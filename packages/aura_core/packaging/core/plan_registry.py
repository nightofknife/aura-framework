# -*- coding: utf-8 -*-
"""Plan registry for loading plans, schedules, interrupts, and task definitions."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ...api import service_registry
from packages.aura_core.observability.logging.core_logger import logger


class PlanRegistry:
    def __init__(self, scheduler: Any):
        self._scheduler = scheduler

    def load_all(self):
        self._scheduler.plan_manager.initialize()
        self.load_plan_specific_data()

    def load_plan_specific_data(self):
        config_service = service_registry.get_service_instance("config")

        def load_core():
            logger.info("--- Loading plan-specific data ---")
            self._scheduler.schedule_items.clear()
            self._scheduler.interrupt_definitions.clear()
            self._scheduler.user_enabled_globals.clear()
            self._scheduler.all_tasks_definitions.clear()

            # 使用 PackageManager
            plan_manager = self._scheduler.plan_manager

            for package_id, manifest in plan_manager.package_manager.loaded_packages.items():
                # 只处理计划包（在 plans/ 目录下）
                if manifest.path.parent.name != "plans":
                    continue

                plan_name = manifest.path.name
                config_path = manifest.path / "config.yaml"
                if config_path.is_file():
                    try:
                        with open(config_path, "r", encoding="utf-8") as f:
                            config_data = yaml.safe_load(f) or {}
                        config_service.register_plan_config(plan_name, config_data)
                    except Exception as exc:
                        logger.error(f"Failed to load config '{config_path}': {exc}")

                self.load_schedule_file(manifest.path, plan_name)
                self.load_interrupt_file(manifest.path, plan_name)

            self.load_all_tasks_definitions()

        if self._scheduler._loop and self._scheduler._loop.is_running():
            async def async_load():
                async with self._scheduler.get_async_lock():
                    load_core()

            # TODO: 修复潜在的死锁风险
            # 问题：使用 future.result(timeout=5) 等待异步加载完成，
            # 如果 async_load() 内部也在等待同一个锁，会导致死锁。
            #
            # 当前场景：
            # 1. 外部线程持有某个锁A，调用此方法
            # 2. async_load() 通过 get_async_lock() 尝试获取异步锁B
            # 3. 如果事件循环正在执行的任务也持有锁B并等待锁A，死锁发生
            #
            # 解决方案：
            # 1. 使用异步条件变量 (asyncio.Condition) 代替混合使用同步锁和异步锁
            # 2. 或者将加载逻辑拆分，避免在锁内等待异步操作
            # 3. 或者使用 asyncio.wait_for() 并设置合理的超时，记录警告
            #
            # 相关代码：
            # - packages/aura_core/scheduler/core.py:191 (get_async_lock)
            # - packages/aura_core/plan_registry.py:82-84
            #
            # 发现日期：2026-01-14
            # 优先级：中等（目前未遇到实际问题，但在高并发场景下可能触发）
            future = asyncio.run_coroutine_threadsafe(async_load(), self._scheduler._loop)
            try:
                future.result(timeout=5)
            except Exception as exc:
                logger.error(f"Async load plan data failed: {exc}")
                with self._scheduler.fallback_lock:
                    load_core()
        else:
            with self._scheduler.fallback_lock:
                load_core()

    def load_all_tasks_definitions(self):
        logger.info("--- Loading all task definitions ---")
        self._scheduler.all_tasks_definitions.clear()
        plans_dir = self._scheduler.base_path / "plans"
        if not plans_dir.is_dir():
            return
        for plan_path in plans_dir.iterdir():
            if not plan_path.is_dir():
                continue
            plan_name = plan_path.name
            tasks_dir = plan_path / "tasks"
            if not tasks_dir.is_dir():
                continue
            for task_file_path in tasks_dir.rglob("*.yaml"):
                try:
                    with open(task_file_path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if not isinstance(data, dict):
                        continue

                    def process_task_definitions(task_data, base_id):
                        for task_key, task_definition in task_data.items():
                            if isinstance(task_definition, dict) and "meta" in task_definition:
                                task_definition.setdefault("execution_mode", "sync")
                                full_task_id = f"{plan_name}/{base_id}/{task_key}".replace("//", "/")
                                self._scheduler.all_tasks_definitions[full_task_id] = task_definition
                                # ✅ 移除别名机制，避免任务列表中出现重复
                                # 旧的别名逻辑已被注释掉：
                                # if task_key == Path(base_id).name:
                                #     alias_id = f"{plan_name}/{base_id}".replace("//", "/")
                                #     self._scheduler.all_tasks_definitions.setdefault(alias_id, task_definition)

                    if "steps" in data:
                        task_name_from_file = task_file_path.relative_to(tasks_dir).with_suffix("").as_posix()
                        data.setdefault("execution_mode", "sync")
                        full_task_id = f"{plan_name}/{task_name_from_file}"
                        self._scheduler.all_tasks_definitions[full_task_id] = data
                    else:
                        relative_path_str = task_file_path.relative_to(tasks_dir).with_suffix("").as_posix()
                        process_task_definitions(data, relative_path_str)

                except Exception as exc:
                    logger.error(f"Failed to load task file '{task_file_path}': {exc}")
        logger.info(f"Task definitions loaded: {len(self._scheduler.all_tasks_definitions)}")

    def load_schedule_file(self, plan_dir: Path, plan_name: str):
        schedule_path = plan_dir / "schedule.yaml"
        if schedule_path.exists():
            try:
                with open(schedule_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                if not isinstance(data, dict):
                    logger.error(f"Schedule file '{schedule_path}' should define a mapping with 'schedules'.")
                    return
                items = data.get("schedules", [])
                if not isinstance(items, list):
                    logger.error(f"Schedule file '{schedule_path}' has invalid 'schedules' format.")
                    return
                for idx, item in enumerate(items):
                    if not isinstance(item, dict):
                        continue
                    task_name = item.get("task")
                    if not task_name:
                        logger.warning(f"Schedule item missing task in '{schedule_path}'.")
                        continue
                    item = dict(item)
                    item["plan_name"] = plan_name
                    item.setdefault("triggers", [])
                    item_id = item.get("id") or f"{plan_name}:{task_name}:{idx}"
                    item["id"] = item_id
                    self._scheduler.schedule_items.append(item)
                    self._scheduler.run_statuses.setdefault(item_id, {"status": "idle"})
            except Exception as exc:
                logger.error(f"Failed to load schedule '{schedule_path}': {exc}")

    def load_interrupt_file(self, plan_dir: Path, plan_name: str):
        interrupt_path = plan_dir / "interrupts.yaml"
        if interrupt_path.exists():
            try:
                with open(interrupt_path, "r", encoding="utf-8") as f:
                    for rule in (yaml.safe_load(f) or {}).get("interrupts", []):
                        rule["plan_name"] = plan_name
                        self._scheduler.interrupt_definitions[rule["name"]] = rule
                        if rule.get("scope") == "global" and rule.get("enabled_by_default", False):
                            self._scheduler.user_enabled_globals.add(rule["name"])
            except Exception as exc:
                logger.error(f"Failed to load interrupts '{interrupt_path}': {exc}")

    def list_plans(self) -> list[str]:
        return self._scheduler.plan_manager.list_plans()

    def list_tasks(self, plan_name: Optional[str] = None) -> list[dict]:
        tasks = self._scheduler.get_all_task_definitions_with_meta()
        if plan_name:
            return [t for t in tasks if t.get("plan_name") == plan_name]
        return tasks

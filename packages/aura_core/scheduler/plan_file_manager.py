# -*- coding: utf-8 -*-
"""Scheduler Plan文件管理器

职责: 管理Plan的文件操作、目录管理和删除操作
"""

import sys
import time
import shutil
import subprocess
import asyncio
from typing import TYPE_CHECKING, Any, Dict, List
from pathlib import Path
from packages.aura_core.observability.logging.core_logger import logger

if TYPE_CHECKING:
    from .core import Scheduler

try:
    from packages.aura_core.packaging.core.dependency_manager import DependencyManager
except ImportError:
    DependencyManager = None


class PlanFileManager:
    """Plan文件管理器

    管理Plan的文件和目录操作，包括:
    - Plan删除
    - 文件列表获取
    - 文件内容读取
    - 任务列表查询
    """

    def __init__(self, scheduler: 'Scheduler'):
        """初始化Plan文件管理器

        Args:
            scheduler: 父调度器实例
        """
        self.scheduler = scheduler

    def delete_plan(self, plan_name: str, *, dry_run: bool = False, backup: bool = True, force: bool = False) -> Dict[str, Any]:
        """删除方案：卸载独有依赖，备份后删除目录并重载计划

        实现来自: scheduler.py 行211-275

        Args:
            plan_name: Plan名称
            dry_run: 仅演练，不实际执行
            backup: 是否备份
            force: 强制执行，忽略错误

        Returns:
            操作结果字典
        """
        plan_dir = (self.scheduler.base_path / "plans" / plan_name).resolve()
        plans_root = (self.scheduler.base_path / "plans").resolve()
        if not plan_dir.is_dir() or plans_root not in plan_dir.parents:
            return {"status": "error", "message": f"Plan '{plan_name}' not found."}

        if not DependencyManager:
            logger.warning("DependencyManager not available, skipping dependency cleanup")
            unique_packages = []
            uninstall_output = ""
        else:
            dep_mgr = DependencyManager(self.scheduler.base_path)
            req_name = dep_mgr._requirements_file_name()

            # 导入utils中的方法
            from .utils import collect_requirement_names

            target_requirements = collect_requirement_names(plan_dir / req_name, dep_mgr)

            other_requirements = set()
            # 其他方案
            for child in plans_root.iterdir():
                if child.is_dir() and child.name != plan_name:
                    other_requirements |= collect_requirement_names(child / req_name, dep_mgr)

            # 全局 requirements.txt 作为基础框架依赖
            other_requirements |= collect_requirement_names(self.scheduler.base_path / "requirements.txt", dep_mgr)

            unique_packages = sorted(target_requirements - other_requirements)

            uninstall_output = ""
            if unique_packages and not dry_run:
                cmd = [sys.executable, "-m", "pip", "uninstall", "-y", *unique_packages]
                try:
                    logger.info("Uninstalling unique dependencies for plan '%s': %s", plan_name, ", ".join(unique_packages))
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    uninstall_output = (result.stdout or "") + (result.stderr or "")
                    if result.returncode != 0 and not force:
                        return {
                            "status": "error",
                            "message": f"Failed to uninstall dependencies (code {result.returncode}).",
                            "uninstall_output": uninstall_output,
                            "packages": unique_packages,
                        }
                except Exception as exc:
                    if not force:
                        return {"status": "error", "message": f"Uninstall failed: {exc}", "packages": unique_packages}
                    uninstall_output = str(exc)

        backup_path = None
        if backup and not dry_run:
            backup_root = self.scheduler.base_path / "backups"
            backup_root.mkdir(exist_ok=True)
            backup_path = backup_root / f"{plan_name}-{int(time.time())}"
            shutil.copytree(plan_dir, backup_path)

        if not dry_run:
            shutil.rmtree(plan_dir, ignore_errors=False)
            try:
                self.scheduler.reload_plans()
            except Exception as exc:
                return {"status": "error", "message": f"Plan removed but reload failed: {exc}", "backup_path": str(backup_path) if backup_path else None}

        return {
            "status": "success",
            "message": f"Plan '{plan_name}' removed" + (" (dry-run)" if dry_run else ""),
            "packages_uninstalled": unique_packages,
            "backup_path": str(backup_path) if backup_path else None,
            "dry_run": dry_run,
            "uninstall_output": uninstall_output,
        }

    def get_all_plans(self) -> List[str]:
        """获取所有已加载Plan的名称列表

        实现来自: scheduler.py 行1304-1321

        Returns:
            Plan名称列表
        """
        async def async_get_plans():
            async with self.scheduler.get_async_lock():
                return self.scheduler.plan_manager.list_plans()

        if hasattr(self.scheduler, '_loop') and self.scheduler._loop and self.scheduler._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_get_plans(), self.scheduler._loop)
            try:
                return future.result(timeout=1)
            except Exception as e:
                logger.error(f"异步获取所有计划失败: {e}")
                with self.scheduler.fallback_lock:
                    return self.scheduler.plan_manager.list_plans()
        else:
            with self.scheduler.fallback_lock:
                return self.scheduler.plan_manager.list_plans()

    def get_plan_files(self, plan_name: str) -> Dict[str, Any]:
        """获取指定Plan的文件目录树结构

        实现来自: scheduler.py 行1322-1346

        Args:
            plan_name: Plan名称

        Returns:
            文件树字典

        Raises:
            FileNotFoundError: Plan目录不存在
        """
        logger.debug(f"请求获取 '{plan_name}' 的文件树...")
        plan_path = self.scheduler.base_path / 'plans' / plan_name
        if not plan_path.is_dir():
            error_msg = f"Plan directory not found for plan '{plan_name}' at path: {plan_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        tree = {}
        for path in sorted(plan_path.rglob('*')):
            if any(part in ['.git', '__pycache__', '.idea'] for part in path.parts):
                continue
            relative_parts = path.relative_to(plan_path).parts
            current_level = tree
            for part in relative_parts[:-1]:
                current_level = current_level.setdefault(part, {})
            final_part = relative_parts[-1]
            if path.is_file():
                current_level[final_part] = None
            elif path.is_dir() and not any(path.iterdir()):
                current_level.setdefault(final_part, {})
        logger.debug(f"为 '{plan_name}' 构建的文件树: {tree}")
        return tree

    def get_tasks_for_plan(self, plan_name: str) -> List[str]:
        """获取指定Plan下所有任务的名称列表

        实现来自: scheduler.py 行1347-1379

        Args:
            plan_name: Plan名称

        Returns:
            任务名称列表
        """
        async def async_get_tasks():
            async with self.scheduler.get_async_lock():
                tasks = []
                prefix = f"{plan_name}/"
                for task_id in self.scheduler.all_tasks_definitions.keys():
                    if task_id.startswith(prefix):
                        tasks.append(task_id[len(prefix):])
                return sorted(tasks)

        if hasattr(self.scheduler, '_loop') and self.scheduler._loop and self.scheduler._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_get_tasks(), self.scheduler._loop)
            try:
                return future.result(timeout=1)
            except Exception as e:
                logger.error(f"异步获取计划任务失败: {e}")
                with self.scheduler.fallback_lock:
                    tasks = []
                    prefix = f"{plan_name}/"
                    for task_id in self.scheduler.all_tasks_definitions.keys():
                        if task_id.startswith(prefix):
                            tasks.append(task_id[len(prefix):])
                    return sorted(tasks)
        else:
            with self.scheduler.fallback_lock:
                tasks = []
                prefix = f"{plan_name}/"
                for task_id in self.scheduler.all_tasks_definitions.keys():
                    if task_id.startswith(prefix):
                        tasks.append(task_id[len(prefix):])
                return sorted(tasks)

    async def get_file_content(self, plan_name: str, relative_path: str) -> str:
        """异步、安全地读取指定Plan内的文件内容

        实现来自: scheduler.py 行1473-1479

        Args:
            plan_name: Plan名称
            relative_path: 相对路径

        Returns:
            文件内容

        Raises:
            FileNotFoundError: Plan未找到
        """
        orchestrator = self.scheduler.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.get_file_content(relative_path)

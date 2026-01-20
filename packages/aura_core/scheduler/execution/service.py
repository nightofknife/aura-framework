# -*- coding: utf-8 -*-
"""Execution service for submitting tasks."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from packages.aura_core.observability.events import Event, EventBus
from packages.aura_core.observability.logging.core_logger import logger
from ...scheduler.utils import convert_task_reference_to_id
from packages.aura_core.scheduler.queues.task_queue import Tasklet


class ExecutionService:
    def __init__(self, scheduler: Any):
        self._scheduler = scheduler

    def run_manual_task(self, task_id: str) -> Dict[str, Any]:
        if not self._scheduler.is_running or self._scheduler._loop is None or not self._scheduler._loop.is_running():
            return {"status": "error", "message": "Scheduler is not running."}

        schedule_item = None
        for it in self._scheduler.schedule_items:
            if it.get("id") == task_id:
                schedule_item = it
                break
        if not schedule_item:
            return {"status": "error", "message": f"Task id '{task_id}' not found in schedule."}

        plan_name = schedule_item.get("plan_name")
        task_name = schedule_item.get("task")
        if not plan_name or not task_name:
            return {"status": "error", "message": "Schedule item missing plan_name/task."}

        full_task_id = f"{plan_name}/{task_name}"

        provided_inputs = schedule_item.get("inputs") or {}
        inputs_spec = {}
        task_def = None

        try:
            if hasattr(self._scheduler, "task_definitions") and isinstance(self._scheduler.task_definitions, dict):
                task_def = self._scheduler.task_definitions.get(full_task_id)
            if task_def is None and hasattr(self._scheduler, "plan_definitions"):
                plan_def = self._scheduler.plan_definitions.get(plan_name) if isinstance(self._scheduler.plan_definitions, dict) else None
                if isinstance(plan_def, dict):
                    tasks_map = plan_def.get("tasks") or {}
                    task_def = tasks_map.get(task_name)
            if isinstance(task_def, dict):
                inputs_spec = task_def.get("inputs") or {}
        except Exception:
            inputs_spec = {}

        defaults = {}
        required_keys = []
        for key, meta in (inputs_spec.items() if isinstance(inputs_spec, dict) else []):
            if isinstance(meta, dict):
                if "default" in meta:
                    defaults[key] = meta.get("default")
                if meta.get("required"):
                    required_keys.append(key)

        merged_inputs = {**defaults, **(provided_inputs or {})}

        missing = [k for k in required_keys if (merged_inputs.get(k) is None or merged_inputs.get(k) == "")]
        if missing:
            return {"status": "error", "message": f"Missing required inputs: {', '.join(missing)}"}

        try:
            tasklet = Tasklet(
                task_name=full_task_id,
                payload={"plan_name": plan_name, "task_name": task_name, "inputs": merged_inputs},
            )
            self._scheduler._ensure_tasklet_identifiers(tasklet, plan_name=plan_name, task_name=task_name, source="manual")
        except Exception as exc:
            logger.error(f"Create Tasklet failed: {exc}", exc_info=True)
            return {"status": "error", "message": f"Create Tasklet failed: {exc}"}

        async def _enqueue():
            try:
                await self._scheduler.event_bus.publish(
                    Event(
                        name="queue.enqueued",
                        payload={
                            "cid": tasklet.cid,
                            "trace_id": tasklet.trace_id,
                            "trace_label": tasklet.trace_label,
                            "source": tasklet.source,
                            "plan_name": plan_name,
                            "task_name": task_name,
                            "priority": None,
                            "enqueued_at": time.time(),
                            "delay_until": None,
                        },
                    )
                )
            except Exception:
                pass
            await self._scheduler.task_queue.put(tasklet)

        try:
            fut = asyncio.run_coroutine_threadsafe(_enqueue(), self._scheduler._loop)
            fut.result(timeout=5.0)
        except Exception as exc:
            logger.error(f"Enqueue task failed: {exc}", exc_info=True)
            return {"status": "error", "message": f"Enqueue failed: {exc}"}

        return {
            "status": "success",
            "message": "Task enqueued.",
            "cid": tasklet.cid,
            "trace_id": tasklet.trace_id,
            "trace_label": tasklet.trace_label,
        }

    def run_ad_hoc_task(
        self,
        plan_name: str,
        task_name: str,
        params: Optional[Dict[str, Any]] = None,
        temp_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = params or {}
        canonical_id = str(next(self._scheduler.id_generator))

        async def async_run():
            async with self._scheduler.get_async_lock():
                orchestrator = self._scheduler.plan_manager.get_plan(plan_name)
                if not orchestrator:
                    return {"status": "error", "message": f"Plan '{plan_name}' not found or not loaded."}

                # ✅ 使用 TaskReference 转换任务名称格式
                from packages.aura_core.types import TaskReference
                try:
                    task_ref = TaskReference.from_string(task_name, default_package=plan_name)
                    loader_path = task_ref.as_loader_path()
                except Exception as e:
                    return {"status": "error", "message": f"Invalid task reference '{task_name}': {e}"}

                # 检查任务是否存在
                if orchestrator.task_loader.get_task_data(loader_path) is None:
                    return {"status": "error", "message": f"在方案 '{plan_name}' 中找不到任务定义: '{task_name}'"}

                full_task_id = convert_task_reference_to_id(plan_name, task_name)
                task_def = self._scheduler.all_tasks_definitions.get(full_task_id) or orchestrator.task_loader.get_task_data(loader_path)
                if not task_def:
                    return {"status": "error", "message": f"Task '{task_name}' not found in plan '{plan_name}'."}

                inputs_meta = task_def.get("meta", {}).get("inputs", [])
                ok, validated_inputs = self._scheduler._validate_inputs_against_meta(inputs_meta, params)
                if not ok:
                    msg = f"Task '{full_task_id}' inputs invalid: {validated_inputs}"
                    logger.error(msg)
                    return {"status": "error", "message": msg}

                tasklet = Tasklet(
                    task_name=full_task_id,
                    cid=canonical_id,
                    is_ad_hoc=True,
                    payload={"plan_name": plan_name, "task_name": task_name},
                    execution_mode=task_def.get("execution_mode", "sync"),
                    initial_context=validated_inputs,
                )
                self._scheduler._ensure_tasklet_identifiers(tasklet, plan_name=plan_name, task_name=task_name, source="manual")

            if self._scheduler.task_queue:
                await self._scheduler.task_queue.put(tasklet)
                await self._scheduler._async_update_run_status(full_task_id, {"status": "queued"})

                try:
                    await self._scheduler.event_bus.publish(
                        Event(
                            name="queue.enqueued",
                            payload={
                                "cid": tasklet.cid,
                                "trace_id": tasklet.trace_id,
                                "trace_label": tasklet.trace_label,
                                "source": tasklet.source,
                                "plan_name": plan_name,
                                "task_name": task_name,
                                "priority": (self._scheduler.all_tasks_definitions.get(full_task_id) or {}).get("priority"),
                                "enqueued_at": datetime.now().timestamp(),
                                "delay_until": None,
                            },
                        )
                    )
                except Exception:
                    pass

            return {
                "status": "success",
                "message": f"Task '{full_task_id}' queued for execution.",
                "temp_id": temp_id,
                "cid": tasklet.cid,
                "trace_id": tasklet.trace_id,
                "trace_label": tasklet.trace_label,
            }

        if self._scheduler._loop and self._scheduler._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_run(), self._scheduler._loop)
            try:
                return future.result(timeout=5)
            except Exception as exc:
                full_id = f"{plan_name}/{task_name}"
                logger.warning(f"Ad-hoc task failed for '{full_id}': {exc}")
                return {"status": "error", "message": str(exc), "temp_id": temp_id}
        else:
            with self._scheduler.fallback_lock:
                logger.info(f"Scheduler not running, buffering ad-hoc task '{plan_name}/{task_name}'")
                full_task_id = convert_task_reference_to_id(plan_name, task_name)
                task_def = self._scheduler.all_tasks_definitions.get(full_task_id, {})
                inputs_meta = task_def.get("meta", {}).get("inputs", [])
                ok, validated_inputs = self._scheduler._validate_inputs_against_meta(inputs_meta, params or {})
                if not ok:
                    return {"status": "error", "message": f"Task '{full_task_id}' inputs invalid: {validated_inputs}"}
                tasklet = Tasklet(
                    task_name=full_task_id,
                    cid=canonical_id,
                    is_ad_hoc=True,
                    payload={"plan_name": plan_name, "task_name": task_name},
                    execution_mode=task_def.get("execution_mode", "sync"),
                    initial_context=validated_inputs,
                )
                self._scheduler._ensure_tasklet_identifiers(tasklet, plan_name=plan_name, task_name=task_name, source="manual")
                self._scheduler._pre_start_task_buffer.append(tasklet)
                self._scheduler.run_statuses.setdefault(full_task_id, {}).update({"status": "queued", "queued_at": datetime.now()})
                return {
                    "status": "success",
                    "message": f"Task '{full_task_id}' queued for execution.",
                    "temp_id": temp_id,
                    "cid": tasklet.cid,
                    "trace_id": tasklet.trace_id,
                    "trace_label": tasklet.trace_label,
                }

    def run_batch_ad_hoc_tasks(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        results = []
        success_count = 0
        failed_count = 0

        for task in tasks:
            try:
                result = self.run_ad_hoc_task(
                    plan_name=task.get("plan_name"),
                    task_name=task.get("task_name"),
                    params=task.get("inputs", {}),
                )

                if result.get("status") == "success":
                    success_count += 1
                else:
                    failed_count += 1

                results.append(
                    {
                        "plan_name": task.get("plan_name"),
                        "task_name": task.get("task_name"),
                        "status": result.get("status"),
                        "message": result.get("message"),
                        "cid": result.get("cid"),
                        "trace_id": result.get("trace_id"),
                        "trace_label": result.get("trace_label"),
                    }
                )
            except Exception as exc:
                failed_count += 1
                results.append(
                    {
                        "plan_name": task.get("plan_name"),
                        "task_name": task.get("task_name"),
                        "status": "error",
                        "message": str(exc),
                        "cid": None,
                        "trace_id": None,
                        "trace_label": None,
                    }
                )

        return {"results": results, "success_count": success_count, "failed_count": failed_count}

    def run_batch(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.run_batch_ad_hoc_tasks(tasks)

    def run_ad_hoc(self, plan_name: str, task_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.run_ad_hoc_task(plan_name, task_name, params)

    def run_manual_schedule(self, item_id: str) -> Dict[str, Any]:
        return self.run_manual_task(item_id)

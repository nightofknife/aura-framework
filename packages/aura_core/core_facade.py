# -*- coding: utf-8 -*-
"""Compatibility facade for backend APIs.

This facade keeps existing API behavior stable while allowing internal
services to evolve. It forwards calls to the underlying Scheduler or
to specialized services when provided.
"""
from __future__ import annotations

from typing import Any, Optional


class CoreFacade:
    def __init__(
        self,
        scheduler: Any,
        observability: Optional[Any] = None,
        dispatch: Optional[Any] = None,
        registry: Optional[Any] = None,
        hot_reload: Optional[Any] = None,
        executor: Optional[Any] = None,
    ):
        self._scheduler = scheduler
        self._observability = observability
        self._dispatch = dispatch
        self._registry = registry
        self._hot_reload = hot_reload
        self._executor = executor

    def __getattr__(self, name: str) -> Any:
        return getattr(self._scheduler, name)

    @property
    def actions(self) -> Any:
        return self._scheduler.actions

    @property
    def base_path(self) -> Any:
        return self._scheduler.base_path

    @property
    def api_log_queue(self) -> Any:
        return self._scheduler.api_log_queue

    # ---- system ----
    def get_master_status(self) -> dict:
        return self._scheduler.get_master_status()

    def get_metrics_snapshot(self) -> dict:
        if self._observability:
            return self._observability.get_metrics_snapshot()
        return self._scheduler.get_metrics_snapshot()

    def start_scheduler(self) -> None:
        return self._scheduler.start_scheduler()

    def stop_scheduler(self) -> None:
        return self._scheduler.stop_scheduler()

    # ---- plans/tasks ----
    def get_all_plans(self) -> list[str]:
        if self._registry:
            return self._registry.list_plans()
        return self._scheduler.get_all_plans()

    def get_all_task_definitions_with_meta(self) -> list[dict]:
        if self._registry:
            return self._registry.list_tasks()
        return self._scheduler.get_all_task_definitions_with_meta()

    def get_plan_files(self, plan_name: str) -> dict:
        return self._scheduler.get_plan_files(plan_name)

    async def get_file_content(self, plan_name: str, path: str) -> str:
        return await self._scheduler.get_file_content(plan_name, path)

    async def save_file_content(self, plan_name: str, path: str, content: bytes) -> None:
        return await self._scheduler.save_file_content(plan_name, path, content)

    async def reload_task_file(self, file_path) -> None:
        return await self._scheduler.reload_task_file(file_path)

    def delete_plan(self, plan_name: str, *, dry_run: bool = False, backup: bool = True, force: bool = False) -> dict:
        return self._scheduler.delete_plan(plan_name, dry_run=dry_run, backup=backup, force=force)

    # ---- execution ----
    def run_ad_hoc_task(self, plan_name: str, task_name: str, params: dict) -> dict:
        if self._executor:
            return self._executor.run_ad_hoc(plan_name, task_name, params)
        return self._scheduler.run_ad_hoc_task(plan_name, task_name, params)

    def run_batch_ad_hoc_tasks(self, tasks: list[dict]) -> dict:
        if self._executor:
            return self._executor.run_batch(tasks)
        return self._scheduler.run_batch_ad_hoc_tasks(tasks)

    def run_manual_task(self, item_id: str) -> dict:
        if self._executor:
            return self._executor.run_manual_schedule(item_id)
        return self._scheduler.run_manual_task(item_id)

    def get_batch_task_status(self, cids: list[str]) -> list[dict]:
        return self._scheduler.get_batch_task_status(cids)

    # ---- queue/dispatch ----
    def get_queue_overview(self) -> dict:
        if self._dispatch:
            return self._dispatch.get_queue_overview()
        return self._scheduler.get_queue_overview()

    def list_queue(self, state: str, limit: int = 200) -> dict:
        if self._dispatch:
            return self._dispatch.list_queue(state, limit)
        return self._scheduler.list_queue(state, limit)

    async def queue_insert_at(self, index: int, plan_name: str, task_name: str, params: dict | None = None) -> dict:
        if self._dispatch:
            return await self._dispatch.queue_insert_at(index, plan_name, task_name, params)
        return await self._scheduler.queue_insert_at(index, plan_name, task_name, params)

    async def queue_remove_task(self, cid: str) -> dict:
        if self._dispatch:
            return await self._dispatch.queue_remove(cid)
        return await self._scheduler.queue_remove_task(cid)

    async def queue_move_to_front(self, cid: str) -> dict:
        if self._dispatch:
            return await self._dispatch.queue_move_to_front(cid)
        return await self._scheduler.queue_move_to_front(cid)

    async def queue_move_to_position(self, cid: str, position: int) -> dict:
        if self._dispatch:
            return await self._dispatch.queue_move_to_position(cid, position)
        return await self._scheduler.queue_move_to_position(cid, position)

    async def queue_list_all(self) -> list[dict]:
        if self._dispatch:
            return await self._dispatch.queue_list_all()
        return await self._scheduler.queue_list_all()

    async def queue_clear(self) -> dict:
        if self._dispatch:
            return await self._dispatch.queue_clear()
        return await self._scheduler.queue_clear()

    async def queue_reorder(self, cid_order: list[str]) -> dict:
        if self._dispatch:
            return await self._dispatch.queue_reorder(cid_order)
        return await self._scheduler.queue_reorder(cid_order)

    # ---- observability ----
    def get_active_runs_snapshot(self) -> list[dict]:
        if self._observability:
            return self._observability.get_active_runs_snapshot()
        return self._scheduler.get_active_runs_snapshot()

    def get_run_timeline(self, run_id: str) -> dict:
        if self._observability:
            return self._observability.get_run_timeline(run_id)
        return self._scheduler.get_run_timeline(run_id)

    def list_persisted_runs(self, **filters) -> list[dict]:
        if self._observability:
            return self._observability.list_persisted_runs(**filters)
        return self._scheduler.list_persisted_runs(**filters)

    def get_persisted_run(self, run_id: str) -> dict | None:
        if self._observability:
            return self._observability.get_persisted_run(run_id)
        return self._scheduler.get_persisted_run(run_id)

    def get_ui_event_queue(self):
        if self._observability:
            return self._observability.get_ui_event_queue()
        return self._scheduler.get_ui_event_queue()

    def trigger_full_ui_update(self) -> None:
        return self._scheduler.trigger_full_ui_update()

    # ---- hot reload ----
    def enable_hot_reload(self) -> dict:
        if self._hot_reload:
            return self._hot_reload.enable()
        return self._scheduler.enable_hot_reload()

    def disable_hot_reload(self) -> dict:
        if self._hot_reload:
            return self._hot_reload.disable()
        return self._scheduler.disable_hot_reload()

    def is_hot_reload_enabled(self) -> bool:
        if self._hot_reload:
            return self._hot_reload.is_enabled()
        return self._scheduler.is_hot_reload_enabled()

# -*- coding: utf-8 -*-
"""Scheduler状态管理器

职责: 管理调度器的运行状态、任务状态和调度状态
"""

import asyncio
import queue
import threading
from typing import TYPE_CHECKING, Any, Dict, Callable, List
from packages.aura_core.observability.logging.core_logger import logger
from packages.aura_core.api import service_registry
from datetime import datetime

if TYPE_CHECKING:
    from .core import Scheduler


class StateManager:
    """状态管理器

    管理调度器的各类状态，包括:
    - 运行任务状态
    - 调度状态
    - 主状态
    """

    def __init__(self, scheduler: 'Scheduler'):
        """初始化状态管理器

        Args:
            scheduler: 父调度器实例
        """
        self.scheduler = scheduler

    def update_run_status(self, item_id: str, status_update: Dict[str, Any]):
        """线程安全地更新一个计划任务的运行状态

        实现来自: scheduler.py 行1120-1136

        Args:
            item_id: 任务项ID
            status_update: 状态更新字典
        """
        if hasattr(self.scheduler, '_loop') and self.scheduler._loop and self.scheduler._loop.is_running():
            # 使用非阻塞方式，避免潜在死锁
            try:
                asyncio.run_coroutine_threadsafe(
                    self._async_update_run_status(item_id, status_update),
                    self.scheduler._loop
                )
                # 不等待结果，避免阻塞调用线程
            except Exception as e:
                logger.error(f"提交异步更新运行状态失败: {e}")
                # 降级到同步方式
                self._sync_update_run_status(item_id, status_update)
        else:
            self._sync_update_run_status(item_id, status_update)

    async def _async_update_run_status(self, item_id: str, status_update: Dict[str, Any]):
        """异步地更新一个计划任务的运行状态

        实现来自: scheduler.py 行400-412

        Args:
            item_id: 任务项ID
            status_update: 状态更新字典
        """
        async with self.scheduler.get_async_lock():
            if item_id:
                self.scheduler.run_statuses.setdefault(item_id, {}).update(status_update)
                if hasattr(self.scheduler, 'ui_update_queue') and self.scheduler.ui_update_queue:
                    try:
                        self.scheduler.ui_update_queue.put_nowait(
                            {'type': 'run_status_single_update', 'data': {'id': item_id, **self.scheduler.run_statuses[item_id]}}
                        )
                    except queue.Full:
                        logger.warning("UI更新队列已满，丢弃消息: run_status_single_update")

    def _sync_update_run_status(self, item_id: str, status_update: Dict[str, Any]):
        """同步方式更新运行状态（fallback）

        实现来自: scheduler.py 行1137-1151

        Args:
            item_id: 任务项ID
            status_update: 状态更新字典
        """
        with self.scheduler.fallback_lock:
            if item_id:
                self.scheduler.run_statuses.setdefault(item_id, {}).update(status_update)
                if hasattr(self.scheduler, 'ui_update_queue') and self.scheduler.ui_update_queue:
                    try:
                        self.scheduler.ui_update_queue.put_nowait({
                            'type': 'run_status_single_update',
                            'data': {'id': item_id, **self.scheduler.run_statuses[item_id]}
                        })
                    except queue.Full:
                        logger.warning("UI更新队列已满，丢弃消息: run_status_single_update")

    def get_running_tasks_count(self) -> int:
        """线程安全地获取运行中任务数量

        实现来自: scheduler.py 行1152-1172

        优化：直接使用 fallback_lock，避免异步锁竞争导致的超时

        Returns:
            运行中任务的数量
        """
        # ✅ 优化：直接使用 fallback_lock，避免事件循环调度开销
        # len(dict) 是原子操作，不需要异步锁
        with self.scheduler.fallback_lock:
            return len(self.scheduler.running_tasks)

    async def _async_get_running_tasks_count(self) -> int:
        """异步获取运行中任务数量

        实现来自: scheduler.py 行1173-1178

        Returns:
            运行中任务的数量
        """
        async with self.scheduler.async_data_lock:
            return len(self.scheduler.running_tasks)

    def get_running_tasks_snapshot(self) -> Dict[str, Any]:
        """获取运行中任务的快照（线程安全）

        实现来自: scheduler.py 行1179-1195

        Returns:
            运行中任务的快照字典
        """
        if hasattr(self.scheduler, '_loop') and self.scheduler._loop and self.scheduler._loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._async_get_running_tasks_snapshot(),
                    self.scheduler._loop
                )
                return future.result(timeout=2)
            except Exception as e:
                logger.warning(f"异步获取运行中任务快照失败: {e}")
                with self.scheduler.fallback_lock:
                    return self._fallback_running_tasks_snapshot()
        else:
            with self.scheduler.fallback_lock:
                return self._fallback_running_tasks_snapshot()

    async def _async_get_running_tasks_snapshot(self) -> Dict[str, Any]:
        """异步获取运行中任务快照

        实现来自: scheduler.py 行1196-1209

        Returns:
            运行中任务的快照字典
        """
        async with self.scheduler.async_data_lock:
            return {
                cid: {
                    'task_name': meta.get('task_name'),
                    'start_time': meta.get('start_time').isoformat() if meta.get('start_time') else None,
                    'duration_sec': (datetime.now() - meta.get('start_time')).total_seconds()
                    if meta.get('start_time') else 0
                }
                for cid, meta in self.scheduler._running_task_meta.items()
            }

    def _fallback_running_tasks_snapshot(self) -> Dict[str, Any]:
        """Fallback方式获取运行中任务快照

        实现来自: scheduler.py 行1210-1222

        Returns:
            运行中任务的快照字典
        """
        return {
            cid: {
                'task_name': meta.get('task_name'),
                'start_time': meta.get('start_time').isoformat() if meta.get('start_time') else None,
                'duration_sec': (datetime.now() - meta.get('start_time')).total_seconds()
                if meta.get('start_time') else 0
            }
            for cid, meta in self.scheduler._running_task_meta.items()
        }

    def get_master_status(self) -> dict:
        """获取调度器的宏观运行状态

        实现来自: scheduler.py 行1231-1235

        Returns:
            包含运行状态的字典
        """
        is_running = (
            hasattr(self.scheduler.lifecycle, '_scheduler_thread') and
            self.scheduler.lifecycle._scheduler_thread is not None and
            self.scheduler.lifecycle._scheduler_thread.is_alive()
        )
        return {"is_running": is_running}

    def get_schedule_status(self):
        """获取所有预定义计划任务的当前状态列表

        实现来自: scheduler.py 行1236-1257

        Returns:
            调度任务状态列表
        """
        if hasattr(self.scheduler, '_loop') and self.scheduler._loop and self.scheduler._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._async_get_schedule_status(), self.scheduler._loop)
            try:
                return future.result(timeout=2)
            except Exception as e:
                logger.error(f"异步获取调度状态失败: {e}")
                with self.scheduler.fallback_lock:
                    schedule_items_copy = list(self.scheduler.schedule_items)
                    run_statuses_copy = dict(self.scheduler.run_statuses)
        else:
            with self.scheduler.fallback_lock:
                schedule_items_copy = list(self.scheduler.schedule_items)
                run_statuses_copy = dict(self.scheduler.run_statuses)

        status_list = []
        for item in schedule_items_copy:
            full_status = item.copy()
            full_status.update(run_statuses_copy.get(item.get('id'), {}))
            status_list.append(full_status)
        return status_list

    async def _async_get_schedule_status(self):
        """异步地获取所有计划任务的状态列表

        实现来自: scheduler.py 行413-424

        Returns:
            调度任务状态列表
        """
        async with self.scheduler.get_async_lock():
            schedule_items_copy = list(self.scheduler.schedule_items)
            run_statuses_copy = dict(self.scheduler.run_statuses)

        status_list = []
        for item in schedule_items_copy:
            full_status = item.copy()
            full_status.update(run_statuses_copy.get(item.get('id'), {}))
            status_list.append(full_status)
        return status_list

    async def _async_update_shared_state(self, update_func: Callable[[], None], read_only: bool = False):
        """在异步锁的保护下执行一个对共享状态的更新操作

        实现来自: scheduler.py 行425-433

        Args:
            update_func: 更新函数
            read_only: 是否为只读操作
        """
        if read_only:
            async with self.scheduler.get_async_lock():
                update_func()
        else:
            async with self.scheduler.get_async_lock():
                update_func()

    def get_all_services_status(self) -> List[Dict[str, Any]]:
        """获取所有已注册服务的当前状态列表

        Returns:
            服务状态列表
        """
        if hasattr(self.scheduler, '_loop') and self.scheduler._loop and self.scheduler._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._async_get_all_services_status(), self.scheduler._loop)
            try:
                return future.result(timeout=2)
            except Exception as e:
                logger.error(f"异步获取所有服务状态失败: {e}")
                with self.scheduler.fallback_lock:
                    service_defs = service_registry.get_all_service_definitions()
                    return [s.__dict__ for s in service_defs]
        else:
            with self.scheduler.fallback_lock:
                service_defs = service_registry.get_all_service_definitions()
                return [s.__dict__ for s in service_defs]

    async def _async_get_all_services_status(self) -> List[Dict[str, Any]]:
        """异步获取所有服务状态

        Returns:
            服务状态列表
        """
        async with self.scheduler.get_async_lock():
            service_defs = service_registry.get_all_service_definitions()
            return [s.__dict__ for s in service_defs]

    def get_all_interrupts_status(self) -> List[Dict[str, Any]]:
        """获取所有已定义中断规则的当前状态列表

        Returns:
            中断规则状态列表
        """
        if hasattr(self.scheduler, '_loop') and self.scheduler._loop and self.scheduler._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._async_get_all_interrupts_status(), self.scheduler._loop)
            try:
                return future.result(timeout=2)
            except Exception as e:
                logger.error(f"异步获取所有中断状态失败: {e}")
                with self.scheduler.fallback_lock:
                    return self._fallback_get_all_interrupts_status()
        else:
            with self.scheduler.fallback_lock:
                return self._fallback_get_all_interrupts_status()

    async def _async_get_all_interrupts_status(self) -> List[Dict[str, Any]]:
        """异步获取所有中断状态

        Returns:
            中断规则状态列表
        """
        async with self.scheduler.get_async_lock():
            status_list = []
            for name, definition in self.scheduler.interrupt_definitions.items():
                status_item = definition.copy()
                status_item['is_global_enabled'] = name in self.scheduler.user_enabled_globals
                status_list.append(status_item)
            return status_list

    def _fallback_get_all_interrupts_status(self) -> List[Dict[str, Any]]:
        """Fallback方式获取所有中断状态

        Returns:
            中断规则状态列表
        """
        status_list = []
        for name, definition in self.scheduler.interrupt_definitions.items():
            status_item = definition.copy()
            status_item['is_global_enabled'] = name in self.scheduler.user_enabled_globals
            status_list.append(status_item)
        return status_list

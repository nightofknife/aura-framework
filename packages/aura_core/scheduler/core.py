# -*- coding: utf-8 -*-
"""Aura 框架的核心调度器。

此模块定义了 `Scheduler` 类，它是整个 Aura 框架的"大脑"和主入口点。
`Scheduler` 负责初始化和协调所有核心服务，管理主事件循环，处理任务的
入队和执行，并提供一个统一的外部 API 来与框架交互。

主要职责:
- **生命周期管理**: 启动和停止主事件循环以及所有相关的后台服务。
- **服务协调**: 初始化并持有对所有核心服务（如 `PlanManager`,
  `ExecutionManager`, `EventBus` 等）的引用。
- **资源加载**: 协调 `PlanManager` 加载所有插件、任务、配置、调度项和中断规则。
- **任务队列**: 管理主任务队列、事件驱动任务队列和中断队列。
- **主循环与消费者**: 运行多个异步消费者来处理不同队列中的任务。
- **状态查询 API**: 提供一系列线程安全的方法来查询框架的内部状态，如
  运行状态、计划任务、服务和中断等。
- **热重载**: 实现 `HotReloadPolicy` 来监控文件系统变动，并触发对
  任务或整个插件的实时、动态重载。
"""
import asyncio
import json
import os
import queue
import re
import sys
import threading
from asyncio import TaskGroup
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Any, List, Optional, Tuple, Union

from packages.aura_core.observability.events import EventBus, Event
from packages.aura_core.context.persistence.store_service import StateStoreService
from packages.aura_core.scheduler.queues.task_queue import TaskQueue, Tasklet
from packages.aura_core.observability.logging.core_logger import logger
from plans.aura_base.src.services.config_service import ConfigService
from packages.aura_core.api.registries import service_registry
from packages.aura_core.utils.id_generator import SnowflakeGenerator
from packages.aura_core.config.loader import get_config_value
from packages.aura_core.observability.service import ObservabilityService
from packages.aura_core.packaging.core.plan_registry import PlanRegistry
from packages.aura_core.scheduler.execution.dispatcher import DispatchService
from packages.aura_core.scheduler.execution.service import ExecutionService
from packages.aura_core.utils.hot_reload import HotReloadPolicy

# 导入核心管理器
from packages.aura_core.scheduler.execution.manager import ExecutionManager
from packages.aura_core.scheduler.queues.interrupt import InterruptService
from packages.aura_core.packaging.core.plan_manager import PlanManager
from packages.aura_core.scheduler.scheduling_service import SchedulingService

# 导入子管理器
from .lifecycle import LifecycleManager
from .task_dispatcher import TaskDispatcher
from .state_manager import StateManager
from .plan_file_manager import PlanFileManager
from .validation import InputValidator
from .ui_bridge import UIBridge
from .utils import *

if TYPE_CHECKING:
    from packages.aura_core.scheduler.orchestrator import Orchestrator

# Sentinel object for missing values
_MISSING = object()



class Scheduler:
    """Aura 框架的核心调度器和总协调器。"""

    def __init__(self):
        """初始化 Scheduler 实例。

        此构造函数会初始化所有核心服务和状态属性，并执行首次的资源加载。
        """
        # --- 核心属性与状态 (非异步部分) ---
        self.base_path = self._resolve_base_path()
        if str(self.base_path) not in sys.path:
            sys.path.insert(0, str(self.base_path))

        self._main_task: Optional[asyncio.Task] = None
        self._scheduler_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._hot_reload_observer = None

        self.num_event_workers = int(get_config_value("scheduler.num_event_workers", 1))
        self.startup_complete_event = threading.Event()
        self._pre_start_task_buffer: List = []
        self.fallback_lock = threading.RLock()

        # 添加启动锁，保护启动/停止操作
        self._startup_lock = threading.Lock()
        # 新增：资源清理控制
        self._shutdown_lock = threading.Lock()
        self._shutdown_done = False

        self.pause_event = asyncio.Event()
        self.pause_event.set()

        self.id_generator = SnowflakeGenerator(
            instance=int(get_config_value("id_generator.instance_id", 1)),
            epoch=int(get_config_value("id_generator.epoch_ms", 1609459200000)),
        )

        # --- 异步组件 (运行时初始化) ---
        self.is_running: Optional[asyncio.Event] = None
        self.task_queue: Optional[TaskQueue] = None
        self.event_task_queue: Optional[TaskQueue] = None
        self.interrupt_queue: Optional[asyncio.Queue[Dict]] = None
        self.async_data_lock: Optional[asyncio.Lock] = None

        # 使用异步队列而非同步队列（将在 _initialize_async_components 中初始化）
        self.api_log_queue: Optional[asyncio.Queue] = None

        # --- 服务实例 ---
        self.config_service = ConfigService()
        self.event_bus = EventBus()
        self.state_store = StateStoreService(config=self.config_service)
        self.plan_manager = PlanManager(str(self.base_path), self.pause_event)
        self.execution_manager = ExecutionManager(
            self,
            max_concurrent_tasks=int(get_config_value("execution.max_concurrent_tasks", 1)),
            io_workers=int(get_config_value("execution.io_workers", 16)),
            cpu_workers=int(get_config_value("execution.cpu_workers", 4)),
        )
        self.scheduling_service = SchedulingService(self)
        self.interrupt_service = InterruptService(self)

        from packages.aura_core.utils.file_watcher import FileWatcherService
        self.file_watcher_service = FileWatcherService(self.event_bus)

        # --- service wrappers ---
        self.plan_registry = PlanRegistry(self)
        self.dispatch = DispatchService(self)
        self.executor = ExecutionService(self)
        self.hot_reload = HotReloadPolicy(self)

        # --- 运行/调度状态 ---
        self.run_statuses: Dict[str, Dict[str, Any]] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self._running_task_meta: Dict[str, Dict[str, Any]] = {}
        self.schedule_items: List[Dict[str, Any]] = []
        self.interrupt_definitions: Dict[str, Dict[str, Any]] = {}
        self.user_enabled_globals: set[str] = set()
        self.all_tasks_definitions: Dict[str, Any] = {}

        # --- Observability/UI ---
        self.observability = ObservabilityService(
            event_bus=self.event_bus,
            base_path=self.base_path,
            running_tasks_provider=self.get_running_tasks_count,
        )
        # UI event queue is unbounded to avoid dropping updates under burst.
        self.ui_event_queue = self.observability.get_ui_event_queue()
        self.ui_update_queue: Optional[queue.Queue] = None
        # Core subscriptions should be registered only once.
        self._core_subscriptions_ready = False

        # --- 初始化子管理器 ---
        self.lifecycle = LifecycleManager(self)
        self.dispatcher = TaskDispatcher(self)
        self.state_mgr = StateManager(self)
        self.plan_mgr = PlanFileManager(self)
        self.validator = InputValidator(self)
        self.ui_bridge = UIBridge(self)

        # --- 初始化日志和核心服务 ---
        logger.setup(
            log_dir=str(get_config_value("logging.log_dir", "logs")),
            task_name=str(get_config_value("logging.task_name.default", "aura_session")),
            api_log_queue=self.api_log_queue
        )
        self._register_core_services()
        self.reload_plans()

    @staticmethod
    def _resolve_base_path() -> Path:
        """解析项目基础路径

        Returns:
            项目的基础路径
        """
        env_base = os.getenv("AURA_BASE_PATH")
        if env_base:
            return Path(env_base).resolve()
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parents[3]

    def get_async_lock(self) -> asyncio.Lock:
        """获取一个线程安全的异步锁，用于保护共享状态。

        实现来自: scheduler.py 行178-184
        """
        if self.async_data_lock is None:
            self.async_data_lock = asyncio.Lock()
            logger.debug("异步数据锁初始化。")
        return self.async_data_lock

    def _register_core_services(self):
        """(私有) 向服务注册表注册所有框架核心服务。

        实现来自: scheduler.py 行450-472
        """
        # 注意：旧系统的set_project_base_path已随builder模块删除
        # 新系统不需要这个函数，因为不再从源码构建manifest

        service_registry.register_instance('config', self.config_service, public=True, fqid='core/config')
        service_registry.register_instance('state_store', self.state_store, public=True, fqid='core/state_store')
        service_registry.register_instance('event_bus', self.event_bus, public=True, fqid='core/event_bus')

        service_registry.register_instance('scheduler', self, public=True, fqid='core/scheduler')
        service_registry.register_instance('plan_manager', self.plan_manager, public=False, fqid='core/plan_manager')
        service_registry.register_instance('execution_manager', self.execution_manager, public=False,
                                           fqid='core/execution_manager')
        service_registry.register_instance('scheduling_service', self.scheduling_service, public=False,
                                           fqid='core/scheduling_service')
        service_registry.register_instance('interrupt_service', self.interrupt_service, public=False,
                                           fqid='core/interrupt_service')
        service_registry.register_instance('file_watcher_service', self.file_watcher_service, public=False,
                                           fqid='core/file_watcher_service')

        # 手动注入 EventBus 到 StateStore
        self.state_store.set_event_bus(self.event_bus)

    def reload_plans(self):
        """重新加载所有 Plan 和相关配置。

        实现来自: scheduler.py 行473-500
        """
        logger.info("======= Scheduler: 开始加载所有框架资源 =======")
        with self.fallback_lock:
            try:
                config_service = service_registry.get_service_instance('config')
                config_service.load_environment_configs(self.base_path)

                self.plan_registry.load_all()

                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(self._async_reload_subscriptions(), self._loop)
                self.ui_bridge.push_update('full_status_update', {
                    'schedule': self.get_schedule_status(),
                    'services': self.get_all_services_status(),
                    'interrupts': self.get_all_interrupts_status(),
                    'workspace': {
                        'plans': self.get_all_plans(),
                        'actions': self.actions.get_all_action_definitions()
                    }
                })
            except Exception as e:
                logger.critical(f"框架资源加载失败: {e}", exc_info=True)
                raise
        logger.info("======= 资源加载完毕 ... =======")

    async def run(self):
        """调度器的主异步运行方法，包含了所有后台消费者的逻辑。

        实现来自: scheduler.py 行682-720
        """
        self.lifecycle.initialize_async_components()
        self.is_running.set()
        self._loop = asyncio.get_running_loop()
        self._main_task = asyncio.current_task()

        # ✅ 同步设置 lifecycle 的事件循环引用
        self.lifecycle._loop = self._loop
        self.lifecycle._main_task = self._main_task

        async with self.get_async_lock():
            if self._pre_start_task_buffer:
                logger.info(f"正在将 {len(self._pre_start_task_buffer)} 个缓冲任务移入执行队列...")
                for tasklet in self._pre_start_task_buffer:
                    await self.task_queue.put(tasklet)
                self._pre_start_task_buffer.clear()

        logger.info("调度器异步核心 (Commander) 已启动...")
        try:
            await self._async_reload_subscriptions()

            async with TaskGroup() as tg:
                tg.create_task(self._consume_interrupt_queue())
                tg.create_task(self._consume_main_task_queue())
                for i in range(self.num_event_workers):
                    tg.create_task(self._event_worker_loop(i + 1))
                tg.create_task(self.scheduling_service.run())
                tg.create_task(self.interrupt_service.run())

                # ✅ NEW: 启动 ObservabilityService 的清理任务
                self.observability.start_cleanup_task()

                self.file_watcher_service.start()
                logger.info("所有核心后台服务已启动，向主线程发出信号。")
                self.startup_complete_event.set()
        except asyncio.CancelledError:
            logger.info("调度器主任务被取消，正在优雅关闭...")
        finally:
            self.is_running.clear()

            # ✅ NEW: 停止 ObservabilityService 的清理任务
            await self.observability.stop_cleanup_task()

            self.file_watcher_service.stop()
            self._loop = None
            self._main_task = None
            logger.info("调度器主循环 (Commander) 已安全退出。")
            self.startup_complete_event.set()

    # ========== 委托方法 - 生命周期管理 ==========

    def start_scheduler(self):
        """启动调度器的主事件循环和所有后台服务。

        委托给: LifecycleManager.start()
        """
        self.lifecycle.start()

    def stop_scheduler(self):
        """优雅地停止调度器和所有后台服务。

        委托给: LifecycleManager.stop()
        """
        self.lifecycle.stop()

    # ========== 委托方法 - 状态管理 ==========

    def update_run_status(self, item_id: str, status_update: Dict[str, Any]):
        """线程安全地更新一个计划任务的运行状态。

        委托给: StateManager.update_run_status()
        """
        self.state_mgr.update_run_status(item_id, status_update)

    def get_master_status(self) -> dict:
        """获取调度器的宏观运行状态。

        委托给: StateManager.get_master_status()
        """
        return self.state_mgr.get_master_status()

    def get_schedule_status(self):
        """获取所有预定义计划任务的当前状态列表。

        委托给: StateManager.get_schedule_status()
        """
        return self.state_mgr.get_schedule_status()

    def get_running_tasks_count(self) -> int:
        """线程安全地获取运行中任务数量。

        委托给: StateManager.get_running_tasks_count()
        """
        return self.state_mgr.get_running_tasks_count()

    def get_running_tasks_snapshot(self) -> Dict[str, Any]:
        """获取运行中任务的快照（线程安全）。

        委托给: StateManager.get_running_tasks_snapshot()
        """
        return self.state_mgr.get_running_tasks_snapshot()

    # ========== 委托方法 - 任务调度 ==========

    def run_manual_task(self, task_id: str):
        """手动运行计划任务。

        委托给: TaskDispatcher.run_manual_task()
        """
        return self.dispatcher.run_manual_task(task_id)

    def run_ad_hoc_task(self, plan_name: str, task_name: str, params: Optional[Dict[str, Any]] = None, temp_id: Optional[str] = None):
        """运行临时任务。

        委托给: TaskDispatcher.run_ad_hoc_task()
        """
        return self.dispatcher.run_ad_hoc_task(plan_name, task_name, params, temp_id)

    def run_batch_ad_hoc_tasks(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量运行临时任务。

        委托给: TaskDispatcher.run_batch_ad_hoc_tasks()
        """
        return self.dispatcher.run_batch_ad_hoc_tasks(tasks)

    def cancel_task(self, cid: str) -> Dict[str, Any]:
        """取消指定任务。

        委托给: TaskDispatcher.cancel_task()
        """
        return self.dispatcher.cancel_task(cid)

    # ========== 委托方法 - Plan文件管理 ==========

    def delete_plan(self, plan_name: str, *, dry_run: bool = False, backup: bool = True, force: bool = False) -> Dict[str, Any]:
        """删除方案。

        委托给: PlanFileManager.delete_plan()
        """
        return self.plan_mgr.delete_plan(plan_name, dry_run=dry_run, backup=backup, force=force)

    def get_all_plans(self) -> List[str]:
        """获取所有已加载 Plan 的名称列表。

        委托给: PlanFileManager.get_all_plans()
        """
        return self.plan_mgr.get_all_plans()

    def get_plan_files(self, plan_name: str) -> Dict[str, Any]:
        """获取指定 Plan 的文件目录树结构。

        委托给: PlanFileManager.get_plan_files()
        """
        return self.plan_mgr.get_plan_files(plan_name)

    def get_tasks_for_plan(self, plan_name: str) -> List[str]:
        """获取指定 Plan 下所有任务的名称列表。

        委托给: PlanFileManager.get_tasks_for_plan()
        """
        return self.plan_mgr.get_tasks_for_plan(plan_name)

    async def get_file_content(self, plan_name: str, relative_path: str) -> str:
        """异步、安全地读取指定 Plan 内的文件内容。

        委托给: PlanFileManager.get_file_content()
        """
        return await self.plan_mgr.get_file_content(plan_name, relative_path)

    async def get_file_content_bytes(self, plan_name: str, relative_path: str) -> bytes:
        """异步、安全地读取指定 Plan 内的文件内容（二进制）。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.get_file_content_bytes(relative_path)

    async def save_file_content(self, plan_name: str, relative_path: str, content: Any):
        """异步、安全地向指定 Plan 内的文件写入内容。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        await orchestrator.save_file_content(relative_path, content)
        logger.info(f"文件已通过Orchestrator异步保存: {relative_path}")

    async def create_directory(self, plan_name: str, relative_path: str):
        """异步、安全地在指定 Plan 内创建目录。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.create_directory(relative_path)

    async def create_file(self, plan_name: str, relative_path: str, content: str = ""):
        """异步、安全地在指定 Plan 内创建文件。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.create_file(relative_path, content)

    async def rename_path(self, plan_name: str, old_relative_path: str, new_relative_path: str):
        """异步、安全地在指定 Plan 内重命名路径。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.rename_path(old_relative_path, new_relative_path)

    async def delete_path(self, plan_name: str, relative_path: str):
        """异步、安全地删除指定 Plan 内的路径。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.delete_path(relative_path)

    # ========== 委托方法 - UI交互 ==========

    def set_ui_update_queue(self, q: queue.Queue):
        """设置用于向 UI 发送更新的队列。"""
        self.ui_update_queue = q
        self.ui_bridge.set_ui_update_queue(q)

    def _push_ui_update(self, msg_type: str, data: Any):
        """(私有) 向 UI 更新队列中推送一条消息。"""
        if self.ui_update_queue:
            try:
                self.ui_update_queue.put_nowait({'type': msg_type, 'data': data})
            except queue.Full:
                # 队列满时丢弃，避免抛到事件循环
                logger.warning(f"UI更新队列已满，丢弃消息: {msg_type}")
            except Exception as e:
                logger.warning(f"推送UI更新失败: {e}")

    def trigger_full_ui_update(self):
        """手动触发一次向 UI 的全量状态更新。"""
        logger.debug("Scheduler: Triggering a full UI status update for new clients.")
        payload = {
            'schedule': self.state_mgr.get_schedule_status(),
            'services': self.state_mgr.get_all_services_status(),
            'interrupts': self.state_mgr.get_all_interrupts_status(),
            'workspace': {
                'plans': self.plan_mgr.get_all_plans(),
                'actions': self.actions.get_all_action_definitions()
            }
        }
        self._push_ui_update('full_status_update', payload)

    # ========== 核心属性访问器 ==========

    @property
    def plans(self) -> Dict[str, 'Orchestrator']:
        """获取所有已加载 Plan 的 `Orchestrator` 实例字典。"""
        return self.plan_manager.plans

    @property
    def actions(self):
        """获取对 Action 注册表的只读访问。"""
        from packages.aura_core.api import ACTION_REGISTRY
        return ACTION_REGISTRY

    # ========== 内部异步方法 ==========

    async def _async_reload_subscriptions(self):
        """(私有) 异步地重新加载所有事件总线的订阅。"""
        # 只在首次注册核心订阅，避免重复叠加回调
        if not self._core_subscriptions_ready:
            await self.event_bus.subscribe(
                event_pattern='*',
                callback=self._mirror_event_to_ui_queue,
                channel='*',
                persistent=True
            )
            await self.event_bus.subscribe(
                event_pattern='task.*',
                callback=self._obs_ingest_event,
                channel='*',
                persistent=True
            )
            await self.event_bus.subscribe(
                event_pattern='node.*',
                callback=self._obs_ingest_event,
                channel='*',
                persistent=True
            )
            await self.event_bus.subscribe(
                event_pattern='queue.*',
                callback=self._obs_ingest_event,
                channel='*',
                persistent=True
            )
            self._core_subscriptions_ready = True

        # 计划/触发器订阅需要在 reload 时刷新
        await self.dispatcher.subscribe_event_triggers()

    async def _consume_main_task_queue(self):
        """(private) Delegate main queue consumption to dispatch service."""
        await self.dispatch.consume_main_task_queue()

    async def _consume_interrupt_queue(self):
        """(private) Delegate interrupt consumption to dispatch service."""
        await self.dispatch.consume_interrupt_queue()

    async def _event_worker_loop(self, worker_id: int):
        """(private) Delegate event worker loop to dispatch service."""
        await self.dispatch.event_worker_loop(worker_id)

    async def _mirror_event_to_ui_queue(self, event: Event):
        """(private) Mirror events into the UI queue."""
        await self.observability.mirror_event_to_ui_queue(event)

    async def _obs_ingest_event(self, event: Event):
        """(private) Forward events to the observability service."""
        await self.observability.ingest_event(event)

    # ========== 服务和中断状态查询 ==========

    def get_all_task_definitions_with_meta(self) -> List[Dict[str, Any]]:
        """获取所有任务的详细定义，包括元数据。"""
        with self.fallback_lock:
            detailed_tasks = []
            for full_task_id, task_def in self.all_tasks_definitions.items():
                try:
                    if not isinstance(task_def, dict):
                        continue
                    plan_name, task_name_in_plan = full_task_id.split('/', 1)

                    # 将旧格式转换为新格式
                    # MyTestPlan/test/draw_one_star/draw_one_star -> tasks:test:draw_one_star
                    task_ref_new = self._convert_id_to_new_format(task_name_in_plan)

                    detailed_tasks.append({
                        'full_task_id': full_task_id,
                        'plan_name': plan_name,
                        'task_name_in_plan': task_name_in_plan,  # 保留旧格式兼容性
                        'task_ref': task_ref_new,  # 新格式
                        'meta': task_def.get('meta', {}),
                        'definition': task_def
                    })
                except ValueError:
                    logger.warning(f"无法从任务ID '{full_task_id}' 中解析方案名，已跳过。")
            return detailed_tasks

    def _convert_id_to_new_format(self, task_name_in_plan: str) -> str:
        """
        将旧格式的任务ID转换为新格式的任务引用。

        示例:
            test/draw_one_star/draw_one_star -> tasks:test:draw_one_star
            test/draw_one_star -> tasks:test:draw_one_star
        """
        parts = task_name_in_plan.split('/')

        if len(parts) >= 2:
            # 检查最后一部分是否与倒数第二部分相同（完整格式）
            if parts[-1] == parts[-2]:
                # 去掉重复的任务键名
                path_parts = parts[:-1]
            else:
                # 简化格式，使用所有部分
                path_parts = parts
        else:
            # 单级路径
            path_parts = parts

        # 构建新格式：tasks:path1:path2:...
        return 'tasks:' + ':'.join(path_parts)

    def get_all_services_status(self) -> List[Dict[str, Any]]:
        """获取所有已注册服务的当前状态列表。"""
        async def async_get_services():
            async with self.get_async_lock():
                service_defs = service_registry.get_all_service_definitions()
                return [s.__dict__ for s in service_defs]

        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_get_services(), self._loop)
            try:
                return future.result(timeout=2)
            except Exception as e:
                logger.error(f"异步获取所有服务状态失败: {e}")
                with self.fallback_lock:
                    service_defs = service_registry.get_all_service_definitions()
                    return [s.__dict__ for s in service_defs]
        else:
            with self.fallback_lock:
                service_defs = service_registry.get_all_service_definitions()
                return [s.__dict__ for s in service_defs]

    def get_all_interrupts_status(self) -> List[Dict[str, Any]]:
        """获取所有已定义中断规则的当前状态列表。"""
        async def async_get():
            async with self.get_async_lock():
                status_list = []
                for name, definition in self.interrupt_definitions.items():
                    status_item = definition.copy()
                    status_item['is_global_enabled'] = name in self.user_enabled_globals
                    status_list.append(status_item)
                return status_list

        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_get(), self._loop)
            try:
                return future.result(timeout=2)
            except Exception as e:
                logger.error(f"异步获取中断状态失败: {e}")
                with self.fallback_lock:
                    status_list = []
                    for name, definition in self.interrupt_definitions.items():
                        status_item = definition.copy()
                        status_item['is_global_enabled'] = name in self.user_enabled_globals
                        status_list.append(status_item)
                    return status_list
        else:
            with self.fallback_lock:
                status_list = []
                for name, definition in self.interrupt_definitions.items():
                    status_item = definition.copy()
                    status_item['is_global_enabled'] = name in self.user_enabled_globals
                    status_list.append(status_item)
                return status_list

    def get_all_services_for_api(self) -> List[Dict[str, Any]]:
        """获取一个对 API 安全的服务列表。"""
        with self.fallback_lock:
            original_services = service_registry.get_all_service_definitions()
        api_safe_services = []
        for service_def in original_services:
            class_info = {'module': None, 'name': None}
            if hasattr(service_def.service_class, '__module__') and hasattr(service_def.service_class, '__name__'):
                class_info['module'] = service_def.service_class.__module__
                class_info['name'] = service_def.service_class.__name__
            plugin_info = None
            if service_def.plugin:
                plugin_info = {'name': service_def.plugin.name, 'canonical_id': service_def.plugin.canonical_id,
                               'version': service_def.plugin.version, 'plugin_type': service_def.plugin.plugin_type}
            api_safe_services.append(
                {"alias": service_def.alias, "fqid": service_def.fqid, "status": service_def.status,
                 "public": service_def.public, "service_class_info": class_info, "plugin": plugin_info})
        return api_safe_services

    # ========== Observability 相关 ==========

    def get_queue_overview(self) -> Dict[str, Any]:
        """Return a snapshot of queue stats."""
        return self.observability.get_queue_overview()

    def list_queue(self, state: str, limit: int = 200) -> Dict[str, Any]:
        """List ready/delayed queue items."""
        return self.observability.list_queue(state, limit)

    def get_metrics_snapshot(self) -> Dict[str, Any]:
        """Return metrics snapshot."""
        return self.observability.get_metrics_snapshot()

    async def _persist_run_snapshot(self, cid: str, run: Dict[str, Any]):
        """Delegate persistence to observability."""
        await self.observability._persist_run_snapshot(cid, run)

    def list_persisted_runs(self, limit: int = 50, plan_name: Optional[str] = None,
                            task_name: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List persisted runs."""
        return self.observability.list_persisted_runs(limit=limit, plan_name=plan_name, task_name=task_name, status=status)

    def get_persisted_run(self, cid: str) -> Dict[str, Any]:
        """Get a single persisted run."""
        return self.observability.get_persisted_run(cid)

    def get_run_timeline(self, cid_or_trace: str) -> Dict[str, Any]:
        """Return run timeline data."""
        return self.observability.get_run_timeline(cid_or_trace)

    def get_ui_event_queue(self) -> queue.Queue:
        """Return UI event queue."""
        return self.observability.get_ui_event_queue()

    def get_active_runs_snapshot(self) -> List[Dict[str, Any]]:
        """Return active runs snapshot."""
        return self.observability.get_active_runs_snapshot()

    def get_batch_task_status(self, cids: List[str]) -> List[Dict[str, Any]]:
        """Batch get task status."""
        return self.observability.get_batch_task_status(cids)

    # ========== 热重载相关 ==========

    async def reload_all(self):
        """执行一次完整的、破坏性的全量重载。"""
        from packages.aura_core.api import ACTION_REGISTRY, hook_manager

        logger.warning("======= 开始执行全量重载 =======")
        async with self.get_async_lock():
            if self.running_tasks:
                active_tasks = list(self.running_tasks.keys())
                msg = f"Cannot reload: {len(active_tasks)} tasks are running: {active_tasks}"
                logger.error(msg)
                return {"status": "error", "message": msg}

            try:
                logger.info("--> 正在清理注册表和缓存...")
                ACTION_REGISTRY.clear()
                service_registry.clear()
                hook_manager.clear()
                # 注意：新系统不需要clear_build_cache，因为不使用builder

                logger.info("--> 正在重新加载所有 Plans...")
                self.reload_plans()

                logger.info("======= 全量重载成功 =======")
                return {"status": "success", "message": "Full reload completed successfully."}
            except Exception as e:
                logger.critical(f"全量重载期间发生严重错误: {e}", exc_info=True)
                return {"status": "error", "message": f"A critical error occurred during reload: {e}"}

    def enable_hot_reload(self):
        """Enable file-system watch to hot reload plan/task files."""
        return self.hot_reload.enable()

    def disable_hot_reload(self):
        """Disable file-system watch for hot reload."""
        return self.hot_reload.disable()

    def is_hot_reload_enabled(self) -> bool:
        """Return True if the hot reload watcher is running."""
        return self.hot_reload.is_enabled()

    async def reload_task_file(self, file_path: Path):
        """热重载单个任务文件。"""
        async with self.get_async_lock():
            try:
                plan_name = file_path.relative_to(self.base_path / 'plans').parts[0]
                orchestrator = self.plan_manager.get_plan(plan_name)
                if orchestrator:
                    orchestrator.task_loader.reload_task_file(file_path)
                    self.plan_registry.load_all_tasks_definitions()
                    logger.info(f"任务文件 '{file_path.name}' 在方案 '{plan_name}' 中已成功热重载。")
                else:
                    logger.error(f"热重载失败：找不到与文件 '{file_path.name}' 关联的方案 '{plan_name}'。")
            except Exception as e:
                logger.error(f"热重载任务文件 '{file_path.name}' 时出错: {e}", exc_info=True)

    async def reload_plugin_from_py_file(self, file_path: Path):
        """根据变动的 Python 文件热重载其所属的整个插件。"""
        from packages.aura_core.api import ACTION_REGISTRY

        async with self.get_async_lock():
            try:
                # 尝试解析出所属的 plan 目录名
                try:
                    plan_dir_name = file_path.relative_to(self.base_path / 'plans').parts[0]
                except ValueError:
                    logger.error(f"热重载失败：文件 '{file_path}' 不在 plans 目录下。")
                    return

                plan_dir = (self.base_path / 'plans' / plan_dir_name).resolve()

                # 从 PackageManager 中查找对应的包定义
                manifest = next(
                    (m for m in self.plan_manager.package_manager.loaded_packages.values()
                     if m.path.resolve() == plan_dir),
                    None
                )

                if not manifest:
                    logger.error(f"热重载失败：找不到与目录 '{plan_dir}' 关联的包定义。")
                    return

                package_id = manifest.package.canonical_id

                if any(task_id.startswith(f"{package_id}/") for task_id in self.running_tasks):
                    logger.warning(f"跳过热重载：包 '{package_id}' 有任务正在运行。")
                    return

                logger.info(f"开始热重载包: '{package_id}'...")

                # 注意：新系统不再有dependency_manager，依赖在加载时已验证
                # 热重载时暂时跳过依赖检查，因为依赖应该已经在初始加载时验证过

                ACTION_REGISTRY.remove_actions_by_plugin(package_id)
                service_registry.remove_services_by_prefix(f"{package_id}/")

                module_prefix = ".".join(manifest.path.relative_to(self.base_path).parts)
                modules_to_remove = [name for name in sys.modules if name.startswith(module_prefix)]
                if modules_to_remove:
                    logger.debug(
                        f"--> 从 sys.modules 中移除 {len(modules_to_remove)} 个模块 (前缀: {module_prefix})..."
                    )
                    for mod_name in modules_to_remove:
                        del sys.modules[mod_name]

                # 注意：新系统不需要build_package_from_source
                # manifest.yaml在包开发时已经手动创建，不需要从源码构建

                self.plan_registry.load_all()
                logger.info(f"包 '{package_id}' 已成功热重载。")

            except Exception as e:
                logger.error(f"热重载插件时出错: {e}", exc_info=True)

    # ========== 队列管理 ==========

    async def queue_insert_at(self, index: int, plan_name: str, task_name: str,
                              params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Insert a task at a specific position in the queue."""
        return await self.dispatch.queue_insert_at(index, plan_name, task_name, params)

    async def queue_remove_task(self, cid: str) -> Dict[str, Any]:
        """Remove a task from the queue."""
        return await self.dispatch.queue_remove(cid)

    async def queue_move_to_front(self, cid: str) -> Dict[str, Any]:
        """Move a task to the front of the queue."""
        return await self.dispatch.queue_move_to_front(cid)

    async def queue_move_to_position(self, cid: str, new_index: int) -> Dict[str, Any]:
        """Move a task to a specific position in the queue."""
        return await self.dispatch.queue_move_to_position(cid, new_index)

    async def queue_list_all(self) -> List[Dict[str, Any]]:
        """List all queued tasks."""
        return await self.dispatch.queue_list_all()

    async def queue_clear(self) -> Dict[str, Any]:
        """Clear the queue."""
        return await self.dispatch.queue_clear()

    async def queue_reorder(self, cid_order: List[str]) -> Dict[str, Any]:
        """Reorder the queue."""
        return await self.dispatch.queue_reorder(cid_order)

    def update_task_priority(self, cid: str, new_priority: int) -> Dict[str, Any]:
        """调整指定任务的优先级。

        注意：此功能需要任务仍在队列中（未开始执行）。

        Args:
            cid: 任务的唯一追踪ID
            new_priority: 新的优先级值（数字越小优先级越高）

        Returns:
            包含操作结果的字典
        """
        # 由于当前的 TaskQueue 实现基于 asyncio.PriorityQueue，
        # 无法直接修改已入队任务的优先级。
        # 这需要重新实现队列或在任务未入队时设置优先级。

        logger.warning(f"Priority update for task '{cid}' is not fully implemented yet.")
        return {
            "status": "error",
            "message": "Priority update is not supported for tasks already in the queue. "
                       "This feature requires queue implementation upgrade."
        }

    async def _enqueue_schedule_item(self, item: Dict[str, Any], *, source: str,
                                     triggering_event: Optional[Event] = None) -> bool:
        """(private) Delegate schedule enqueue to dispatch service."""
        return await self.dispatch.enqueue_schedule_item(item, source=source, triggering_event=triggering_event)

    # ========== Tasklet Identifier Methods ==========

    def _base36_encode(self, num: int) -> str:
        """将整数编码为 base36 字符串。"""
        if num == 0:
            return "0"
        chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        out = []
        n = num
        while n > 0:
            n, r = divmod(n, 36)
            out.append(chars[r])
        return "".join(reversed(out))

    def _short_cid_suffix(self, cid: Optional[str]) -> str:
        """从 CID 生成短后缀（4位）。"""
        if not cid:
            return "0000"
        try:
            return self._base36_encode(int(cid))[-4:].rjust(4, "0")
        except Exception:
            return (cid[-4:] if len(cid) >= 4 else cid.rjust(4, "0"))

    def _make_trace_id(self, plan_name: str, task_name: str, cid: str,
                       when: Optional[datetime] = None) -> str:
        """生成任务追踪 ID。"""
        ts = when or datetime.now()
        time_part = ts.strftime("%y%m%d-%H%M%S")
        suffix = self._short_cid_suffix(cid)
        return f"{plan_name}/{task_name}@{time_part}-{suffix}"

    def _make_trace_label(self, plan_name: Optional[str], task_name: Optional[str]) -> str:
        """生成任务追踪标签（使用任务的 title 或全限定名）。"""
        full_task_id = f"{plan_name}/{task_name}" if plan_name and task_name else (plan_name or task_name or "")
        task_def = self.all_tasks_definitions.get(full_task_id, {}) if full_task_id else {}
        title = task_def.get("meta", {}).get("title") if isinstance(task_def, dict) else None
        return title or full_task_id

    def _build_resource_tags(self, plan_name: str, task_name: str) -> List[str]:
        """从任务定义构建资源标签列表。

        Args:
            plan_name: Plan 名称
            task_name: 任务名称

        Returns:
            资源标签列表
        """
        tags = []

        # 获取任务定义
        full_task_id = f"{plan_name}/{task_name}"
        task_data = self.all_tasks_definitions.get(full_task_id)

        if not task_data:
            # 无法获取任务定义，默认使用 exclusive 模式
            logger.debug(f"任务 {full_task_id} 未找到定义，默认使用 exclusive 模式")
            tags.append('__global_mutex__:1')
            return tags

        # 提取规范化的并发配置
        meta = task_data.get('meta', {})
        concurrency = meta.get('__normalized_concurrency__', {})

        mode = concurrency.get('mode', 'exclusive')
        resources = concurrency.get('resources', [])
        mutex_group = concurrency.get('mutex_group')
        max_instances = concurrency.get('max_instances')

        # 根据模式构建资源标签
        if mode == 'exclusive':
            # 独占模式：全局互斥
            tags.append('__global_mutex__:1')
        elif mode == 'concurrent':
            # 并发模式：不添加资源标签，只受全局 max_concurrent_tasks 限制
            pass
        elif mode == 'shared':
            # 共享资源模式：添加声明的资源
            tags.extend(resources)

            # 添加互斥组
            if mutex_group:
                tags.append(f'__mutex_group__:{mutex_group}:1')

        # 添加实例数限制
        if max_instances:
            tags.append(f'__max_instances__:{full_task_id}:{max_instances}')

        logger.debug(f"任务 {full_task_id} 并发模式: {mode}, 资源标签: {tags}")
        return tags

    def _ensure_tasklet_identifiers(self, tasklet: Tasklet,
                                    plan_name: Optional[str] = None,
                                    task_name: Optional[str] = None,
                                    source: Optional[str] = None) -> Tasklet:
        """确保 Tasklet 有完整的标识符（CID、trace_id 等）。"""
        payload = tasklet.payload if isinstance(tasklet.payload, dict) else {}

        if not plan_name:
            plan_name = payload.get("plan_name")
        if not task_name:
            task_name = payload.get("task_name") or payload.get("task") or payload.get("handler_task")

        if (not plan_name or not task_name) and tasklet.task_name:
            if "/" in tasklet.task_name:
                parts = tasklet.task_name.split("/", 1)
                plan_name = plan_name or parts[0]
                task_name = task_name or parts[1]

        if not tasklet.cid:
            tasklet.cid = str(next(self.id_generator))

        if not tasklet.trace_id and plan_name and task_name:
            tasklet.trace_id = self._make_trace_id(plan_name, task_name, tasklet.cid)
        if not tasklet.trace_label and plan_name and task_name:
            tasklet.trace_label = self._make_trace_label(plan_name, task_name)

        # 构建资源标签（如果尚未设置）
        if not tasklet.resource_tags and plan_name and task_name:
            tasklet.resource_tags = self._build_resource_tags(plan_name, task_name)

        if source and not tasklet.source:
            tasklet.source = source
        if not tasklet.source and payload.get("source"):
            tasklet.source = payload.get("source")

        if tasklet.cid:
            payload.setdefault("cid", tasklet.cid)
        if tasklet.trace_id:
            payload.setdefault("trace_id", tasklet.trace_id)
        if tasklet.trace_label:
            payload.setdefault("trace_label", tasklet.trace_label)
        if tasklet.source:
            payload.setdefault("source", tasklet.source)
        if plan_name:
            payload.setdefault("plan_name", plan_name)
        if task_name:
            payload.setdefault("task_name", task_name)

        tasklet.payload = payload
        return tasklet

    async def _async_update_run_status(self, item_id: str, status_update: Dict[str, Any]):
        """(私有) 异步地更新一个计划任务的运行状态。"""
        async with self.get_async_lock():
            if item_id:
                self.run_statuses.setdefault(item_id, {}).update(status_update)
                if self.ui_update_queue:
                    try:
                        self.ui_update_queue.put_nowait(
                            {'type': 'run_status_single_update', 'data': {'id': item_id, **self.run_statuses[item_id]}}
                        )
                    except queue.Full:
                        logger.warning("UI更新队列已满，丢弃消息: run_status_single_update")

    # ========== Input Validation Methods ==========

    def _infer_enum_type(self, enum_vals: Any) -> Optional[str]:
        """推断枚举值的类型。"""
        if not isinstance(enum_vals, list) or not enum_vals:
            return None
        kinds = set()
        for val in enum_vals:
            if isinstance(val, bool):
                kinds.add("boolean")
            elif isinstance(val, (int, float)):
                kinds.add("number")
            elif isinstance(val, str):
                kinds.add("string")
            else:
                return None
        return kinds.pop() if len(kinds) == 1 else None

    def _normalize_input_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """规范化 meta.inputs 字段定义，支持 list<type>/dict/enum/count 等写法。"""
        if not isinstance(schema, dict):
            return {"type": "string"}
        normalized = dict(schema)

        # 1. 统一 enum 和 options
        enum_vals = normalized.get("enum")
        if enum_vals is None and "options" in normalized:
            enum_vals = normalized.get("options")
        if enum_vals is not None:
            normalized["enum"] = enum_vals or []

        # 2. 处理 count 语法糖（新增）
        if "count" in normalized:
            count = normalized["count"]

            if isinstance(count, int):
                # count: 3 → min: 3, max: 3
                normalized["min"] = count
                normalized["max"] = count
            elif isinstance(count, str):
                # count: "<=5" → max: 5
                max_match = re.match(r'^<=(\d+)$', count)
                if max_match:
                    normalized["max"] = int(max_match.group(1))

                # count: ">=2" → min: 2
                min_match = re.match(r'^>=(\d+)$', count)
                if min_match:
                    normalized["min"] = int(min_match.group(1))

                # count: "1-3" → min: 1, max: 3
                range_match = re.match(r'^(\d+)-(\d+)$', count)
                if range_match:
                    normalized["min"] = int(range_match.group(1))
                    normalized["max"] = int(range_match.group(2))
            elif isinstance(count, list) and len(count) == 2:
                # count: [1, 3] → min: 1, max: 3
                normalized["min"] = count[0]
                normalized["max"] = count[1]

        # 3. 保留 ui 字段（前端使用，不验证）
        if "ui" in schema:
            normalized["ui"] = schema["ui"]

        # 4. 类型规范化
        type_raw = normalized.get("type")
        if type_raw is None or type_raw == "":
            type_raw = self._infer_enum_type(normalized.get("enum")) or "string"
        else:
            type_raw = str(type_raw).lower()
        if type_raw == "enum":
            type_raw = self._infer_enum_type(normalized.get("enum")) or "string"

        list_match = re.match(r"^list<(.+)>$", type_raw)
        if list_match:
            normalized["type"] = "list"
            item_schema = normalized.get("item") or normalized.get("items") or {"type": list_match.group(1)}
            normalized["item"] = self._normalize_input_schema(item_schema)
        else:
            if type_raw in {"array"}:
                type_raw = "list"
            elif type_raw in {"object"}:
                type_raw = "dict"
            allowed = {"string", "number", "boolean", "list", "dict"}
            normalized["type"] = type_raw if type_raw in allowed else "string"
            if normalized["type"] == "list":
                item_schema = normalized.get("item") or normalized.get("items")
                if item_schema is not None:
                    normalized["item"] = self._normalize_input_schema(item_schema)
            if normalized["type"] == "dict":
                props = {}
                for k, v in (normalized.get("properties") or {}).items():
                    if isinstance(v, dict):
                        props[k] = self._normalize_input_schema(v)
                normalized["properties"] = props
        return normalized

    def _build_default_from_schema(self, schema: Dict[str, Any]):
        """递归构造默认值（若有），用于填充缺失字段。"""
        schema_n = self._normalize_input_schema(schema or {})
        if "default" in schema_n:
            try:
                return json.loads(json.dumps(schema_n.get("default")))
            except Exception:
                return schema_n.get("default")
        enum_vals = schema_n.get("enum") or []
        if enum_vals:
            try:
                return json.loads(json.dumps(enum_vals[0]))
            except Exception:
                return enum_vals[0]
        t = schema_n.get("type")
        if t == "list":
            if isinstance(schema_n.get("default"), list):
                try:
                    return json.loads(json.dumps(schema_n.get("default")))
                except Exception:
                    return list(schema_n.get("default"))
            return []
        if t == "dict":
            if isinstance(schema_n.get("default"), dict):
                try:
                    return json.loads(json.dumps(schema_n.get("default")))
                except Exception:
                    return dict(schema_n.get("default"))
            result = {}
            for k, v in (schema_n.get("properties") or {}).items():
                child_default = self._build_default_from_schema(v)
                if child_default is not None:
                    result[k] = child_default
            return result
        if t == "boolean":
            return False
        if t == "number":
            return 0
        return ""

    def _validate_input_value(self, schema: Dict[str, Any], value: Any, path: str) -> Tuple[bool, Any, Optional[str]]:
        """递归校验单个字段值，返回 (ok, normalized_value, error_message)。"""
        s = self._normalize_input_schema(schema or {})
        required = bool(s.get("required"))
        has_default = "default" in s
        if value is _MISSING or value is None:
            if value is None and not required and not has_default:
                return True, None, None
            if has_default:
                return True, self._build_default_from_schema(s), None
            if required:
                return False, None, f"Missing required input: {path}"
            return True, None, None

        t = s.get("type", "string")
        if t == "string":
            val = str(value)
        elif t == "number":
            try:
                if isinstance(value, bool):
                    val = 1 if value else 0
                elif isinstance(value, (int, float)):
                    val = value
                else:
                    val = float(value)
            except Exception:
                return False, None, f"Input '{path}' must be a number."
            if "min" in s and val < s["min"]:
                return False, None, f"Input '{path}' must be >= {s['min']}."
            if "max" in s and val > s["max"]:
                return False, None, f"Input '{path}' must be <= {s['max']}."
        elif t == "boolean":
            if isinstance(value, bool):
                val = value
            elif isinstance(value, str):
                low = value.lower()
                if low in {"true", "1", "yes", "y"}:
                    val = True
                elif low in {"false", "0", "no", "n"}:
                    val = False
                else:
                    return False, None, f"Input '{path}' must be a boolean."
            else:
                val = bool(value)
        elif t == "list":
            if not isinstance(value, list):
                return False, None, f"Input '{path}' must be a list."
            # 使用统一的 min/max 字段（优先使用新的 min/max）
            min_items = s.get("min")
            if min_items is None:
                min_items = s.get("min_items") if s.get("min_items") is not None else s.get("minItems")
            max_items = s.get("max")
            if max_items is None:
                max_items = s.get("max_items") if s.get("max_items") is not None else s.get("maxItems")

            count = len(value)
            if min_items is not None and count < min_items:
                return False, None, f"Input '{path}' must contain at least {min_items} items (got {count})."
            if max_items is not None and count > max_items:
                return False, None, f"Input '{path}' must contain no more than {max_items} items (got {count})."

            item_schema = s.get("item") or s.get("items") or {}
            validated_list = []
            for idx, item in enumerate(value):
                ok, v, err = self._validate_input_value(item_schema, item, f"{path}[{idx}]")
                if not ok:
                    return False, None, err
                validated_list.append(v)
            val = validated_list
        elif t == "dict":
            if not isinstance(value, dict):
                return False, None, f"Input '{path}' must be an object."
            properties = s.get("properties") or {}
            extra = set(value.keys()) - set(properties.keys())
            if extra:
                return False, None, f"Input '{path}' has unexpected fields: {', '.join(sorted(extra))}."
            validated = {}
            for key, subschema in properties.items():
                ok, v, err = self._validate_input_value(subschema, value.get(key, _MISSING), f"{path}.{key}")
                if not ok:
                    return False, None, err
                if v is not None or "default" in subschema or subschema.get("required"):
                    validated[key] = v
            val = validated
        else:
            val = value
        allowed = s.get("enum")
        if allowed is not None:
            allowed = allowed or []
            if val not in allowed:
                return False, None, f"Input '{path}' must be one of {allowed}."
        return True, val, None

    def _validate_inputs_against_meta(self, inputs_meta: List[Dict[str, Any]], provided_inputs: Dict[str, Any]) -> Tuple[bool, Union[str, Dict[str, Any]]]:
        """基于 meta.inputs 递归校验/填充用户输入。"""
        if not isinstance(inputs_meta, list):
            return False, "Task meta.inputs must be a list."
        provided_inputs = provided_inputs or {}
        if not isinstance(provided_inputs, dict):
            return False, "Inputs must be an object/dict."
        expected_names = [item.get("name") for item in inputs_meta if isinstance(item, dict) and item.get("name")]
        extra = set(provided_inputs.keys()) - set(expected_names)
        if extra:
            return False, f"Unexpected inputs provided: {', '.join(extra)}"
        full_params = {}
        for item in inputs_meta:
            if not isinstance(item, dict) or "name" not in item:
                continue
            name = item["name"]
            ok, val, err = self._validate_input_value(item, provided_inputs.get(name, _MISSING), name)
            if not ok:
                return False, err
            if val is not None or "default" in item or item.get("required"):
                full_params[name] = val
        return True, full_params

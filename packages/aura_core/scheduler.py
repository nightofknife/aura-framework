# -*- coding: utf-8 -*-
"""Aura 框架的核心调度器。

此模块定义了 `Scheduler` 类，它是整个 Aura 框架的“大脑”和主入口点。
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
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
import json
import re
from asyncio import TaskGroup
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Any, List, Optional, Callable, Tuple, Union
from watchdog.observers import Observer
import yaml
import sys

from packages.aura_core.event_bus import EventBus, Event
from packages.aura_core.dependency_manager import DependencyManager
from packages.aura_core.state_store_service import StateStoreService
from packages.aura_core.task_queue import TaskQueue, Tasklet
from packages.aura_core.logger import logger
from plans.aura_base.services.config_service import ConfigService
from packages.aura_core.builder import build_package_from_source, clear_build_cache
from packages.aura_core.api import ACTION_REGISTRY, service_registry, hook_manager
from .execution_manager import ExecutionManager
from .interrupt_service import InterruptService
from .plan_manager import PlanManager
from .scheduling_service import SchedulingService
from packages.aura_core.id_generator import SnowflakeGenerator
from packages.aura_core.config_loader import get_config_value
from packages.aura_core.observability_service import ObservabilityService
from packages.aura_core.plan_registry import PlanRegistry
from packages.aura_core.dispatch_service import DispatchService
from packages.aura_core.execution_service import ExecutionService
from packages.aura_core.hot_reload_policy import HotReloadPolicy

if TYPE_CHECKING:
    from packages.aura_core.orchestrator import Orchestrator

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
        self._hot_reload_observer: Optional[Observer] = None
        self.num_event_workers = int(get_config_value("scheduler.num_event_workers", 1))
        self.startup_complete_event = threading.Event()
        self._pre_start_task_buffer: List[Tasklet] = []
        self.fallback_lock = threading.RLock()
        # ✅ 添加启动锁，保护启动/停止操作
        self._startup_lock = threading.Lock()
        # ✅ 新增：资源清理控制
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

        # ✅ 修复: 使用异步队列而非同步队列（将在 _initialize_async_components 中初始化）
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
        from packages.aura_core.file_watcher_service import FileWatcherService
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
            running_tasks_provider=self.get_running_tasks_count,  # ✅ 改进：使用线程安全的方法
        )
        # UI event queue is unbounded to avoid dropping updates under burst.
        self.ui_event_queue = self.observability.get_ui_event_queue()
        self.ui_update_queue: Optional[queue.Queue] = None
        # Core subscriptions should be registered only once.
        self._core_subscriptions_ready = False

        logger.setup(
            log_dir=str(get_config_value("logging.log_dir", "logs")),
            task_name=str(get_config_value("logging.task_name.default", "aura_session")),
            api_log_queue=self.api_log_queue
        )
        self._register_core_services()
        self.reload_plans()

    @staticmethod
    def _resolve_base_path() -> Path:
        env_base = os.getenv("AURA_BASE_PATH")
        if env_base:
            return Path(env_base).resolve()
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parents[2]

    def _initialize_async_components(self):
        """(私有) 在事件循环内部初始化所有需要事件循环的组件。"""
        logger.debug("Scheduler: 正在事件循环内初始化/重置异步组件...")
        self.is_running = asyncio.Event()
        if self.async_data_lock is None:
            self.async_data_lock = asyncio.Lock()

        # ✅ 初始化异步日志队列（无界）
        if self.api_log_queue is None:
            self.api_log_queue = asyncio.Queue(maxsize=0)

        self.task_queue = TaskQueue(maxsize=int(get_config_value("scheduler.queue.main_maxsize", 1000)))
        self.event_task_queue = TaskQueue(maxsize=int(get_config_value("scheduler.queue.event_maxsize", 2000)))
        self.interrupt_queue = asyncio.Queue(maxsize=int(get_config_value("scheduler.queue.interrupt_maxsize", 100)))

    def get_async_lock(self) -> asyncio.Lock:
        """获取一个线程安全的异步锁，用于保护共享状态。"""
        if self.async_data_lock is None:
            self.async_data_lock = asyncio.Lock()
            logger.debug("异步数据锁初始化。")
        return self.async_data_lock

    def _base36_encode(self, num: int) -> str:
        if num == 0:
            return "0"
        chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        out = []
        n = num
        while n > 0:
            n, r = divmod(n, 36)
            out.append(chars[r])
        return "".join(reversed(out))

    def _collect_requirement_names(self, req_file: Path, dep_mgr: DependencyManager) -> set[str]:
        """读取 requirements 文件中的包名集合（小写），忽略无效行。"""
        if not req_file.is_file():
            return set()
        try:
            requirements = dep_mgr._read_requirements(req_file)
        except Exception:
            return set()
        names: set[str] = set()
        for req in requirements:
            name = getattr(req, "name", None)
            if name:
                names.add(name.lower())
        return names

    def delete_plan(self, plan_name: str, *, dry_run: bool = False, backup: bool = True, force: bool = False) -> Dict[str, Any]:
        """删除方案：卸载独有依赖（相对其他方案与全局requirements），备份后删除目录并重载计划。"""
        plan_dir = (self.base_path / "plans" / plan_name).resolve()
        plans_root = (self.base_path / "plans").resolve()
        if not plan_dir.is_dir() or plans_root not in plan_dir.parents:
            return {"status": "error", "message": f"Plan '{plan_name}' not found."}

        dep_mgr = DependencyManager(self.base_path)
        req_name = dep_mgr._requirements_file_name()

        target_requirements = self._collect_requirement_names(plan_dir / req_name, dep_mgr)

        other_requirements: set[str] = set()
        # 其他方案
        for child in plans_root.iterdir():
            if child.is_dir() and child.name != plan_name:
                other_requirements |= self._collect_requirement_names(child / req_name, dep_mgr)

        # 全局 requirements.txt 作为基础框架依赖
        other_requirements |= self._collect_requirement_names(self.base_path / "requirements.txt", dep_mgr)

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
            backup_root = self.base_path / "backups"
            backup_root.mkdir(exist_ok=True)
            backup_path = backup_root / f"{plan_name}-{int(time.time())}"
            shutil.copytree(plan_dir, backup_path)

        if not dry_run:
            shutil.rmtree(plan_dir, ignore_errors=False)
            try:
                self.reload_plans()
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

    def _short_cid_suffix(self, cid: Optional[str]) -> str:
        if not cid:
            return "0000"
        try:
            return self._base36_encode(int(cid))[-4:].rjust(4, "0")
        except Exception:
            return (cid[-4:] if len(cid) >= 4 else cid.rjust(4, "0"))

    def _make_trace_id(self, plan_name: str, task_name: str, cid: str,
                       when: Optional[datetime] = None) -> str:
        ts = when or datetime.now()
        time_part = ts.strftime("%y%m%d-%H%M%S")
        suffix = self._short_cid_suffix(cid)
        return f"{plan_name}/{task_name}@{time_part}-{suffix}"

    def _make_trace_label(self, plan_name: Optional[str], task_name: Optional[str]) -> str:
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

    async def _async_get_schedule_status(self):
        """(私有) 异步地获取所有计划任务的状态列表。"""
        async with self.get_async_lock():
            schedule_items_copy = list(self.schedule_items)
            run_statuses_copy = dict(self.run_statuses)
        status_list = []
        for item in schedule_items_copy:
            full_status = item.copy()
            full_status.update(run_statuses_copy.get(item.get('id'), {}))
            status_list.append(full_status)
        return status_list

    async def _async_update_shared_state(self, update_func: Callable[[], None], read_only: bool = False):
        """(私有) 在异步锁的保护下执行一个对共享状态的更新操作。"""
        if read_only:
            async with self.get_async_lock():
                update_func()
        else:
            async with self.get_async_lock():
                update_func()

    def set_ui_update_queue(self, q: queue.Queue):
        """设置用于向 UI 发送更新的队列。"""
        self.ui_update_queue = q
        self.execution_manager.set_ui_update_queue(q)

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

    def _register_core_services(self):
        """(私有) 向服务注册表注册所有框架核心服务。"""
        from packages.aura_core.builder import set_project_base_path
        set_project_base_path(self.base_path)

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
        """重新加载所有 Plan 和相关配置。"""
        logger.info("======= Scheduler: 开始加载所有框架资源 =======")
        with self.fallback_lock:
            try:
                config_service = service_registry.get_service_instance('config')
                config_service.load_environment_configs(self.base_path)

                self.plan_registry.load_all()

                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(self._async_reload_subscriptions(), self._loop)
                self._push_ui_update('full_status_update', {
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

    # scheduler.py

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
        await self._subscribe_event_triggers()

    def start_scheduler(self):
        """启动调度器的主事件循环和所有后台服务。"""
        # ✅ 使用锁保护启动操作
        with self._startup_lock:
            if self._scheduler_thread and self._scheduler_thread.is_alive():
                logger.warning("调度器已经在运行中。")
                return

            # ✅ 重置shutdown标志，允许重新启动
            with self._shutdown_lock:
                self._shutdown_done = False

            self.startup_complete_event.clear()
            logger.info("用户请求启动调度器及所有后台服务...")
            self.execution_manager.startup()

            self._scheduler_thread = threading.Thread(
                target=self._run_scheduler_in_thread,
                name="SchedulerThread",
                daemon=True
            )
            self._scheduler_thread.start()

            # ✅ 修复：等待调度器完全启动
            logger.info("等待调度器事件循环完全启动...")
            startup_success = self.startup_complete_event.wait(timeout=10)

            if not startup_success:
                logger.error("调度器启动超时！")
                # ✅ 清理失败的启动
                self.stop_scheduler()
                return

            # ✅ 修复：使用锁保护状态检查和事件发布
            if not (self._loop and self._loop.is_running()):
                logger.error("调度器事件循环未正确启动")
                return

            logger.info("调度器已启动，正在发布 scheduler.started 事件...")
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.event_bus.publish(Event(
                        name="scheduler.started",
                        payload={"message": "Scheduler has started."}
                    )),
                    self._loop
                )
                # ✅ 增加超时时间
                future.result(timeout=5)
                logger.info("scheduler.started 事件发布成功。")
            except asyncio.TimeoutError:
                logger.error("发布 scheduler.started 事件超时")
            except Exception as e:
                logger.error(f"发布 scheduler.started 事件失败: {e}", exc_info=True)

        self._push_ui_update('master_status_update', {"is_running": True})

    def _cleanup_resources(self):
        """✅ 统一的资源清理方法，防止双重shutdown。"""
        with self._shutdown_lock:
            if self._shutdown_done:
                logger.debug("资源已清理，跳过重复调用。")
                return

            try:
                logger.info("正在清理调度器资源...")

                # 1. 清理运行中任务记录
                self.running_tasks.clear()
                self._running_task_meta.clear()

                # 2. 关闭执行管理器
                if self.execution_manager:
                    try:
                        self.execution_manager.shutdown()
                    except Exception as e:
                        logger.error(f"关闭执行管理器时发生异常: {e}", exc_info=True)

                # 3. 标记为已关闭
                self._shutdown_done = True
                logger.info("调度器资源清理完成。")

            except Exception as e:
                logger.error(f"资源清理时发生异常: {e}", exc_info=True)
            finally:
                # 4. 无论成功失败都设置事件
                self.startup_complete_event.set()

    def _run_scheduler_in_thread(self):
        """(私有) 在一个单独的线程中运行主事件循环。"""
        try:
            asyncio.run(self.run())
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("调度器事件循环被取消。")
        except Exception as e:
            logger.critical(f"调度器主事件循环崩溃: {e}", exc_info=True)
        finally:
            # ✅ 修复：使用统一的资源清理方法
            self._cleanup_resources()
            logger.info("调度器事件循环已终止。")

    def stop_scheduler(self):
        """优雅地停止调度器和所有后台服务。"""
        # ✅ 使用锁保护停止操作
        with self._startup_lock:
            if not self._scheduler_thread or not self._scheduler_thread.is_alive() or not self._loop:
                logger.warning("调度器已经处于停止状态。")
                return

            logger.info("用户请求停止调度器及所有后台服务...")

            # ✅ 修复：在停止之前发布事件
            if self._loop and self._loop.is_running():
                logger.info("正在发布 scheduler.stopped 事件...")
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self.event_bus.publish(Event(
                            name="scheduler.stopped",
                            payload={"message": "Scheduler is stopping."}
                        )),
                        self._loop
                    )
                    # ✅ 增加超时时间
                    future.result(timeout=5)
                    logger.info("scheduler.stopped 事件发布成功。")
                except asyncio.TimeoutError:
                    logger.error("发布 scheduler.stopped 事件超时")
                except Exception as e:
                    logger.error(f"发布 scheduler.stopped 事件失败: {e}", exc_info=True)

            if self.is_running:
                self._loop.call_soon_threadsafe(self.is_running.clear)
            if self._main_task:
                self._loop.call_soon_threadsafe(self._main_task.cancel)

            # ✅ 修复：等待线程结束，_cleanup_resources 会在线程中自动调用
            self._scheduler_thread.join(timeout=10)
            if self._scheduler_thread.is_alive():
                logger.error("调度器线程在超时后未能停止。")
            else:
                logger.info("调度器线程已成功终止。")

            self._scheduler_thread = None
            self._loop = None
            logger.info("调度器已安全停止。")

        self._push_ui_update('master_status_update', {"is_running": False})

    async def run(self):
        """调度器的主异步运行方法，包含了所有后台消费者的逻辑。"""
        self._initialize_async_components()
        self.is_running.set()
        self._loop = asyncio.get_running_loop()
        self._main_task = asyncio.current_task()

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
                self.file_watcher_service.start()
                logger.info("所有核心后台服务已启动，向主线程发出信号。")
                self.startup_complete_event.set()
        except asyncio.CancelledError:
            logger.info("调度器主任务被取消，正在优雅关闭...")
        finally:
            self.is_running.clear()
            self.file_watcher_service.stop()
            self._loop = None
            self._main_task = None
            logger.info("调度器主循环 (Commander) 已安全退出。")
            self.startup_complete_event.set()

    async def _consume_main_task_queue(self):
        """(private) Delegate main queue consumption to dispatch service."""
        await self.dispatch.consume_main_task_queue()

    async def _consume_interrupt_queue(self):
        """(private) Delegate interrupt consumption to dispatch service."""
        await self.dispatch.consume_interrupt_queue()

    async def _event_worker_loop(self, worker_id: int):
        """(private) Delegate event worker loop to dispatch service."""
        await self.dispatch.event_worker_loop(worker_id)

    def plans(self) -> Dict[str, 'Orchestrator']:
        """获取所有已加载 Plan 的 `Orchestrator` 实例字典。"""
        return self.plan_manager.plans

    def _load_plan_specific_data(self):
        """(private) Delegate plan-specific loading to PlanRegistry."""
        return self.plan_registry.load_plan_specific_data()

    def _load_all_tasks_definitions(self):
        """(private) Delegate task loading to PlanRegistry."""
        return self.plan_registry.load_all_tasks_definitions()

    async def _subscribe_event_triggers(self):
        """(私有) 订阅所有调度规则中的事件类触发器。"""
        logger.info("--- 订阅调度触发器 ---")

        async with self.get_async_lock():
            subscribed_count = 0
            schedule_items = list(self.schedule_items)

        for item in schedule_items:
            plan_name = item.get('plan_name')
            triggers = item.get('triggers') or []
            if not plan_name or not isinstance(triggers, list):
                continue
            for idx, trigger in enumerate(triggers):
                if not isinstance(trigger, dict):
                    continue
                trigger_type = trigger.get('type')
                if trigger_type == 'cron':
                    continue
                if trigger_type == 'variable':
                    key = trigger.get('key')
                    target_value = trigger.get('value')
                    operator = trigger.get('operator', 'eq')
                    if key:
                        async def var_handler(event, sched_item=item, k=key, v=target_value, op=operator):
                            if event.payload.get('key') == k:
                                current_val = event.payload.get('new_value')
                                match = False
                                if v is None:
                                    match = True
                                elif op == 'eq' and str(current_val) == str(v):
                                    match = True
                                elif op == 'neq' and str(current_val) != str(v):
                                    match = True
                                if match:
                                    await self._enqueue_schedule_item(
                                        sched_item,
                                        source="schedule_trigger",
                                        triggering_event=event
                                    )

                        await self.event_bus.subscribe('state.changed', var_handler)
                        subscribed_count += 1
                elif trigger_type == 'task':
                    target_task = trigger.get('task')
                    target_status = trigger.get('status', 'completed')
                    if target_task and target_status == 'completed':
                        target_full = f"{plan_name}/{target_task}"

                        async def task_handler(event, sched_item=item, target=target_full):
                            completed_task = f"{event.payload.get('plan_name')}/{event.payload.get('task_name')}"
                            if completed_task == target:
                                await self._enqueue_schedule_item(
                                    sched_item,
                                    source="schedule_trigger",
                                    triggering_event=event
                                )

                        await self.event_bus.subscribe('queue.completed', task_handler)
                        subscribed_count += 1
                elif trigger_type == 'file':
                    path = trigger.get('path')
                    pattern = trigger.get('pattern', '*')
                    events = trigger.get('events')
                    recursive = trigger.get('recursive', False)
                    if path:
                        watch_id = f"watch_{item.get('id', 'schedule')}_{idx}_{int(time.time())}"
                        self.file_watcher_service.add_watch(watch_id, path, events, recursive)

                        async def file_handler(event, sched_item=item, p=pattern, w_id=watch_id):
                            if event.payload.get('watch_id') == w_id:
                                import fnmatch
                                file_name = Path(event.payload.get('path')).name
                                if fnmatch.fnmatch(file_name, p):
                                    await self._enqueue_schedule_item(
                                        sched_item,
                                        source="schedule_trigger",
                                        triggering_event=event
                                    )

                        await self.event_bus.subscribe('file.changed', file_handler, channel='file_watcher')
                        subscribed_count += 1
                elif trigger_type == 'event':
                    event_pattern = trigger.get('event')
                    if not event_pattern:
                        continue
                    plugin_def = next(
                        (p for p in self.plan_manager.plugin_manager.plugin_registry.values()
                         if p.path.name == plan_name),
                        None
                    )
                    if not plugin_def:
                        continue
                    channel = plugin_def.canonical_id

                    from functools import partial

                    async def handler(event, sched_item):
                        await self._enqueue_schedule_item(
                            sched_item,
                            source="schedule_trigger",
                            triggering_event=event
                        )

                    callback = partial(handler, sched_item=item)
                    callback.__name__ = f"schedule_event_trigger_for_{item.get('id', 'schedule')}"
                    await self.event_bus.subscribe(event_pattern, callback, channel=channel)
                    subscribed_count += 1

        if subscribed_count:
            logger.info(f"--- 已订阅 {subscribed_count} 个调度触发器 ---")

    async def _enqueue_schedule_item(self, item: Dict[str, Any], *, source: str,
                                     triggering_event: Optional[Event] = None) -> bool:
        """(private) Delegate schedule enqueue to dispatch service."""
        return await self.dispatch.enqueue_schedule_item(item, source=source, triggering_event=triggering_event)

    def _infer_enum_type(self, enum_vals: Any) -> Optional[str]:
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

    def _load_schedule_file(self, plan_dir: Path, plan_name: str):
        """(private) Delegate schedule loading to PlanRegistry."""
        return self.plan_registry.load_schedule_file(plan_dir, plan_name)

    def _load_interrupt_file(self, plan_dir: Path, plan_name: str):
        """(private) Delegate interrupt loading to PlanRegistry."""
        return self.plan_registry.load_interrupt_file(plan_dir, plan_name)

    def update_run_status(self, item_id: str, status_update: Dict[str, Any]):
        """线程安全地更新一个计划任务的运行状态。"""
        if self._loop and self._loop.is_running():
            # ✅ 修复：使用非阻塞方式，避免潜在死锁
            try:
                asyncio.run_coroutine_threadsafe(
                    self._async_update_run_status(item_id, status_update),
                    self._loop
                )
                # 不等待结果，避免阻塞调用线程
            except Exception as e:
                logger.error(f"提交异步更新运行状态失败: {e}")
                # 降级到同步方式
                self._sync_update_run_status(item_id, status_update)
        else:
            self._sync_update_run_status(item_id, status_update)

    def _sync_update_run_status(self, item_id: str, status_update: Dict[str, Any]):
        """同步方式更新运行状态（fallback）"""
        with self.fallback_lock:
            if item_id:
                self.run_statuses.setdefault(item_id, {}).update(status_update)
                if self.ui_update_queue:
                    try:
                        self.ui_update_queue.put_nowait({
                            'type': 'run_status_single_update',
                            'data': {'id': item_id, **self.run_statuses[item_id]}
                        })
                    except queue.Full:
                        logger.warning("UI更新队列已满，丢弃消息: run_status_single_update")

    # ✅ 新增：线程安全地获取运行中任务数量
    def get_running_tasks_count(self) -> int:
        """线程安全地获取运行中任务数量。

        使用非阻塞方式从事件循环获取，避免死锁。
        """
        if self._loop and self._loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._async_get_running_tasks_count(),
                    self._loop
                )
                return future.result(timeout=1)
            except Exception as e:
                logger.warning(f"异步获取运行中任务数量失败: {e}")
                # Fallback: 使用fallback_lock
                with self.fallback_lock:
                    return len(self.running_tasks)
        else:
            with self.fallback_lock:
                return len(self.running_tasks)

    async def _async_get_running_tasks_count(self) -> int:
        """异步获取运行中任务数量。"""
        async with self.async_data_lock:
            return len(self.running_tasks)

    # ✅ 新增：线程安全地获取运行中任务的快照
    def get_running_tasks_snapshot(self) -> Dict[str, Any]:
        """获取运行中任务的快照（线程安全）。"""
        if self._loop and self._loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._async_get_running_tasks_snapshot(),
                    self._loop
                )
                return future.result(timeout=2)
            except Exception as e:
                logger.warning(f"异步获取运行中任务快照失败: {e}")
                with self.fallback_lock:
                    return self._fallback_running_tasks_snapshot()
        else:
            with self.fallback_lock:
                return self._fallback_running_tasks_snapshot()

    async def _async_get_running_tasks_snapshot(self) -> Dict[str, Any]:
        """异步获取运行中任务快照。"""
        from datetime import datetime
        async with self.async_data_lock:
            return {
                cid: {
                    'task_name': meta.get('task_name'),
                    'start_time': meta.get('start_time').isoformat() if meta.get('start_time') else None,
                    'duration_sec': (datetime.now() - meta.get('start_time')).total_seconds()
                    if meta.get('start_time') else 0
                }
                for cid, meta in self._running_task_meta.items()
            }

    def _fallback_running_tasks_snapshot(self) -> Dict[str, Any]:
        """Fallback方式获取运行中任务快照。"""
        from datetime import datetime
        return {
            cid: {
                'task_name': meta.get('task_name'),
                'start_time': meta.get('start_time').isoformat() if meta.get('start_time') else None,
                'duration_sec': (datetime.now() - meta.get('start_time')).total_seconds()
                if meta.get('start_time') else 0
            }
            for cid, meta in self._running_task_meta.items()
        }

    def run_manual_task(self, task_id: str):
        """Delegate manual schedule run to execution service."""
        return self.executor.run_manual_task(task_id)

    def run_ad_hoc_task(self, plan_name: str, task_name: str, params: Optional[Dict[str, Any]] = None, temp_id: Optional[str] = None):
        """Delegate ad-hoc task run to execution service."""
        return self.executor.run_ad_hoc_task(plan_name, task_name, params, temp_id)

    def get_master_status(self) -> dict:
        """获取调度器的宏观运行状态。"""
        is_running = self._scheduler_thread is not None and self._scheduler_thread.is_alive()
        return {"is_running": is_running}

    def get_schedule_status(self):
        """获取所有预定义计划任务的当前状态列表。"""
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._async_get_schedule_status(), self._loop)
            try:
                return future.result(timeout=2)
            except Exception as e:
                logger.error(f"异步获取调度状态失败: {e}")
                with self.fallback_lock:
                    schedule_items_copy = list(self.schedule_items)
                    run_statuses_copy = dict(self.run_statuses)
        else:
            with self.fallback_lock:
                schedule_items_copy = list(self.schedule_items)
                run_statuses_copy = dict(self.run_statuses)
        status_list = []
        for item in schedule_items_copy:
            full_status = item.copy()
            full_status.update(run_statuses_copy.get(item.get('id'), {}))
            status_list.append(full_status)
        return status_list

    @property
    def actions(self):
        """获取对 Action 注册表的只读访问。"""
        return ACTION_REGISTRY

    async def _mirror_event_to_ui_queue(self, event: Event):
        """(private) Mirror events into the UI queue."""
        await self.observability.mirror_event_to_ui_queue(event)

    async def _obs_ingest_event(self, event: Event):
        """(private) Forward events to the observability service."""
        await self.observability.ingest_event(event)

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

    def get_all_plans(self) -> List[str]:
        """获取所有已加载 Plan 的名称列表。"""
        async def async_get_plans():
            async with self.get_async_lock():
                return self.plan_manager.list_plans()

        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_get_plans(), self._loop)
            try:
                return future.result(timeout=1)
            except Exception as e:
                logger.error(f"异步获取所有计划失败: {e}")
                with self.fallback_lock:
                    return self.plan_manager.list_plans()
        else:
            with self.fallback_lock:
                return self.plan_manager.list_plans()

    def get_plan_files(self, plan_name: str) -> Dict[str, Any]:
        """获取指定 Plan 的文件目录树结构。"""
        logger.debug(f"请求获取 '{plan_name}' 的文件树...")
        plan_path = self.base_path / 'plans' / plan_name
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
        """获取指定 Plan 下所有任务的名称列表。"""
        async def async_get_tasks():
            async with self.get_async_lock():
                tasks = []
                prefix = f"{plan_name}/"
                for task_id in self.all_tasks_definitions.keys():
                    if task_id.startswith(prefix):
                        tasks.append(task_id[len(prefix):])
                return sorted(tasks)

        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_get_tasks(), self._loop)
            try:
                return future.result(timeout=1)
            except Exception as e:
                logger.error(f"异步获取计划任务失败: {e}")
                with self.fallback_lock:
                    tasks = []
                    prefix = f"{plan_name}/"
                    for task_id in self.all_tasks_definitions.keys():
                        if task_id.startswith(prefix):
                            tasks.append(task_id[len(prefix):])
                    return sorted(tasks)
        else:
            with self.fallback_lock:
                tasks = []
                prefix = f"{plan_name}/"
                for task_id in self.all_tasks_definitions.keys():
                    if task_id.startswith(prefix):
                        tasks.append(task_id[len(prefix):])
                return sorted(tasks)

    def get_all_task_definitions_with_meta(self) -> List[Dict[str, Any]]:
        """获取所有任务的详细定义，包括元数据。"""
        with self.fallback_lock:
            detailed_tasks = []
            for full_task_id, task_def in self.all_tasks_definitions.items():
                try:
                    if not isinstance(task_def, dict):
                        continue
                    plan_name, task_name_in_plan = full_task_id.split('/', 1)
                    detailed_tasks.append({
                        'full_task_id': full_task_id,
                        'plan_name': plan_name,
                        'task_name_in_plan': task_name_in_plan,
                        'meta': task_def.get('meta', {}),
                        'definition': task_def
                    })
                except ValueError:
                    logger.warning(f"无法从任务ID '{full_task_id}' 中解析方案名，已跳过。")
            return detailed_tasks

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

    async def get_file_content(self, plan_name: str, relative_path: str) -> str:
        """异步、安全地读取指定 Plan 内的文件内容。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.get_file_content(relative_path)

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

    def trigger_full_ui_update(self):
        """手动触发一次向 UI 的全量状态更新。"""
        logger.debug("Scheduler: Triggering a full UI status update for new clients.")
        payload = {
            'schedule': self.get_schedule_status(),
            'services': self.get_all_services_status(),
            'interrupts': self.get_all_interrupts_status(),
            'workspace': {
                'plans': self.get_all_plans(),
                'actions': self.actions.get_all_action_definitions()
            }
        }
        self._push_ui_update('full_status_update', payload)

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

    async def reload_all(self):
        """执行一次完整的、破坏性的全量重载。"""
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
                clear_build_cache()

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
                    self._load_all_tasks_definitions()
                    logger.info(f"任务文件 '{file_path.name}' 在方案 '{plan_name}' 中已成功热重载。")
                else:
                    logger.error(f"热重载失败：找不到与文件 '{file_path.name}' 关联的方案 '{plan_name}'。")
            except Exception as e:
                logger.error(f"热重载任务文件 '{file_path.name}' 时出错: {e}", exc_info=True)

    async def reload_plugin_from_py_file(self, file_path: Path):
        """根据变动的 Python 文件热重载其所属的整个插件。"""
        async with self.get_async_lock():
            try:
                # 尝试解析出所属的 plan 目录名
                try:
                    plan_dir_name = file_path.relative_to(self.base_path / 'plans').parts[0]
                except ValueError:
                    logger.error(f"热重载失败：文件 '{file_path}' 不在 plans 目录下。")
                    return

                plan_dir = (self.base_path / 'plans' / plan_dir_name).resolve()

                # 根据目录路径在 plugin_registry 中查找对应的插件定义
                plugin_def = next(
                    (p for p in self.plan_manager.plugin_manager.plugin_registry.values()
                     if p.path.resolve() == plan_dir),
                    None
                )

                if not plugin_def:
                    logger.error(f"热重载失败：找不到与目录 '{plan_dir}' 关联的插件定义。")
                    return

                plugin_id = plugin_def.canonical_id

                if any(task_id.startswith(f"{plugin_id}/") for task_id in self.running_tasks):
                    logger.warning(f"跳过热重载：插件 '{plugin_id}' 有任务正在运行。")
                    return

                logger.info(f"开始热重载插件: '{plugin_id}'...")

                if plugin_def.plugin_type == "plan":
                    result = self.plan_manager.plugin_manager.dependency_manager.ensure_plan_dependencies(plugin_def.path)
                    if not result.ok:
                        on_missing = str(get_config_value("dependencies.on_missing", "skip_plan")).lower()
                        if on_missing == "skip_plan":
                            logger.warning(
                                "跳过热重载：插件 '%s' 缺少依赖: %s",
                                plugin_id,
                                ", ".join(result.missing),
                            )
                            return
                        logger.warning(
                            "继续热重载：插件 '%s' 缺少依赖",
                            plugin_id,
                        )

                ACTION_REGISTRY.remove_actions_by_plugin(plugin_id)
                service_registry.remove_services_by_prefix(f"{plugin_id}/")

                module_prefix = ".".join(plugin_def.path.relative_to(self.base_path).parts)
                modules_to_remove = [name for name in sys.modules if name.startswith(module_prefix)]
                if modules_to_remove:
                    logger.debug(
                        f"--> 从 sys.modules 中移除 {len(modules_to_remove)} 个模块 (前缀: {module_prefix})..."
                    )
                    for mod_name in modules_to_remove:
                        del sys.modules[mod_name]

                clear_build_cache()
                build_package_from_source(plugin_def)

                self.plan_registry.load_all()
                logger.info(f"插件 '{plugin_id}' 已成功热重载。")

            except Exception as e:
                logger.error(f"热重载插件时出错: {e}", exc_info=True)

    def get_active_runs_snapshot(self) -> List[Dict[str, Any]]:
        """Return active runs snapshot."""
        return self.observability.get_active_runs_snapshot()

    def run_batch_ad_hoc_tasks(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Delegate batch ad-hoc runs to execution service."""
        return self.executor.run_batch_ad_hoc_tasks(tasks)

    def cancel_task(self, cid: str) -> Dict[str, Any]:
        """取消指定 cid 的任务。

        Args:
            cid: 任务的唯一追踪ID

        Returns:
            包含取消操作结果的字典
        """
        with self.fallback_lock:
            if cid not in self.running_tasks:
                return {"status": "error", "message": f"Task with cid '{cid}' is not running or not found."}

            task = self.running_tasks.get(cid)
            if task and not task.done():
                task.cancel()
                logger.info(f"Task with cid '{cid}' has been cancelled.")
                return {"status": "success", "message": f"Task '{cid}' cancellation initiated."}
            else:
                return {"status": "error", "message": f"Task '{cid}' is already finished or cannot be cancelled."}

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

    def get_batch_task_status(self, cids: List[str]) -> List[Dict[str, Any]]:
        """Batch get task status."""
        return self.observability.get_batch_task_status(cids)

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


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
- **热重载**: 实现 `HotReloadHandler` 来监控文件系统变动，并触发对
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
from typing import TYPE_CHECKING, Dict, Any, List, Optional, Callable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
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

if TYPE_CHECKING:
    from packages.aura_core.orchestrator import Orchestrator

_MISSING = object()

class HotReloadHandler(FileSystemEventHandler):
    """一个响应式的文件系统事件处理器，用于监控文件变动并触发相应的热重载。"""

    def __init__(self, scheduler: 'Scheduler'):
        """初始化热重载处理器。"""
        self.scheduler = scheduler
        self.loop = scheduler._loop

    def on_modified(self, event):
        """当文件被修改时调用此方法。"""
        if not self.loop or not self.loop.is_running():
            logger.warning("事件循环不可用，跳过热重载。")
            return

        if event.is_directory:
            return

        file_path = Path(event.src_path)
        if file_path.name.startswith('.') or '__pycache__' in file_path.parts:
            return

        if file_path.suffix == '.yaml' and 'tasks' in file_path.parts:
            logger.info(f"[Hot Reload] 检测到任务文件变动: {file_path.name}")
            asyncio.run_coroutine_threadsafe(
                self.scheduler.reload_task_file(file_path),
                self.loop
            )
        elif file_path.suffix == '.py':
            logger.info(f"[Hot Reload] 检测到Python代码变动: {file_path.name}")
            asyncio.run_coroutine_threadsafe(
                self.scheduler.reload_plugin_from_py_file(file_path),
                self.loop
            )

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

        # 改为无界队列，避免日志激增时阻塞/抛 queue.Full
        self.api_log_queue: queue.Queue = queue.Queue(maxsize=0)

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

        # --- 运行/调度状态 ---
        self.run_statuses: Dict[str, Dict[str, Any]] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self._running_task_meta: Dict[str, Dict[str, Any]] = {}
        self.schedule_items: List[Dict[str, Any]] = []
        self.interrupt_definitions: Dict[str, Dict[str, Any]] = {}
        self.user_enabled_globals: set[str] = set()
        self.all_tasks_definitions: Dict[str, Any] = {}
        # UI 事件队列改为无界，避免 queue.Full 导致状态事件丢失
        self.ui_event_queue = queue.Queue(maxsize=0)
        self.ui_update_queue: Optional[queue.Queue] = None
        # 确保核心事件订阅不会重复注册
        self._core_subscriptions_ready = False

        # --- 可观测性内存索引 ---
        self._obs_runs: Dict[str, Dict[str, Any]] = {}
        self._obs_ready: Dict[str, Dict[str, Any]] = {}
        self._obs_delayed: Dict[str, Dict[str, Any]] = {}
        self._obs_runs_by_trace: Dict[str, str] = {}
        runs_dir_cfg = get_config_value("observability.runs.dir", str(self.base_path / "logs" / "runs"))
        self.persist_runs = bool(get_config_value("observability.persist_runs", False))
        self.run_history_dir = Path(runs_dir_cfg).resolve()

        # --- 基础指标 ---
        self.metrics: Dict[str, Any] = {
            "tasks_started": 0,
            "tasks_finished": 0,
            "tasks_success": 0,
            "tasks_error": 0,
            "tasks_failed": 0,
            "tasks_timeout": 0,
            "tasks_cancelled": 0,
            "tasks_running": 0,
            "nodes_total": 0,
            "nodes_succeeded": 0,
            "nodes_failed": 0,
            "nodes_duration_ms_sum": 0.0,
            "nodes_duration_ms_avg": 0.0,
            "updated_at": time.time(),
        }


        # --- 初始化流程 ---
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

                self.plan_manager.initialize()
                self._load_plan_specific_data()

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
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            logger.warning("调度器已经在运行中。")
            return
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
            return

        # ✅ 修复：在事件循环启动后发布事件
        if self._loop and self._loop.is_running():
            logger.info("调度器已启动，正在发布 scheduler.started 事件...")
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.event_bus.publish(Event(
                        name="scheduler.started",
                        payload={"message": "Scheduler has started."}
                    )),
                    self._loop
                )
                # 等待事件发布完成
                future.result(timeout=2)
                logger.info("scheduler.started 事件发布成功。")
            except Exception as e:
                logger.error(f"发布 scheduler.started 事件失败: {e}")

        self._push_ui_update('master_status_update', {"is_running": True})

    def _run_scheduler_in_thread(self):
        """(私有) 在一个单独的线程中运行主事件循环。"""
        try:
            asyncio.run(self.run())
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("调度器事件循环被取消。")
        except Exception as e:
            logger.critical(f"调度器主事件循环崩溃: {e}", exc_info=True)
        finally:
            try:
                # 确保执行器池被释放，防止异常退出后资源泄漏
                self.execution_manager.shutdown()
            except Exception as e:
                logger.warning(f"关闭执行管理器时发生异常: {e}")
            # 清理运行中任务记录
            self.running_tasks.clear()
            self._running_task_meta.clear()
            logger.info("调度器事件循环已终止。")
            self.startup_complete_event.set()

    def stop_scheduler(self):
        """优雅地停止调度器和所有后台服务。"""
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
                future.result(timeout=2)
                logger.info("scheduler.stopped 事件发布成功。")
            except Exception as e:
                logger.error(f"发布 scheduler.stopped 事件失败: {e}")

        if self.is_running:
            self._loop.call_soon_threadsafe(self.is_running.clear)
        if self._main_task:
            self._loop.call_soon_threadsafe(self._main_task.cancel)

        self._scheduler_thread.join(timeout=10)
        if self._scheduler_thread.is_alive():
            logger.error("调度器线程在超时后未能停止。")

        self.execution_manager.shutdown()
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
        """(私有) 主任务队列的消费者循环。"""
        max_cc = int(getattr(self.execution_manager, "max_concurrent_tasks", 1) or 1)
        queue_full_sleep = float(get_config_value("scheduler.loop_sleep_sec.queue_full", 0.2))
        consumer_error_sleep = float(get_config_value("scheduler.loop_sleep_sec.consumer_error", 0.5))

        while True:
            try:
                current_running_count = len(self.running_tasks)

                # ✅ 详细日志
                if current_running_count > 0 or self.task_queue.qsize() > 0:
                    logger.info(
                        f"[Queue Consumer] 当前状态: "
                        f"running={current_running_count}/{max_cc}, "
                        f"queue_size={self.task_queue.qsize()}, "
                        f"keys={list(self.running_tasks.keys())}"
                    )

                if len(self.running_tasks) >= max_cc:
                    logger.warning(f"[Queue Consumer] 达到并发上限，等待中...")
                    await asyncio.sleep(queue_full_sleep)
                    continue

                tasklet = await self.task_queue.get()
                self._ensure_tasklet_identifiers(tasklet)
                dequeued_at = time.time()
                queued_at = getattr(tasklet, "enqueued_at", None) or dequeued_at
                queue_wait_ms = max(0.0, (dequeued_at - queued_at) * 1000)

                try:
                    payload = {}
                    tname = getattr(tasklet, "task_name", None) or getattr(tasklet, "name", None)
                    if tname and isinstance(tname, str):
                        if "/" in tname:
                            plan_name, task_name = tname.split("/", 1)
                        else:
                            plan_name, task_name = None, tname
                    else:
                        plan_name = getattr(tasklet, "plan_name", None)
                        task_name = getattr(tasklet, "task_name", None)

                    payload.update({
                        "cid": tasklet.cid,
                        "trace_id": tasklet.trace_id,
                        "trace_label": tasklet.trace_label,
                        "source": tasklet.source,
                        "plan_name": plan_name,
                        "task_name": task_name,
                        "start_time": dequeued_at,
                        "queue_wait_ms": queue_wait_ms,
                    })
                    await self.event_bus.publish(Event(name="queue.dequeued", payload=payload))
                except Exception:
                    pass

                submit_task = asyncio.create_task(self.execution_manager.submit(tasklet))

                key = tasklet.cid

                logger.info(f"[Queue Consumer] ✅ 任务入队: key={key}")
                self.running_tasks[key] = submit_task
                self._running_task_meta[key] = {
                    "plan_name": plan_name,
                    "task_name": task_name,
                    "source": tasklet.source,
                    "trace_id": tasklet.trace_id,
                    "trace_label": tasklet.trace_label,
                    "dequeued_at": dequeued_at,
                    "queued_at": queued_at,
                }

                def _cleanup(_fut: asyncio.Task):
                    try:
                        removed = self.running_tasks.pop(key, None)
                        if removed:
                            logger.debug(f"[_consume_main_task_queue] ???????????? running_tasks ?????????key={key}")
                        else:
                            logger.warning(f"[_consume_main_task_queue] ???????????????????????? key={key}")
                    finally:
                        try:
                            self.task_queue.task_done()
                        except Exception:
                            pass
                        try:
                            end_ts = time.time()
                            meta = self._running_task_meta.pop(key, {})
                            start_ts = meta.get("dequeued_at") or end_ts
                            q_at = meta.get("queued_at") or start_ts
                            exec_ms = max(0.0, (end_ts - start_ts) * 1000)
                            q_wait = max(0.0, (start_ts - q_at) * 1000)
                            evt_payload = {
                                "cid": key,
                                "trace_id": meta.get("trace_id"),
                                "trace_label": meta.get("trace_label"),
                                "plan_name": meta.get("plan_name"),
                                "task_name": meta.get("task_name"),
                                "source": meta.get("source"),
                                "dequeued_at": start_ts,
                                "completed_at": end_ts,
                                "queue_wait_ms": q_wait,
                                "exec_ms": exec_ms,
                            }
                            try:
                                asyncio.create_task(self.event_bus.publish(Event(name="queue.completed", payload=evt_payload)))
                            except Exception:
                                pass
                        except Exception:
                            logger.debug("queue.completed emit failed", exc_info=True)

                submit_task.add_done_callback(_cleanup)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error consuming main task queue")
                await asyncio.sleep(consumer_error_sleep)

    async def _consume_interrupt_queue(self):
        """(私有) 中断队列的消费者循环。"""
        while self.is_running.is_set():
            try:
                handler_rule = await asyncio.wait_for(self.interrupt_queue.get(), timeout=1.0)
                rule_name = handler_rule.get('name', 'unknown_interrupt')
                logger.info(f"指挥官: 开始处理中断 '{rule_name}'...")
                scope = handler_rule.get('scope') or 'plan'
                target_plan = handler_rule.get('plan_name')
                tasks_to_cancel = []
                async with self.get_async_lock():
                    for cid, task in self.running_tasks.items():
                        meta = self._running_task_meta.get(cid, {})
                        if meta.get('source') == 'interrupt':
                            continue
                        if scope != 'global' and target_plan and meta.get('plan_name') != target_plan:
                            continue
                        tasks_to_cancel.append(task)
                for task in tasks_to_cancel:
                    task.cancel()
                handler_task_id = f"{handler_rule['plan_name']}/{handler_rule['handler_task']}"
                handler_item = {
                    'plan_name': handler_rule['plan_name'],
                    'task_name': handler_rule['handler_task'],
                    'handler_task': handler_rule['handler_task']
                }
                tasklet = Tasklet(task_name=handler_task_id, payload=handler_item, is_ad_hoc=True, execution_mode='sync')
                self._ensure_tasklet_identifiers(tasklet, source="interrupt")
                await asyncio.create_task(self.execution_manager.submit(tasklet, is_interrupt_handler=True))
                self.interrupt_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info("中断队列消费者被取消。")
                break

    async def _event_worker_loop(self, worker_id: int):
        """(私有) 事件驱动任务队列的消费者循环。"""
        while self.is_running.is_set():
            try:
                tasklet = await asyncio.wait_for(self.event_task_queue.get(), timeout=1.0)
                self._ensure_tasklet_identifiers(tasklet)
                await self.execution_manager.submit(tasklet)
                self.event_task_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info(f"事件工作者 #{worker_id} 被取消。")
                break

    @property
    def plans(self) -> Dict[str, 'Orchestrator']:
        """获取所有已加载 Plan 的 `Orchestrator` 实例字典。"""
        return self.plan_manager.plans

    def _load_plan_specific_data(self):
        """(私有) 加载所有 Plan 特有的数据，如配置、调度项和中断规则。"""
        config_service = service_registry.get_service_instance('config')

        def load_core():
            logger.info("--- 加载方案包特定数据 ---")
            self.schedule_items.clear()
            self.interrupt_definitions.clear()
            self.user_enabled_globals.clear()
            self.all_tasks_definitions.clear()

            for plugin_def in self.plan_manager.plugin_manager.plugin_registry.values():
                if plugin_def.plugin_type != 'plan':
                    continue

                plan_name = plugin_def.path.name
                config_path = plugin_def.path / 'config.yaml'
                if config_path.is_file():
                    try:
                        with open(config_path, 'r', encoding='utf-8') as f:
                            config_data = yaml.safe_load(f) or {}
                        config_service.register_plan_config(plan_name, config_data)
                    except Exception as e:
                        logger.error(f"加载配置文件 '{config_path}' 失败: {e}")

                self._load_schedule_file(plugin_def.path, plan_name)
                self._load_interrupt_file(plugin_def.path, plan_name)

            self._load_all_tasks_definitions()

        if self._loop and self._loop.is_running():
            async def async_load():
                async with self.get_async_lock():
                    load_core()

            future = asyncio.run_coroutine_threadsafe(async_load(), self._loop)
            try:
                future.result(timeout=5)
            except Exception as e:
                logger.error(f"异步加载计划数据失败: {e}")
                with self.fallback_lock:
                    load_core()
        else:
            with self.fallback_lock:
                load_core()

    def _load_all_tasks_definitions(self):
        """(私有) 从所有 Plan 的 `tasks` 目录中加载任务定义。"""
        logger.info("--- 加载所有任务定义 ---")
        self.all_tasks_definitions.clear()
        plans_dir = self.base_path / 'plans'
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
                    with open(task_file_path, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)
                    if not isinstance(data, dict):
                        continue

                    def process_task_definitions(task_data, base_id):
                        for task_key, task_definition in task_data.items():
                            if isinstance(task_definition, dict) and 'meta' in task_definition:
                                task_definition.setdefault('execution_mode', 'sync')
                                full_task_id = f"{plan_name}/{base_id}/{task_key}".replace("//", "/")
                                self.all_tasks_definitions[full_task_id] = task_definition
                                if task_key == Path(base_id).name:
                                    alias_id = f"{plan_name}/{base_id}".replace("//", "/")
                                    self.all_tasks_definitions.setdefault(alias_id, task_definition)

                    if 'steps' in data:
                        task_name_from_file = task_file_path.relative_to(tasks_dir).with_suffix('').as_posix()
                        data.setdefault('execution_mode', 'sync')
                        full_task_id = f"{plan_name}/{task_name_from_file}"
                        self.all_tasks_definitions[full_task_id] = data
                    else:
                        relative_path_str = task_file_path.relative_to(tasks_dir).with_suffix('').as_posix()
                        process_task_definitions(data, relative_path_str)

                except Exception as e:
                    logger.error(f"加载任务文件 '{task_file_path}' 失败: {e}")
        logger.info(f"任务定义加载完毕，共找到 {len(self.all_tasks_definitions)} 个任务。")

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
        """(私有) 将一个调度项放入主任务队列。"""
        plan_name = item.get('plan_name')
        task_name = item.get('task')
        item_id = item.get('id')
        if not plan_name or not task_name or not item_id:
            return False
        if not item.get('enabled', False):
            return False

        now = datetime.now()
        async with self.get_async_lock():
            status = self.run_statuses.get(item_id, {})
            if status.get('status') in ('queued', 'running'):
                return False
            cooldown = item.get('run_options', {}).get('cooldown', 0)
            last_run = status.get('last_run')
            if last_run and (now - last_run).total_seconds() < cooldown:
                return False
            self.run_statuses.setdefault(item_id, {}).update({
                'status': 'queued',
                'queued_at': now
            })

        full_task_id = f"{plan_name}/{task_name}"
        task_def = self.all_tasks_definitions.get(full_task_id, {})
        provided_inputs = item.get('inputs') if isinstance(item, dict) else None
        if not isinstance(provided_inputs, dict):
            provided_inputs = {}
        inputs_meta = (task_def.get('meta', {}) or {}).get('inputs', [])
        initial_context = provided_inputs
        if isinstance(inputs_meta, list):
            ok, validated_inputs = self._validate_inputs_against_meta(inputs_meta, provided_inputs)
            if not ok:
                logger.error(f"Schedule '{item_id}' inputs invalid: {validated_inputs}")
                return False
            initial_context = validated_inputs

        payload = dict(item)
        if isinstance(initial_context, dict):
            payload['inputs'] = initial_context
        tasklet = Tasklet(
            task_name=full_task_id,
            payload=payload,
            triggering_event=triggering_event,
            initial_context=initial_context,
            execution_mode=task_def.get('execution_mode', 'sync')
        )
        self._ensure_tasklet_identifiers(tasklet, plan_name=plan_name, task_name=task_name, source=source)
        await self.task_queue.put(tasklet)
        return True

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
        """规范化 meta.inputs 字段定义，支持 list<type>/dict/enum 等写法。"""
        if not isinstance(schema, dict):
            return {"type": "string"}
        normalized = dict(schema)
        enum_vals = normalized.get("enum")
        if enum_vals is None and "options" in normalized:
            enum_vals = normalized.get("options")
        if enum_vals is not None:
            normalized["enum"] = enum_vals or []

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

    def _validate_input_value(self, schema: Dict[str, Any], value: Any, path: str):
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
            min_items = s.get("min_items") if s.get("min_items") is not None else s.get("minItems")
            max_items = s.get("max_items") if s.get("max_items") is not None else s.get("maxItems")
            if min_items is not None and len(value) < min_items:
                return False, None, f"Input '{path}' must contain at least {min_items} items."
            if max_items is not None and len(value) > max_items:
                return False, None, f"Input '{path}' must contain no more than {max_items} items."
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

    def _validate_inputs_against_meta(self, inputs_meta: List[Dict[str, Any]], provided_inputs: Dict[str, Any]):
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
        """(私有) 从 Plan 的 `schedule.yaml` 文件中加载计划任务项。"""
        schedule_path = plan_dir / "schedule.yaml"
        if schedule_path.exists():
            try:
                with open(schedule_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                if not isinstance(data, dict):
                    logger.error(f"Schedule file '{schedule_path}' should define a mapping with 'schedules'.")
                    return
                items = data.get('schedules', [])
                if not isinstance(items, list):
                    logger.error(f"Schedule file '{schedule_path}' has invalid 'schedules' format.")
                    return
                for idx, item in enumerate(items):
                    if not isinstance(item, dict):
                        continue
                    task_name = item.get('task')
                    if not task_name:
                        logger.warning(f"Schedule item missing task in '{schedule_path}'.")
                        continue
                    item = dict(item)
                    item['plan_name'] = plan_name
                    item.setdefault('triggers', [])
                    item_id = item.get('id') or f"{plan_name}:{task_name}:{idx}"
                    item['id'] = item_id
                    self.schedule_items.append(item)
                    self.run_statuses.setdefault(item_id, {'status': 'idle'})
            except Exception as e:
                logger.error(f"加载调度文件 '{schedule_path}' 失败: {e}")

    def _load_interrupt_file(self, plan_dir: Path, plan_name: str):
        """(私有) 从 Plan 的 `interrupts.yaml` 文件中加载中断规则。"""
        interrupt_path = plan_dir / "interrupts.yaml"
        if interrupt_path.exists():
            try:
                with open(interrupt_path, 'r', encoding='utf-8') as f:
                    for rule in (yaml.safe_load(f) or {}).get('interrupts', []):
                        rule['plan_name'] = plan_name
                        self.interrupt_definitions[rule['name']] = rule
                        if rule.get('scope') == 'global' and rule.get('enabled_by_default', False):
                            self.user_enabled_globals.add(rule['name'])
            except Exception as e:
                logger.error(f"加载中断文件 '{interrupt_path}' 失败: {e}")

    def update_run_status(self, item_id: str, status_update: Dict[str, Any]):
        """线程安全地更新一个计划任务的运行状态。"""
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._async_update_run_status(item_id, status_update), self._loop)
            try:
                future.result(timeout=2)
            except Exception as e:
                logger.error(f"异步更新运行状态失败: {e}")
        else:
            with self.fallback_lock:
                if item_id:
                    self.run_statuses.setdefault(item_id, {}).update(status_update)
                    if self.ui_update_queue:
                        try:
                            self.ui_update_queue.put_nowait({'type': 'run_status_single_update',
                                                             'data': {'id': item_id, **self.run_statuses[item_id]}})
                        except queue.Full:
                            logger.warning("UI更新队列已满，丢弃消息: run_status_single_update")

    def run_manual_task(self, task_id: str):
        """将一个预定义的计划任务（通过其ID）手动加入执行队列。"""
        if not self.is_running or self._loop is None or not self._loop.is_running():
            return {"status": "error", "message": "Scheduler is not running."}

        schedule_item = None
        for it in self.schedule_items:
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
            if hasattr(self, "task_definitions") and isinstance(self.task_definitions, dict):
                task_def = self.task_definitions.get(full_task_id)
            if task_def is None and hasattr(self, "plan_definitions"):
                plan_def = self.plan_definitions.get(plan_name) if isinstance(self.plan_definitions, dict) else None
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
                payload={
                    "plan_name": plan_name,
                    "task_name": task_name,
                    "inputs": merged_inputs
                }
            )
            self._ensure_tasklet_identifiers(tasklet, plan_name=plan_name, task_name=task_name, source="manual")
        except Exception as e:
            logger.exception("Create Tasklet failed")
            return {"status": "error", "message": f"Create Tasklet failed: {e}"}

        async def _enqueue():
            try:
                await self.event_bus.publish(Event(
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
                        "delay_until": None
                    }
                ))
            except Exception:
                pass
            await self.task_queue.put(tasklet)

        try:
            fut = asyncio.run_coroutine_threadsafe(_enqueue(), self._loop)
            fut.result(timeout=5.0)
        except Exception as e:
            logger.exception("Enqueue task failed")
            return {"status": "error", "message": f"Enqueue failed: {e}"}

        return {
            "status": "success",
            "message": "Task enqueued.",
            "cid": tasklet.cid,
            "trace_id": tasklet.trace_id,
            "trace_label": tasklet.trace_label
        }

    def run_ad_hoc_task(self, plan_name: str, task_name: str, params: Optional[Dict[str, Any]] = None, temp_id: Optional[str] = None):
        """临时（Ad-hoc）运行一个任何已定义的任务。"""
        params = params or {}

        canonical_id = str(next(self.id_generator))

        async def async_run():
            async with self.get_async_lock():
                orchestrator = self.plan_manager.get_plan(plan_name)
                if not orchestrator:
                    return {"status": "error", "message": f"Plan '{plan_name}' not found or not loaded."}
                if orchestrator.task_loader.get_task_data(task_name) is None:
                    return {"status": "error", "message": f"Task '{task_name}' not found in plan '{plan_name}'."}

                full_task_id = f"{plan_name}/{task_name}"
                task_def = self.all_tasks_definitions.get(full_task_id) or \
                           orchestrator.task_loader.get_task_data(task_name)
                if not task_def:
                    return {"status": "error", "message": f"Task '{task_name}' not found in plan '{plan_name}'."}

                inputs_meta = task_def.get('meta', {}).get('inputs', [])
                ok, validated_inputs = self._validate_inputs_against_meta(inputs_meta, params)
                if not ok:
                    msg = f"Task '{full_task_id}' inputs invalid: {validated_inputs}"
                    logger.error(msg)
                    return {"status": "error", "message": msg}

                tasklet = Tasklet(
                    task_name=full_task_id,
                    cid=canonical_id,
                    is_ad_hoc=True,
                    payload={'plan_name': plan_name, 'task_name': task_name},
                    execution_mode=task_def.get('execution_mode', 'sync'),
                    initial_context=validated_inputs
                )
                self._ensure_tasklet_identifiers(tasklet, plan_name=plan_name, task_name=task_name, source="manual")

            if self.task_queue:
                await self.task_queue.put(tasklet)
                await self._async_update_run_status(full_task_id, {'status': 'queued'})

                try:
                    await self.event_bus.publish(Event(
                        name='queue.enqueued',
                        payload={
                            'cid': tasklet.cid,
                            'trace_id': tasklet.trace_id,
                            'trace_label': tasklet.trace_label,
                            'source': tasklet.source,
                            'plan_name': plan_name,
                            'task_name': task_name,
                            'priority': (self.all_tasks_definitions.get(full_task_id) or {}).get('priority'),
                            'enqueued_at': datetime.now().timestamp(),
                            'delay_until': None
                        }
                    ))
                except Exception:
                    pass

            return {"status": "success", "message": f"Task '{full_task_id}' queued for execution.","temp_id": temp_id,
                "cid": tasklet.cid, "trace_id": tasklet.trace_id, "trace_label": tasklet.trace_label}

        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_run(), self._loop)
            try:
                return future.result(timeout=5)
            except Exception as e:
                full_id = f"{plan_name}/{task_name}"
                logger.warning(f"Ad-hoc task failed for '{full_id}': {e}")
                return {"status": "error", "message": str(e), "temp_id": temp_id}
        else:
            with self.fallback_lock:
                logger.info(f"调度器未运行，临时任务 '{plan_name}/{task_name}' 已加入启动前缓冲区。")
                full_task_id = f"{plan_name}/{task_name}"
                task_def = self.all_tasks_definitions.get(full_task_id, {})
                inputs_meta = task_def.get('meta', {}).get('inputs', [])
                ok, validated_inputs = self._validate_inputs_against_meta(inputs_meta, params or {})
                if not ok:
                    return {"status": "error", "message": f"Task '{full_task_id}' inputs invalid: {validated_inputs}"}
                tasklet = Tasklet(
                    task_name=full_task_id,
                    cid=canonical_id,
                    is_ad_hoc=True,
                    payload={'plan_name': plan_name, 'task_name': task_name},
                    execution_mode=task_def.get('execution_mode', 'sync'),
                    initial_context=validated_inputs
                )
                self._ensure_tasklet_identifiers(tasklet, plan_name=plan_name, task_name=task_name, source="manual")
                self._pre_start_task_buffer.append(tasklet)
                self.run_statuses.setdefault(full_task_id, {}).update(
                    {'status': 'queued', 'queued_at': datetime.now()}
                )
                return {
                    "status": "success",
                    "message": f"Task '{full_task_id}' queued for execution.",
                    "temp_id": temp_id,
                    "cid": tasklet.cid,
                    "trace_id": tasklet.trace_id,
                    "trace_label": tasklet.trace_label
                }


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

    def _update_metrics_from_event(self, name: str, payload: Dict[str, Any]) -> bool:
        """????/??/????????????????????"""
        changed = False
        m = self.metrics
        now = time.time()
        if name == 'task.started':
            m["tasks_started"] += 1
            m["tasks_running"] = max(0, m.get("tasks_running", 0)) + 1
            changed = True
        elif name == 'task.finished':
            m["tasks_finished"] += 1
            m["tasks_running"] = max(0, m.get("tasks_running", 0) - 1)
            status = (payload.get('final_status') or payload.get('status') or '').lower()
            if status == 'success':
                m["tasks_success"] += 1
            elif status == 'error':
                m["tasks_error"] += 1
            elif status == 'failed':
                m["tasks_failed"] += 1
            elif status == 'timeout':
                m["tasks_timeout"] += 1
            elif status == 'cancelled':
                m["tasks_cancelled"] += 1
            changed = True
        elif name in ('node.finished', 'node.failed'):
            m["nodes_total"] += 1
            duration_ms = payload.get("duration_ms")
            if duration_ms is not None:
                try:
                    dur_val = float(duration_ms)
                    m["nodes_duration_ms_sum"] = m.get("nodes_duration_ms_sum", 0.0) + dur_val
                    if m["nodes_total"] > 0:
                        m["nodes_duration_ms_avg"] = m["nodes_duration_ms_sum"] / max(1, m["nodes_total"])
                except Exception:
                    pass
            status = (payload.get("status") or payload.get("final_status") or '').lower()
            if status == 'success':
                m["nodes_succeeded"] += 1
            elif status in ('error', 'failed'):
                m["nodes_failed"] += 1
            changed = True
        elif name.startswith('queue.'):
            changed = True
        if changed:
            m["updated_at"] = now
        return changed

    async def _mirror_event_to_ui_queue(self, event: Event):
        """(私有) 将事件总线中的事件镜像到一个同步队列，供 UI 使用。"""
        if self.ui_event_queue:
            try:
                self.ui_event_queue.put_nowait(event.to_dict())
            except queue.Full:
                pass

    async def _obs_ingest_event(self, event: Event):
        """(私有) 内部可观测性事件的处理器。"""
        name = (event.name or '').lower()
        p = event.payload or {}
        cid = p.get('cid') or p.get('trace_id')
        trace_id = p.get('trace_id')
        trace_label = p.get('trace_label')
        source = p.get('source')
        parent_cid = p.get('parent_cid')

        if trace_id and cid:
            self._obs_runs_by_trace.setdefault(trace_id, cid)

        if not cid:
            return

        run_snapshot = None
        metrics_changed = False
        persist_event = False
        async with self.get_async_lock():
            if name == 'task.started':
                run = self._obs_runs.setdefault(cid, {
                    'cid': cid,
                    'trace_id': trace_id,
                    'trace_label': trace_label,
                    'source': source,
                    'parent_cid': parent_cid,
                    'plan_name': p.get('plan_name'),
                    'task_name': p.get('task_name'),
                    'started_at': int((p.get('start_time') or 0) * 1000) if p.get('start_time') and p.get('start_time') < 1e12 else int(p.get('start_time') or 0),
                    'finished_at': None,
                    'status': 'running',
                    'nodes': [],
                    'queue_wait_ms': p.get('queue_wait_ms'),
                    'dequeued_at': p.get('start_time'),
                })
                if trace_id:
                    run['trace_id'] = trace_id
                if trace_label:
                    run['trace_label'] = trace_label
                if source:
                    run['source'] = source
                if parent_cid is not None:
                    run['parent_cid'] = parent_cid
                if p.get('queue_wait_ms') is not None:
                    run['queue_wait_ms'] = p.get('queue_wait_ms')
                self._obs_ready.pop(cid, None)

                persist_event = True
                run_snapshot = run
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name == 'task.finished':
                run = self._obs_runs.setdefault(cid, {
                    'cid': cid,
                    'trace_id': trace_id,
                    'trace_label': trace_label,
                    'source': source,
                    'parent_cid': parent_cid,
                    'plan_name': p.get('plan_name'),
                    'task_name': p.get('task_name'),
                    'started_at': None,
                    'finished_at': None,
                    'status': 'unknown',
                    'nodes': []
                })
                end_ms = int((p.get('end_time') or 0) * 1000) if p.get('end_time') and p.get('end_time') < 1e12 else int(p.get('end_time') or 0)
                run['finished_at'] = end_ms or run.get('finished_at')
                status = (p.get('final_status') or 'unknown').lower()
                run['status'] = 'success' if status == 'success' else ('error' if status == 'error' else status)
                if run.get('started_at') and end_ms:
                    run['duration_ms'] = max(0, end_ms - int(run.get('started_at') or 0))
                if p.get('duration') is not None:
                    run['duration_ms'] = int(float(p.get('duration')) * 1000)
                if trace_id:
                    run['trace_id'] = trace_id
                if trace_label:
                    run['trace_label'] = trace_label
                if source:
                    run['source'] = source
                if parent_cid is not None:
                    run['parent_cid'] = parent_cid
                if p.get('queue_wait_ms') is not None:
                    run['queue_wait_ms'] = p.get('queue_wait_ms')
                if p.get('duration_ms') is not None:
                    run['duration_ms'] = int(p.get('duration_ms') or 0)

                persist_event = True
                run_snapshot = run
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name == 'node.started':
                run = self._obs_runs.setdefault(cid, {
                    'cid': cid,
                    'trace_id': trace_id,
                    'trace_label': trace_label,
                    'source': source,
                    'parent_cid': parent_cid,
                    'plan_name': p.get('plan_name'),
                    'task_name': p.get('task_name'),
                    'started_at': None, 'finished_at': None, 'status': 'running', 'nodes': []
                })
                node_id = p.get('node_id') or p.get('step_name') or 'node'
                start_ms = int((p.get('start_time') or event.timestamp) * 1000) if (p.get('start_time') or event.timestamp) and (p.get('start_time') or event.timestamp) < 1e12 else int(p.get('start_time') or event.timestamp or 0)
                nodes = run['nodes']
                idx = next((i for i,n in enumerate(nodes) if n.get('node_id') == node_id), -1)
                item = {
                    'node_id': node_id,
                    'node_name': p.get('node_name'),
                    'startMs': start_ms,
                    'endMs': None,
                    'status': 'running',
                    'loop_index': p.get('loop_index', 0),
                    'loop_item': p.get('loop_item')
                }
                if idx >= 0:
                    nodes[idx].update(item)
                else:
                    nodes.append(item)
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name in ('node.finished', 'node.failed'):
                run = self._obs_runs.setdefault(cid, {
                    'cid': cid,
                    'trace_id': trace_id,
                    'trace_label': trace_label,
                    'source': source,
                    'parent_cid': parent_cid,
                    'plan_name': p.get('plan_name'),
                    'task_name': p.get('task_name'),
                    'started_at': None, 'finished_at': None, 'status': 'running', 'nodes': []
                })
                node_id = p.get('node_id') or 'node'
                end_ms = int((p.get('end_time') or event.timestamp) * 1000) if (p.get('end_time') or event.timestamp) and (p.get('end_time') or event.timestamp) < 1e12 else int(p.get('end_time') or event.timestamp or 0)
                status = (p.get('status') or ('error' if name == 'node.failed' else 'success')).lower()
                nodes = run['nodes']
                idx = next((i for i,n in enumerate(nodes) if n.get('node_id') == node_id), -1)
                if idx >= 0:
                    nodes[idx].update({
                        'endMs': end_ms,
                        'status': status,
                        'duration_ms': p.get('duration_ms'),
                        'retry_count': p.get('retry_count'),
                        'exception_type': p.get('exception_type'),
                        'exception_message': p.get('exception_message'),
                        'loop_index': p.get('loop_index', nodes[idx].get('loop_index', 0)),
                        'loop_item': p.get('loop_item', nodes[idx].get('loop_item'))
                    })
                else:
                    nodes.append({
                        'node_id': node_id,
                        'node_name': p.get('node_name'),
                        'startMs': end_ms,
                        'endMs': end_ms,
                        'status': status,
                        'duration_ms': p.get('duration_ms'),
                        'retry_count': p.get('retry_count'),
                        'exception_type': p.get('exception_type'),
                        'exception_message': p.get('exception_message'),
                        'loop_index': p.get('loop_index', 0),
                        'loop_item': p.get('loop_item')
                    })

                run_snapshot = run
                persist_event = True
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name == 'queue.completed':
                run = self._obs_runs.setdefault(cid, {
                    'cid': cid,
                    'trace_id': trace_id,
                    'trace_label': trace_label,
                    'source': source,
                    'parent_cid': parent_cid,
                    'plan_name': p.get('plan_name'),
                    'task_name': p.get('task_name'),
                    'started_at': None, 'finished_at': None, 'status': 'running', 'nodes': []
                })
                if p.get('queue_wait_ms') is not None:
                    run['queue_wait_ms'] = p.get('queue_wait_ms')
                if p.get('exec_ms') is not None:
                    run['exec_ms'] = p.get('exec_ms')
                if p.get('dequeued_at'):
                    run['dequeued_at'] = int(float(p.get('dequeued_at')) * 1000)
                if p.get('completed_at'):
                    run['completed_at'] = int(float(p.get('completed_at')) * 1000)

                run_snapshot = run
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name == 'queue.enqueued':

                item = {
                    'cid': cid,
                    'trace_id': trace_id,
                    'trace_label': trace_label,
                    'source': source,
                    'parent_cid': parent_cid,
                    'plan_name': p.get('plan_name'),
                    'task_name': p.get('task_name'),
                    'priority': p.get('priority'),
                    'enqueued_at': p.get('enqueued_at'),
                    'delay_until': p.get('delay_until')
                }
                if item['delay_until']:
                    self._obs_delayed[cid] = item
                else:
                    self._obs_ready[cid] = item

                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name in ('queue.dequeued', 'task.started'):
                self._obs_ready.pop(cid, None)
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name == 'queue.promoted':
                it = self._obs_delayed.pop(cid, None)
                if it:
                    it['delay_until'] = None
                    self._obs_ready[cid] = it
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name in ('queue.dropped',):
                self._obs_ready.pop(cid, None)
                self._obs_delayed.pop(cid, None)
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

        if persist_event and run_snapshot and self.persist_runs:
            await self._persist_run_snapshot(cid, run_snapshot)
        if metrics_changed:
            snap = self.get_metrics_snapshot()
            await self.event_bus.publish(Event(name="metrics.update", payload=snap))


    def get_queue_overview(self) -> Dict[str, Any]:
        """获取任务队列的概览信息。"""
        import time
        now = time.time()
        with self.fallback_lock:
            ready_list = list(self._obs_ready.values())
            delayed_list = list(self._obs_delayed.values())

        waits = []
        for it in ready_list:
            enq = it.get('enqueued_at')
            if enq:
                waits.append(max(0.0, now - float(enq)))

        avg_wait = float(sum(waits) / len(waits)) if waits else 0.0
        p95 = 0.0
        if waits:
            waits_sorted = sorted(waits)
            k = max(0, int(len(waits_sorted) * 0.95) - 1)
            p95 = float(waits_sorted[k])

        by_plan: Dict[str, int] = {}
        by_pri: Dict[int, int] = {}
        for it in ready_list + delayed_list:
            by_plan[it.get('plan_name') or ''] = by_plan.get(it.get('plan_name') or '', 0) + 1
            pri = int(it.get('priority') or 0)
            by_pri[pri] = by_pri.get(pri, 0) + 1

        oldest_age = 0.0
        for it in ready_list:
            if it.get('enqueued_at'):
                oldest_age = max(oldest_age, now - float(it['enqueued_at']))

        return {
            'ready_length': len(ready_list),
            'delayed_length': len(delayed_list),
            'by_plan': [{'plan': k, 'count': v} for k, v in by_plan.items()],
            'by_priority': [{'priority': k, 'count': v} for k, v in by_pri.items()],
            'avg_wait_sec': avg_wait,
            'p95_wait_sec': p95,
            'oldest_age_sec': oldest_age,
            'throughput': {'m5': 0, 'm15': 0, 'm60': 0}
        }

    def list_queue(self, state: str, limit: int = 200) -> Dict[str, Any]:
        """列出就绪或延迟队列中的任务。"""
        with self.fallback_lock:
            if state == 'ready':
                items = list(self._obs_ready.values())
                items.sort(key=lambda x: x.get('enqueued_at') or 0, reverse=True)
            else:
                items = list(self._obs_delayed.values())
                items.sort(key=lambda x: x.get('delay_until') or 0)

        # 过滤缺少 cid 的条目，避免前端出现“无标识”任务
        filtered = [it for it in items if it.get('cid')]
        if len(filtered) != len(items):
            logger.warning(f"[list_queue] 过滤掉 {len(items) - len(filtered)} 条缺少 cid 的任务条目")

        items = filtered[:max(1, int(limit))]
        for it in items:
            it['__key'] = it.get('trace_id') or it.get('cid') or f"{it.get('plan_name')}/{it.get('task_name')}:{it.get('enqueued_at') or it.get('delay_until')}"
        return {'items': items, 'next_cursor': None}

    def get_metrics_snapshot(self) -> Dict[str, Any]:
        """返回当前基础指标的拷贝（线程安全）。"""
        with self.fallback_lock:
            snap = dict(self.metrics)
            snap["queue_ready"] = len(self._obs_ready)
            snap["queue_delayed"] = len(self._obs_delayed)
            snap["running_tasks"] = len(self.running_tasks)
        return snap

    async def _persist_run_snapshot(self, cid: str, run: Dict[str, Any]):
        """将运行快照持久化到磁盘（可选开启）。"""
        if not self.persist_runs:
            return
        if not cid or not run:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        try:
            run_copy = json.loads(json.dumps(run, default=str))
        except Exception:
            run_copy = dict(run)
        run_copy.setdefault("cid", cid)
        run_copy.setdefault("trace_id", run_copy.get("trace_id"))
        run_copy["persisted_at"] = int(time.time() * 1000)
        target_path = self.run_history_dir / f"{cid}.json"

        def _write():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(run_copy, f, ensure_ascii=False, indent=2)

        try:
            await loop.run_in_executor(None, _write)
        except Exception as exc:
            logger.error(f"Failed to persist run {cid}: {exc}", exc_info=True)

    def list_persisted_runs(self, limit: int = 50, plan_name: Optional[str] = None,
                            task_name: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """读取磁盘上已持久化的运行记录（按修改时间倒序，限制条数）。"""
        if not self.persist_runs:
            return []
        if not self.run_history_dir.exists():
            return []
        try:
            files = sorted(self.run_history_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            return []

        out: List[Dict[str, Any]] = []
        status_lower = status.lower() if status else None
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if plan_name and data.get("plan_name") != plan_name:
                continue
            if task_name and data.get("task_name") != task_name:
                continue
            if status_lower and (data.get("status") or data.get("final_status") or "").lower() != status_lower:
                continue
            data.setdefault("cid", path.stem)
            out.append(data)
            if len(out) >= max(1, int(limit)):
                break
        return out

    def get_persisted_run(self, cid: str) -> Dict[str, Any]:
        """读取单个持久化运行记录。"""
        if not self.persist_runs or not cid:
            return {}
        target = self.run_history_dir / f"{cid}.json"
        if not target.is_file():
            return {}
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def get_run_timeline(self, cid_or_trace: str) -> Dict[str, Any]:
        """???????????????????????????"""
        with self.fallback_lock:
            cid = cid_or_trace
            if cid_or_trace in self._obs_runs_by_trace:
                cid = self._obs_runs_by_trace.get(cid_or_trace, cid_or_trace)
            run = self._obs_runs.get(cid)
            if not run:
                return {}
            return {
                'cid': cid,
                'trace_id': run.get('trace_id'),
                'trace_label': run.get('trace_label'),
                'parent_cid': run.get('parent_cid'),
                'plan_name': run.get('plan_name'),
                'task_name': run.get('task_name'),
                'started_at': run.get('started_at'),
                'finished_at': run.get('finished_at'),
                'queue_wait_ms': run.get('queue_wait_ms'),
                'duration_ms': run.get('duration_ms'),
                'exec_ms': run.get('exec_ms'),
                'status': run.get('status'),
                'nodes': run.get('nodes') or []
            }

    def get_ui_event_queue(self) -> queue.Queue:
        """获取用于 UI 事件的同步队列。"""
        return self.ui_event_queue

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
        if not self._loop or not self._loop.is_running():
            return {"status": "error", "message": "Scheduler is not running, cannot enable hot reload."}

        if self._hot_reload_observer and self._hot_reload_observer.is_alive():
            return {"status": "already_enabled", "message": "Hot reloading is already active."}

        logger.info("Enabling hot reload watcher...")
        event_handler = HotReloadHandler(self)
        self._hot_reload_observer = Observer()
        plans_path = str(self.base_path / "plans")
        self._hot_reload_observer.schedule(event_handler, plans_path, recursive=True)
        self._hot_reload_observer.start()
        logger.info(f"Hot reload started; watching {plans_path}")
        return {"status": "enabled", "message": "Hot reloading has been enabled."}

    def disable_hot_reload(self):
        """Disable file-system watch for hot reload."""
        if self._hot_reload_observer and self._hot_reload_observer.is_alive():
            logger.info("Disabling hot reload watcher...")
            self._hot_reload_observer.stop()
            self._hot_reload_observer.join()
            self._hot_reload_observer = None
            logger.info("Hot reload watcher stopped.")
            return {"status": "disabled", "message": "Hot reloading has been disabled."}

        return {"status": "not_active", "message": "Hot reloading was not active."}

    def is_hot_reload_enabled(self) -> bool:
        """Return True if the hot reload watcher is running."""
        return bool(self._hot_reload_observer and self._hot_reload_observer.is_alive())

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

                self._load_plan_specific_data()
                logger.info(f"插件 '{plugin_id}' 已成功热重载。")

            except Exception as e:
                logger.error(f"热重载插件时出错: {e}", exc_info=True)

    def get_active_runs_snapshot(self) -> List[Dict[str, Any]]:
        """
        线程安全地获取当前所有活动运行的快照。
        包括正在执行的任务和队列中等待的任务。
        """
        import time

        with self.fallback_lock:
            active_list = []
            current_time_ms = int(time.time() * 1000)

            # ✅ 1. 正在执行的任务（从 running_tasks 获取）
            for cid in list(self.running_tasks.keys()):
                run_data = self._obs_runs.get(cid)

                if run_data and run_data.get('status') == 'running':
                    # ✅ 有完整的运行数据
                    active_list.append(run_data)
                else:
                    # ✅ 事件还没更新，返回临时数据
                    logger.debug(f"[get_active_runs_snapshot] Task {cid} is running but not in _obs_runs yet")

                    # 尝试从 _obs_ready 获取基础信息
                    ready_item = self._obs_ready.get(cid, {})

                    active_list.append({
                        'cid': cid,
                        'trace_id': ready_item.get('trace_id'),
                        'trace_label': ready_item.get('trace_label'),
                        'plan_name': ready_item.get('plan_name'),
                        'task_name': ready_item.get('task_name'),
                        'status': 'starting',  # ← 标记为启动中
                        'started_at': current_time_ms,
                        'finished_at': None,
                        'nodes': []
                    })

            # ✅ 2. 队列中等待的任务（可选：如果你想在前端显示"队列中"的任务）
            for cid, item in self._obs_ready.items():
                if cid not in self.running_tasks:  # 避免重复
                    active_list.append({
                        'cid': cid,
                        'trace_id': item.get('trace_id'),
                        'trace_label': item.get('trace_label'),
                        'plan_name': item.get('plan_name'),
                        'task_name': item.get('task_name'),
                        'status': 'queued',
                        'enqueued_at': int(item.get('enqueued_at', 0) * 1000),
                        'started_at': None,
                        'finished_at': None,
                        'nodes': []
                    })

            logger.debug(f"[get_active_runs_snapshot] Returning {len(active_list)} active runs")
            return active_list

    # scheduler.py 新增方法（添加在 Scheduler 类中）

    def run_batch_ad_hoc_tasks(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量派发多个临时任务。

        Args:
            tasks: 任务列表，每个任务包含 plan_name, task_name, inputs

        Returns:
            包含所有任务派发结果的字典
        """
        results = []
        success_count = 0
        failed_count = 0

        for task in tasks:
            try:
                result = self.run_ad_hoc_task(
                    plan_name=task.get("plan_name"),
                    task_name=task.get("task_name"),
                    params=task.get("inputs", {})
                )

                if result.get("status") == "success":
                    success_count += 1
                else:
                    failed_count += 1

                results.append({
                    "plan_name": task.get("plan_name"),
                    "task_name": task.get("task_name"),
                    "status": result.get("status"),
                    "message": result.get("message"),
                    "cid": result.get("cid"),
                    "trace_id": result.get("trace_id"),
                    "trace_label": result.get("trace_label")
                })
            except Exception as e:
                failed_count += 1
                results.append({
                    "plan_name": task.get("plan_name"),
                    "task_name": task.get("task_name"),
                    "status": "error",
                    "message": str(e),
                    "cid": None,
                    "trace_id": None,
                    "trace_label": None
                })

        return {
            "results": results,
            "success_count": success_count,
            "failed_count": failed_count
        }

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
        """批量获取多个任务的状态。

        Args:
            cids: 任务的 cid 列表

        Returns:
            包含所有任务状态的列表
        """
        results = []

        with self.fallback_lock:
            for cid in cids:
                # 尝试从 _obs_runs 中查找
                run_data = self._obs_runs.get(cid)

                if run_data:
                    results.append({
                        "cid": cid,
                        "status": run_data.get("status"),
                        "plan_name": run_data.get("plan_name"),
                        "task_name": run_data.get("task_name"),
                        "started_at": run_data.get("started_at"),
                        "finished_at": run_data.get("finished_at"),
                        "nodes": run_data.get("nodes", [])
                    })
                else:
                    # 如果在 _obs_runs 中找不到，可能任务还在队列中
                    results.append({
                        "cid": cid,
                        "status": "not_found",
                        "plan_name": None,
                        "task_name": None,
                        "started_at": None,
                        "finished_at": None,
                        "nodes": None
                    })

        return results

    # scheduler.py 中新增方法

    async def queue_insert_at(self, index: int, plan_name: str, task_name: str,
                              params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """在队列的指定位置插入任务。"""
        full_task_id = f"{plan_name}/{task_name}"
        task_def = self.all_tasks_definitions.get(full_task_id, {})

        canonical_id = str(next(self.id_generator))

        tasklet = Tasklet(
            task_name=full_task_id,
            cid=canonical_id,
            is_ad_hoc=True,
            payload={'plan_name': plan_name, 'task_name': task_name},
            execution_mode=task_def.get('execution_mode', 'sync'),
            initial_context=params or {}
        )
        self._ensure_tasklet_identifiers(tasklet, plan_name=plan_name, task_name=task_name, source="manual")

        success = await self.task_queue.insert_at(index, tasklet)

        if success:
            return {"status": "success", "cid": canonical_id, "message": f"Task inserted at position {index}"}
        else:
            return {"status": "error", "message": "Failed to insert task"}

    async def queue_remove_task(self, cid: str) -> Dict[str, Any]:
        """从队列中删除指定任务。"""
        success = await self.task_queue.remove_by_cid(cid)

        if success:
            return {"status": "success", "message": f"Task {cid} removed from queue"}
        else:
            return {"status": "error", "message": f"Task {cid} not found in queue"}

    async def queue_move_to_front(self, cid: str) -> Dict[str, Any]:
        """将任务移动到队列头部。"""
        success = await self.task_queue.move_to_front(cid)

        if success:
            return {"status": "success", "message": f"Task {cid} moved to front"}
        else:
            return {"status": "error", "message": f"Task {cid} not found in queue"}

    async def queue_move_to_position(self, cid: str, new_index: int) -> Dict[str, Any]:
        """将任务移动到指定位置。"""
        success = await self.task_queue.move_to_position(cid, new_index)

        if success:
            return {"status": "success", "message": f"Task {cid} moved to position {new_index}"}
        else:
            return {"status": "error", "message": f"Task {cid} not found in queue"}

    async def queue_list_all(self) -> List[Dict[str, Any]]:
        """获取队列中所有任务。"""
        return await self.task_queue.list_all()

    async def queue_clear(self) -> Dict[str, Any]:
        """清空队列。"""
        count = await self.task_queue.clear()
        return {"status": "success", "message": f"Cleared {count} tasks from queue"}

    async def queue_reorder(self, cid_order: List[str]) -> Dict[str, Any]:
        """重新排序队列。"""
        success = await self.task_queue.reorder(cid_order)

        if success:
            return {"status": "success", "message": "Queue reordered successfully"}
        else:
            return {"status": "error", "message": "Failed to reorder queue"}

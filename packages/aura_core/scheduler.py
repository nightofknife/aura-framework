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
import queue
import threading
import time
import uuid
from asyncio import TaskGroup
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Any, List, Optional, Callable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import yaml
import sys

from packages.aura_core.event_bus import EventBus, Event
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

if TYPE_CHECKING:
    from packages.aura_core.orchestrator import Orchestrator


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
        self.base_path = Path(__file__).resolve().parents[2]
        self._main_task: Optional[asyncio.Task] = None
        self._scheduler_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.num_event_workers = 4
        self.startup_complete_event = threading.Event()
        self._pre_start_task_buffer: List[Tasklet] = []
        self.fallback_lock = threading.RLock()
        self.pause_event = asyncio.Event()
        self.id_generator = SnowflakeGenerator(instance=1)
        # --- 异步组件 (运行时初始化) ---
        self.is_running: Optional[asyncio.Event] = None
        self.task_queue: Optional[TaskQueue] = None
        self.event_task_queue: Optional[TaskQueue] = None
        self.interrupt_queue: Optional[asyncio.Queue[Dict]] = None
        self.async_data_lock: Optional[asyncio.Lock] = None

        self.api_log_queue: queue.Queue = queue.Queue(maxsize=500)

        # --- 服务实例 ---
        self.config_service = ConfigService()
        self.event_bus = EventBus()
        self.state_store = StateStoreService(config=self.config_service)
        self.plan_manager = PlanManager(str(self.base_path), self.pause_event)
        self.execution_manager = ExecutionManager(self)
        self.scheduling_service = SchedulingService(self)
        self.interrupt_service = InterruptService(self)

        # --- 运行/调度状态 ---
        self.run_statuses: Dict[str, Dict[str, Any]] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.max_concurrency: int = 1
        self.schedule_items: List[Dict[str, Any]] = []
        self.interrupt_definitions: Dict[str, Dict[str, Any]] = {}
        self.user_enabled_globals: set[str] = set()
        self.all_tasks_definitions: Dict[str, Any] = {}
        self.ui_event_queue = queue.Queue(maxsize=200)
        self.ui_update_queue: Optional[queue.Queue] = None

        # --- 可观测性内存索引 ---
        self._obs_runs: Dict[str, Dict[str, Any]] = {}
        self._obs_ready: Dict[str, Dict[str, Any]] = {}
        self._obs_delayed: Dict[str, Dict[str, Any]] = {}

        def _mk_run_id_from_payload(p: Dict[str, Any]) -> str:
            rid = p.get('run_id')
            if rid:
                return rid
            plan = p.get('plan_name') or 'plan'
            task = p.get('task_name') or 'task'
            st = p.get('start_time')
            if st is None:
                import time
                st = int(time.time() * 1000)
            else:
                st = int(st * 1000) if st < 1e12 else int(st)
            return f"{plan}/{task}:{st}"

        self._mk_run_id_from_payload = _mk_run_id_from_payload

        # --- 初始化流程 ---
        logger.setup(log_dir='logs', task_name='aura_session', api_log_queue=self.api_log_queue)
        self._register_core_services()
        self.reload_plans()

    def _initialize_async_components(self):
        """(私有) 在事件循环内部初始化所有需要事件循环的组件。"""
        logger.debug("Scheduler: 正在事件循环内初始化/重置异步组件...")
        self.is_running = asyncio.Event()
        if self.async_data_lock is None:
            self.async_data_lock = asyncio.Lock()

        self.task_queue = TaskQueue(maxsize=1000)
        self.event_task_queue = TaskQueue(maxsize=2000)
        self.interrupt_queue = asyncio.Queue(maxsize=100)

    def get_async_lock(self) -> asyncio.Lock:
        """获取一个线程安全的异步锁，用于保护共享状态。"""
        if self.async_data_lock is None:
            self.async_data_lock = asyncio.Lock()
            logger.debug("异步数据锁初始化。")
        return self.async_data_lock

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
                logger.warning(f"UI更新队列已满，丢弃消息: {msg_type}")

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
        # ✅ 修复：不要清除所有订阅，只清除那些由 Scheduler 自己注册的
        # await self.event_bus.clear_subscriptions()  # ❌ 移除这行

        # ✅ 只重新注册 Scheduler 自己的订阅
        await self.event_bus.subscribe(
            event_pattern='*',
            callback=self._mirror_event_to_ui_queue,
            channel='*',
            persistent=True  # ✅ 标记为持久化
        )
        await self._subscribe_event_triggers()
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
                logger.info("所有核心后台服务已启动，向主线程发出信号。")
                self.startup_complete_event.set()
        except asyncio.CancelledError:
            logger.info("调度器主任务被取消，正在优雅关闭...")
        finally:
            self.is_running.clear()
            self._loop = None
            self._main_task = None
            logger.info("调度器主循环 (Commander) 已安全退出。")
            self.startup_complete_event.set()

    async def _consume_main_task_queue(self):
        """(私有) 主任务队列的消费者循环。"""
        max_cc = int(getattr(self, "max_concurrency", 1) or 1)

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
                    await asyncio.sleep(0.2)
                    continue

                tasklet = await self.task_queue.get()

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
                        "plan_name": plan_name,
                        "task_name": task_name,
                        "start_time": time.time(),
                    })
                    await self.event_bus.publish(Event(name="queue.dequeued", payload=payload))
                except Exception:
                    pass

                submit_task = asyncio.create_task(self.execution_manager.submit(tasklet))

                key = tasklet.cid if hasattr(tasklet, 'cid') and tasklet.cid else f"task:{int(time.time() * 1000)}"

                logger.info(f"[Queue Consumer] ✅ 任务入队: key={key}")
                self.running_tasks[key] = submit_task

                def _cleanup(_fut: asyncio.Task):
                    try:
                        removed = self.running_tasks.pop(key, None)
                        if removed:
                            logger.debug(f"[_consume_main_task_queue] 任务已从 running_tasks 清除，key={key}")
                        else:
                            logger.warning(f"[_consume_main_task_queue] 清理失败：找不到 key={key}")
                    finally:
                        try:
                            self.task_queue.task_done()
                        except Exception:
                            pass

                submit_task.add_done_callback(_cleanup)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error consuming main task queue")
                await asyncio.sleep(0.5)

    async def _consume_interrupt_queue(self):
        """(私有) 中断队列的消费者循环。"""
        while self.is_running.is_set():
            try:
                handler_rule = await asyncio.wait_for(self.interrupt_queue.get(), timeout=1.0)
                rule_name = handler_rule.get('name', 'unknown_interrupt')
                logger.info(f"指挥官: 开始处理中断 '{rule_name}'...")
                tasks_to_cancel = []
                async with self.get_async_lock():
                    for task_id, task in self.running_tasks.items():
                        if not task_id.startswith('interrupt/'):
                            tasks_to_cancel.append(task)
                for task in tasks_to_cancel:
                    task.cancel()
                handler_task_id = f"interrupt/{rule_name}/{uuid.uuid4()}"
                handler_item = {'plan_name': handler_rule['plan_name'], 'handler_task': handler_rule['handler_task']}
                tasklet = Tasklet(task_name=handler_task_id, payload=handler_item, is_ad_hoc=True, execution_mode='sync')
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
        """(私有) 订阅所有任务定义中声明的事件触发器。"""
        logger.info("--- 订阅事件触发器 ---")
        async with self.get_async_lock():
            subscribed_count = 0
            for task_id, task_data in self.all_tasks_definitions.items():
                triggers = task_data.get('triggers')
                if not isinstance(triggers, list):
                    continue
                for trigger in triggers:
                    if not isinstance(trigger, dict) or 'event' not in trigger:
                        continue
                    event_pattern = trigger['event']
                    plan_name = task_id.split('/')[0]
                    plugin_def = next((p for p in self.plan_manager.plugin_manager.plugin_registry.values() if
                                       p.path.name == plan_name), None)
                    if not plugin_def:
                        continue
                    channel = trigger.get('channel', plugin_def.canonical_id)

                    from functools import partial
                    async def handler(event, task_id_to_run):
                        await self._handle_event_triggered_task(event, task_id_to_run)

                    callback = partial(handler, task_id_to_run=task_id)
                    callback.__name__ = f"event_trigger_for_{task_id.replace('/', '_')}"
                    await self.event_bus.subscribe(event_pattern, callback, channel=channel)
                    subscribed_count += 1
        logger.info(f"事件触发器订阅完成，共 {subscribed_count} 个订阅。")

    async def _handle_event_triggered_task(self, event: Event, task_id: str):
        """(私有) 当事件触发任务时，创建 Tasklet 并放入事件任务队列。"""
        logger.info(f"事件 '{event.name}' (频道: {event.channel}) 触发了任务 '{task_id}'")
        task_def = self.all_tasks_definitions.get(task_id, {})
        tasklet = Tasklet(task_name=task_id, triggering_event=event,
                          execution_mode=task_def.get('execution_mode', 'sync'))
        await self.event_task_queue.put(tasklet)

    def _load_schedule_file(self, plan_dir: Path, plan_name: str):
        """(私有) 从 Plan 的 `schedule.yaml` 文件中加载计划任务项。"""
        schedule_path = plan_dir / "schedule.yaml"
        if schedule_path.exists():
            try:
                with open(schedule_path, 'r', encoding='utf-8') as f:
                    for item in yaml.safe_load(f) or []:
                        item['plan_name'] = plan_name
                        self.schedule_items.append(item)
                        if 'id' in item:
                            self.run_statuses.setdefault(item['id'], {'status': 'idle'})
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
            return {"ok": False, "message": "Scheduler is not running."}

        schedule_item = None
        for it in self.schedule_items:
            if it.get("id") == task_id:
                schedule_item = it
                break
        if not schedule_item:
            return {"ok": False, "message": f"Task id '{task_id}' not found in schedule."}

        plan_name = schedule_item.get("plan_name")
        task_name = schedule_item.get("task_name")
        if not plan_name or not task_name:
            return {"ok": False, "message": "Schedule item missing plan_name/task_name."}

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
            return {"ok": False, "message": f"Missing required inputs: {', '.join(missing)}"}

        try:
            tasklet = Tasklet(
                task_name=full_task_id,
                payload={
                    "plan_name": plan_name,
                    "task_name": task_name,
                    "inputs": merged_inputs
                }
            )
        except Exception as e:
            logger.exception("Create Tasklet failed")
            return {"ok": False, "message": f"Create Tasklet failed: {e}"}

        async def _enqueue():
            try:
                await self.event_bus.publish(Event(
                    name="queue.enqueued",
                    payload={
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
            return {"ok": False, "message": f"Enqueue failed: {e}"}

        return {"ok": True, "message": "Task enqueued."}

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
                if not isinstance(inputs_meta, list):
                    msg = f"Task '{full_task_id}' has malformed meta.inputs (must be a list)."
                    logger.error(msg)
                    return {"status": "error", "message": msg}

                expected_input_names = {item['name'] for item in inputs_meta
                                        if isinstance(item, dict) and 'name' in item}
                extra_params = set(params.keys()) - expected_input_names
                if extra_params:
                    msg = f"Unexpected inputs provided for task '{full_task_id}': {', '.join(extra_params)}"
                    logger.warning(msg)
                    return {"status": "error", "message": msg}

                full_params = {}
                for item in inputs_meta:
                    if not isinstance(item, dict) or 'name' not in item:
                        continue
                    name = item['name']
                    if name in params:
                        full_params[name] = params[name]
                    elif 'default' in item:
                        full_params[name] = item['default']

                required_inputs = {item['name'] for item in inputs_meta
                                   if isinstance(item, dict) and 'name' in item and 'default' not in item}
                missing_params = required_inputs - set(full_params.keys())
                if missing_params:
                    msg = f"Missing required inputs for task '{full_task_id}': {', '.join(missing_params)}"
                    logger.error(msg)
                    return {"status": "error", "message": msg}

                tasklet = Tasklet(
                    task_name=full_task_id,
                    cid=canonical_id,
                    is_ad_hoc=True,
                    payload={'plan_name': plan_name, 'task_name': task_name},
                    execution_mode=task_def.get('execution_mode', 'sync'),
                    initial_context=full_params
                )

            if self.task_queue:
                await self.task_queue.put(tasklet)
                await self._async_update_run_status(full_task_id, {'status': 'queued'})

                try:
                    await self.event_bus.publish(Event(
                        name='queue.enqueued',
                        payload={
                            'cid': canonical_id,
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
                "cid": canonical_id}

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
                tasklet = Tasklet(
                    task_name=full_task_id,
                    cid=canonical_id,
                    is_ad_hoc=True,
                    payload={'plan_name': plan_name, 'task_name': task_name},
                    execution_mode=task_def.get('execution_mode', 'sync'),
                    initial_context=params or {}
                )
                self._pre_start_task_buffer.append(tasklet)
                self.run_statuses.setdefault(full_task_id, {}).update(
                    {'status': 'queued', 'queued_at': datetime.now()}
                )
                return {
                    "status": "success",
                    "message": f"Task '{full_task_id}' queued for execution.",
                    "temp_id": temp_id,
                    "cid": canonical_id
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
        rid = self._mk_run_id_from_payload(p)

        async with self.get_async_lock():
            if name == 'task.started':
                run = self._obs_runs.setdefault(rid, {
                    'run_id': rid,
                    'plan_name': p.get('plan_name'),
                    'task_name': p.get('task_name'),
                    'started_at': int((p.get('start_time') or 0) * 1000) if p.get('start_time') and p.get('start_time') < 1e12 else int(p.get('start_time') or 0),
                    'finished_at': None,
                    'status': 'running',
                    'nodes': []
                })
                self._obs_ready.pop(rid, None)

            elif name == 'task.finished':
                run = self._obs_runs.setdefault(rid, {
                    'run_id': rid,
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

            elif name == 'node.started':
                run = self._obs_runs.setdefault(rid, {
                    'run_id': rid,
                    'plan_name': p.get('plan_name'),
                    'task_name': p.get('task_name'),
                    'started_at': None, 'finished_at': None, 'status': 'running', 'nodes': []
                })
                node_id = p.get('node_id') or p.get('step_name') or 'node'
                start_ms = int((p.get('start_time') or event.timestamp) * 1000) if (p.get('start_time') or event.timestamp) and (p.get('start_time') or event.timestamp) < 1e12 else int(p.get('start_time') or event.timestamp or 0)
                nodes = run['nodes']
                idx = next((i for i,n in enumerate(nodes) if n.get('node_id') == node_id), -1)
                item = {'node_id': node_id, 'startMs': start_ms, 'endMs': None, 'status': 'running'}
                if idx >= 0:
                    nodes[idx].update(item)
                else:
                    nodes.append(item)

            elif name in ('node.finished', 'node.failed'):
                run = self._obs_runs.setdefault(rid, {
                    'run_id': rid,
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
                    nodes[idx].update({'endMs': end_ms, 'status': status})
                else:
                    nodes.append({'node_id': node_id, 'startMs': end_ms, 'endMs': end_ms, 'status': status})

            elif name == 'queue.enqueued':
                item = {
                    'run_id': rid,
                    'plan_name': p.get('plan_name'),
                    'task_name': p.get('task_name'),
                    'priority': p.get('priority'),
                    'enqueued_at': p.get('enqueued_at'),
                    'delay_until': p.get('delay_until')
                }
                if item['delay_until']:
                    self._obs_delayed[rid] = item
                else:
                    self._obs_ready[rid] = item

            elif name in ('queue.dequeued', 'task.started'):
                self._obs_ready.pop(rid, None)

            elif name == 'queue.promoted':
                it = self._obs_delayed.pop(rid, None)
                if it:
                    it['delay_until'] = None
                    self._obs_ready[rid] = it

            elif name in ('queue.dropped',):
                self._obs_ready.pop(rid, None)
                self._obs_delayed.pop(rid, None)

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

        items = items[:max(1, int(limit))]
        for it in items:
            it['__key'] = it.get('run_id') or f"{it.get('plan_name')}/{it.get('task_name')}:{it.get('enqueued_at') or it.get('delay_until')}"
        return {'items': items, 'next_cursor': None}

    def get_run_timeline(self, run_id: str) -> Dict[str, Any]:
        """获取一次任务运行的详细时间线数据。"""
        with self.fallback_lock:
            run = self._obs_runs.get(run_id)
            if not run:
                return {}
            return {
                'run_id': run_id,
                'plan_name': run.get('plan_name'),
                'task_name': run.get('task_name'),
                'started_at': run.get('started_at'),
                'finished_at': run.get('finished_at'),
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
        """启用文件系统监控以实现自动热重载。"""
        if not self._loop or not self._loop.is_running():
            return {"status": "error", "message": "Scheduler is not running, cannot enable hot reload."}

        if self._hot_reload_observer and self._hot_reload_observer.is_alive():
            return {"status": "already_enabled", "message": "Hot reloading is already active."}

        logger.info("正在启用热重载功能...")
        event_handler = HotReloadHandler(self)
        self._hot_reload_observer = Observer()
        plans_path = str(self.base_path / 'plans')
        self._hot_reload_observer.schedule(event_handler, plans_path, recursive=True)
        self._hot_reload_observer.start()
        logger.info(f"热重载已启动，正在监控目录: {plans_path}")
        return {"status": "enabled", "message": "Hot reloading has been enabled."}

    def disable_hot_reload(self):
        """禁用文件系统监控。"""
        if self._hot_reload_observer and self._hot_reload_observer.is_alive():
            logger.info("正在禁用热重载功能...")
            self._hot_reload_observer.stop()
            self._hot_reload_observer.join()
            self._hot_reload_observer = None
            logger.info("热重载已禁用。")
            return {"status": "disabled", "message": "Hot reloading has been disabled."}

        return {"status": "not_active", "message": "Hot reloading was not active."}

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
                plan_name = file_path.relative_to(self.base_path / 'plans').parts[0]
                plugin_def = self.plan_manager.plugin_manager.plugin_registry.get(plan_name)
                if not plugin_def:
                    logger.error(f"热重载失败：找不到与文件 '{file_path.name}' 关联的插件 '{plan_name}'。")
                    return

                plugin_id = plugin_def.canonical_id

                if any(task_id.startswith(f"{plugin_id}/") for task_id in self.running_tasks):
                    logger.warning(f"跳过热重载：插件 '{plugin_id}' 有任务正在运行。")
                    return

                logger.info(f"开始热重载插件: '{plugin_id}'...")

                ACTION_REGISTRY.remove_actions_by_plugin(plugin_id)
                service_registry.remove_services_by_prefix(f"{plugin_id}/")

                module_prefix = ".".join(plugin_def.path.relative_to(self.base_path).parts)
                modules_to_remove = [name for name in sys.modules if name.startswith(module_prefix)]
                if modules_to_remove:
                    logger.debug(
                        f"--> 从 sys.modules 中移除 {len(modules_to_remove)} 个模块 (前缀: {module_prefix})...")
                    for mod_name in modules_to_remove:
                        del sys.modules[mod_name]

                clear_build_cache()
                build_package_from_source(plugin_def)

                self._load_plan_specific_data()
                logger.info(f"插件 '{plugin_id}' 已成功热重载。")

            except Exception as e:
                logger.error(f"热重载插件 '{plan_name}' 时出错: {e}", exc_info=True)

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
                        'run_id': cid,
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
                        'run_id': item.get('run_id', cid),
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
                    "cid": result.get("cid")
                })
            except Exception as e:
                failed_count += 1
                results.append({
                    "plan_name": task.get("plan_name"),
                    "task_name": task.get("task_name"),
                    "status": "error",
                    "message": str(e),
                    "cid": None
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

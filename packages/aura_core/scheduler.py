# packages/aura_core/scheduler.py (REPLACED & FIXED)
import asyncio
import logging
import queue
import threading
import time
import uuid
from asyncio import TaskGroup
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Any, List, Optional, Callable

import yaml

from packages.aura_core.api import service_registry, ACTION_REGISTRY
from packages.aura_core.event_bus import EventBus, Event
from packages.aura_core.state_store_service import StateStoreService
from packages.aura_core.task_queue import TaskQueue, Tasklet
from packages.aura_core.logger import logger
from plans.aura_base.services.config_service import ConfigService
from .execution_manager import ExecutionManager
from .interrupt_service import InterruptService
from .plan_manager import PlanManager
from .scheduling_service import SchedulingService
from .state_planner import StatePlanner
from .asynccontext import plan_context

if TYPE_CHECKING:
    from packages.aura_core.orchestrator import Orchestrator


class Scheduler:
    def __init__(self):
        # --- 核心属性与状态 (非异步部分) ---
        self.base_path = Path(__file__).resolve().parents[2]
        self._main_task: Optional[asyncio.Task] = None
        self._scheduler_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.num_event_workers = 4
        self.startup_complete_event = threading.Event()
        self._pre_start_task_buffer: List[Tasklet] = []
        self.fallback_lock = threading.RLock()

        # 提前创建 pause_event（若未来出现 loop 绑定错误，可移动到 _initialize_async_components）
        self.pause_event = asyncio.Event()

        # --- 异步组件 (运行时初始化) ---
        self.is_running: Optional[asyncio.Event] = None
        self.task_queue: Optional[TaskQueue] = None
        self.event_task_queue: Optional[TaskQueue] = None
        self.interrupt_queue: Optional[asyncio.Queue[Dict]] = None
        self.async_data_lock: Optional[asyncio.Lock] = None

        # 用线程安全队列接 API 日志
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

        self.max_concurrency: int = 1 # 1 = 顺序执行；日后想并发跑，调大即可

        self.schedule_items: List[Dict[str, Any]] = []
        self.interrupt_definitions: Dict[str, Dict[str, Any]] = {}
        self.user_enabled_globals: set[str] = set()
        self.all_tasks_definitions: Dict[str, Any] = {}
        self.ui_event_queue = queue.Queue(maxsize=200)
        self.ui_update_queue: Optional[queue.Queue] = None

        # --- Observability in-memory indexes (NEW) ---
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

    # ------------------------------------------------------------------------------
    # 初始化/锁
    # ------------------------------------------------------------------------------
    def _initialize_async_components(self):
        logger.debug("Scheduler: 正在事件循环内初始化/重置异步组件...")
        self.is_running = asyncio.Event()
        if self.async_data_lock is None:
            self.async_data_lock = asyncio.Lock()

        self.task_queue = TaskQueue(maxsize=1000)
        self.event_task_queue = TaskQueue(maxsize=2000)
        self.interrupt_queue = asyncio.Queue(maxsize=100)

    def get_async_lock(self) -> asyncio.Lock:
        """
        始终返回 asyncio.Lock（避免意外返回线程锁导致 async with 崩溃）
        """
        if self.async_data_lock is None:
            self.async_data_lock = asyncio.Lock()
            logger.debug("异步数据锁初始化。")
        return self.async_data_lock

    # 通用异步更新帮助
    async def _async_update_run_status(self, item_id: str, status_update: Dict[str, Any]):
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
        if read_only:
            async with self.get_async_lock():
                update_func()
        else:
            async with self.get_async_lock():
                update_func()

    def set_ui_update_queue(self, q: queue.Queue):
        self.ui_update_queue = q
        self.execution_manager.set_ui_update_queue(q)

    def _push_ui_update(self, msg_type: str, data: Any):
        if self.ui_update_queue:
            try:
                self.ui_update_queue.put_nowait({'type': msg_type, 'data': data})
            except queue.Full:
                logger.warning(f"UI更新队列已满，丢弃消息: {msg_type}")

    # ------------------------------------------------------------------------------
    # 服务注册/加载
    # ------------------------------------------------------------------------------
    def _register_core_services(self):
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

    async def _async_reload_subscriptions(self):
        await self.event_bus.clear_subscriptions()
        await self.event_bus.subscribe(event_pattern='*', callback=self._mirror_event_to_ui_queue, channel='*')
        await self._subscribe_event_triggers()
        # --- Observability subscriptions (NEW) ---
        await self.event_bus.subscribe(event_pattern='task.*', callback=self._obs_ingest_event, channel='*')
        await self.event_bus.subscribe(event_pattern='node.*', callback=self._obs_ingest_event, channel='*')
        await self.event_bus.subscribe(event_pattern='queue.*', callback=self._obs_ingest_event, channel='*')

    # ------------------------------------------------------------------------------
    # 启停/主循环
    # ------------------------------------------------------------------------------
    def start_scheduler(self):
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            logger.warning("调度器已经在运行中。")
            return
        self.startup_complete_event.clear()
        logger.info("用户请求启动调度器及所有后台服务...")
        self.execution_manager.startup()
        self._scheduler_thread = threading.Thread(target=self._run_scheduler_in_thread, name="SchedulerThread",
                                                  daemon=True)
        self._scheduler_thread.start()
        self._push_ui_update('master_status_update', {"is_running": True})

    def _run_scheduler_in_thread(self):
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
        if not self._scheduler_thread or not self._scheduler_thread.is_alive() or not self._loop:
            logger.warning("调度器已经处于停止状态。")
            return
        logger.info("用户请求停止调度器及所有后台服务...")

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

            await self.event_bus.publish(
                Event(name="scheduler.started", payload={"message": "Scheduler has started."})
            )
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
            await self.event_bus.publish(
                Event(name="scheduler.stopped", payload={"message": "Scheduler has been stopped."})
            )
            self._loop = None
            self._main_task = None
            logger.info("调度器主循环 (Commander) 已安全退出。")
            self.startup_complete_event.set()

    async def _consume_main_task_queue(self):
        """
        从主任务队列取出 Tasklet 并提交到执行管理器。
        - 严格控制并发：默认单并发（顺序执行）；如需并发，可把 self.max_concurrency 调大
         （如果 __init__ 中尚未定义，getattr 会回退为 1）
        - 每次真正取出任务时，镜像发布 queue.dequeued，便于前端刷新
        - 任务完成后从 running_tasks 中移除并 task_done()
        """
        # 允许通过属性动态调整并发；未设置时默认为 1
        max_cc = int(getattr(self, "max_concurrency", 1) or 1)

        while True:
            try:
                # 若达到并发上限，稍等再看
                if len(self.running_tasks) >= max_cc:
                    await asyncio.sleep(0.2)
                    continue

                # 从队列取一个任务（阻塞直至有任务）
                tasklet = await self.task_queue.get()

                # —— 可选：发布“出队”事件，方便 UI 侧 Ready 列表立刻减少 ——
                try:
                    payload = {}
                    # 尽量从 tasklet 中取到关键信息（不同实现下字段名可能不同，这里做容错）
                    tname = getattr(tasklet, "task_name", None) or getattr(tasklet, "name", None)
                    if tname and isinstance(tname, str):
                        # 常见命名：plan/task
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
                    # 出队事件失败不应影响主流程
                    pass

                # 提交执行
                submit_task = asyncio.create_task(self.execution_manager.submit(tasklet))

                # 用一个可区分的 key 跟踪运行中任务
                key = getattr(tasklet, "id", None) or getattr(tasklet, "task_name", None)
                if not key:
                    key = f"task:{int(time.time() * 1000)}"
                self.running_tasks[key] = submit_task

                # 完成清理：从 running_tasks 移除，并标记队列完成
                def _cleanup(_fut: asyncio.Task):
                    try:
                        self.running_tasks.pop(key, None)
                    finally:
                        try:
                            self.task_queue.task_done()
                        except Exception:
                            pass

                submit_task.add_done_callback(_cleanup)

            except asyncio.CancelledError:
                # 终止消费者循环
                break
            except Exception:
                logger.exception("Error consuming main task queue")
                await asyncio.sleep(0.5)

    async def _consume_interrupt_queue(self):
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

    # ------------------------------------------------------------------------------
    # 计划/任务加载
    # ------------------------------------------------------------------------------
    @property
    def plans(self) -> Dict[str, 'Orchestrator']:
        return self.plan_manager.plans

    def _load_plan_specific_data(self):
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

                    if 'steps' in data:  # Old format
                        task_name_from_file = task_file_path.relative_to(tasks_dir).with_suffix('').as_posix()
                        data.setdefault('execution_mode', 'sync')
                        full_task_id = f"{plan_name}/{task_name_from_file}"
                        self.all_tasks_definitions[full_task_id] = data
                    else:  # New format
                        relative_path_str = task_file_path.relative_to(tasks_dir).with_suffix('').as_posix()
                        process_task_definitions(data, relative_path_str)

                except Exception as e:
                    logger.error(f"加载任务文件 '{task_file_path}' 失败: {e}")
        logger.info(f"任务定义加载完毕，共找到 {len(self.all_tasks_definitions)} 个任务。")

    async def _subscribe_event_triggers(self):
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
        logger.info(f"事件 '{event.name}' (频道: {event.channel}) 触发了任务 '{task_id}'")
        task_def = self.all_tasks_definitions.get(task_id, {})
        tasklet = Tasklet(task_name=task_id, triggering_event=event,
                          execution_mode=task_def.get('execution_mode', 'sync'))
        await self.event_task_queue.put(tasklet)

    def _load_schedule_file(self, plan_dir: Path, plan_name: str):
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

    # ------------------------------------------------------------------------------
    # 对外操作
    # ------------------------------------------------------------------------------
    def update_run_status(self, item_id: str, status_update: Dict[str, Any]):
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
        """
        将指定 task_id（来自 schedule_items 的一条）加入执行队列（而非立即运行）。
        - 校验 task 是否存在、inputs 是否齐全（尽力根据定义合并默认值）
        - 通过 event loop 将 Tasklet 入队：self.task_queue.put(tasklet)
        - 发布 queue.enqueued，便于前端 Queue 页即时显示
        返回 { "ok": bool, "message": str }
        """
        # 1) 运行状态检查（需要事件循环与 scheduler 已启动）
        if not self.is_running or self._loop is None or not self._loop.is_running():
            return {"ok": False, "message": "Scheduler is not running."}

        # 2) 在 schedule_items 里定位 task
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

        # 3) 合成 inputs：task 定义里的默认 + 本次提供的 inputs
        #    说明：具体结构依你的定义而定，这里做了“尽力而为”的合并
        provided_inputs = schedule_item.get("inputs") or {}
        inputs_spec = {}
        task_def = None

        # 尝试从不同字典中找到 task 定义
        try:
            if hasattr(self, "task_definitions") and isinstance(self.task_definitions, dict):
                task_def = self.task_definitions.get(full_task_id)
            if task_def is None and hasattr(self, "plan_definitions"):
                # 可能在 plan_definitions 里嵌套
                plan_def = self.plan_definitions.get(plan_name) if isinstance(self.plan_definitions, dict) else None
                if isinstance(plan_def, dict):
                    # 常见结构：plan_def["tasks"][task_name] 或类似
                    tasks_map = plan_def.get("tasks") or {}
                    task_def = tasks_map.get(task_name)
            if isinstance(task_def, dict):
                inputs_spec = task_def.get("inputs") or {}
        except Exception:
            inputs_spec = {}

        # 从 spec 里抽默认值与必填项
        defaults = {}
        required_keys = []
        for key, meta in (inputs_spec.items() if isinstance(inputs_spec, dict) else []):
            if isinstance(meta, dict):
                if "default" in meta:
                    defaults[key] = meta.get("default")
                if meta.get("required"):
                    required_keys.append(key)

        merged_inputs = {**defaults, **(provided_inputs or {})}

        # 检查必填
        missing = [k for k in required_keys if (merged_inputs.get(k) is None or merged_inputs.get(k) == "")]
        if missing:
            return {"ok": False, "message": f"Missing required inputs: {', '.join(missing)}"}

        # 4) 构造 Tasklet（签名因你的实现而异，这里采用常见参数名）
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

        # 5) 通过事件循环把任务放入队列，同时发布 queue.enqueued
        async def _enqueue():
            try:
                await self.event_bus.publish(Event(
                    name="queue.enqueued",
                    payload={
                        "plan_name": plan_name,
                        "task_name": task_name,
                        "priority": None,  # 如有优先级可填入
                        "enqueued_at": time.time(),
                        "delay_until": None
                    }
                ))
            except Exception:
                # 事件失败不影响入队
                pass
            await self.task_queue.put(tasklet)

        try:
            fut = asyncio.run_coroutine_threadsafe(_enqueue(), self._loop)
            fut.result(timeout=5.0)
        except Exception as e:
            logger.exception("Enqueue task failed")
            return {"ok": False, "message": f"Enqueue failed: {e}"}

        return {"ok": True, "message": "Task enqueued."}

    def run_ad_hoc_task(self, plan_name: str, task_name: str, params: Optional[Dict[str, Any]] = None):
        params = params or {}

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
                    is_ad_hoc=True,
                    payload={'plan_name': plan_name, 'task_name': task_name},
                    execution_mode=task_def.get('execution_mode', 'sync'),
                    initial_context=full_params
                )

            if self.task_queue:
                await self.task_queue.put(tasklet)
                await self._async_update_run_status(full_task_id, {'status': 'queued'})

                # 可选：镜像 queue.enqueued（提升 Queue 页体验）
                try:
                    await self.event_bus.publish(Event(
                        name='queue.enqueued',
                        payload={
                            'plan_name': plan_name,
                            'task_name': task_name,
                            'priority': (self.all_tasks_definitions.get(full_task_id) or {}).get('priority'),
                            'enqueued_at': datetime.now().timestamp(),
                            'delay_until': None
                        }
                    ))
                except Exception:
                    pass

            return {"status": "success", "message": f"Task '{full_task_id}' queued for execution."}

        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_run(), self._loop)
            try:
                return future.result(timeout=5)
            except Exception as e:
                full_id = f"{plan_name}/{task_name}"
                logger.warning(f"Ad-hoc task failed for '{full_id}': {e}")
                return {"status": "error", "message": str(e)}
        else:
            with self.fallback_lock:
                logger.info(f"调度器未运行，临时任务 '{plan_name}/{task_name}' 已加入启动前缓冲区。")
                full_task_id = f"{plan_name}/{task_name}"
                task_def = self.all_tasks_definitions.get(full_task_id, {})
                tasklet = Tasklet(
                    task_name=full_task_id,
                    is_ad_hoc=True,
                    payload={'plan_name': plan_name, 'task_name': task_name},
                    execution_mode=task_def.get('execution_mode', 'sync'),
                    initial_context=params or {}
                )
                self._pre_start_task_buffer.append(tasklet)
                self.run_statuses.setdefault(full_task_id, {}).update(
                    {'status': 'queued', 'queued_at': datetime.now()}
                )
                return {"status": "success", "message": f"Task '{full_task_id}' queued for execution."}

    # ------------------------------------------------------------------------------
    # 只读状态查询（供 API）
    # ------------------------------------------------------------------------------
    def get_master_status(self) -> dict:
        is_running = self._scheduler_thread is not None and self._scheduler_thread.is_alive()
        return {"is_running": is_running}

    def get_schedule_status(self):
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
        return ACTION_REGISTRY

    async def _mirror_event_to_ui_queue(self, event: Event):
        if self.ui_event_queue:
            try:
                self.ui_event_queue.put_nowait(event.to_dict())
            except queue.Full:
                pass

    # ------------------------------------------------------------------------------
    # Observability: ingestion & query
    # ------------------------------------------------------------------------------
    async def _obs_ingest_event(self, event: Event):
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

    # ------------------------------------------------------------------------------
    # 其余对前端有用的只读方法
    # ------------------------------------------------------------------------------
    def get_ui_event_queue(self) -> queue.Queue:
        return self.ui_event_queue

    def get_all_plans(self) -> List[str]:
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
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.get_file_content(relative_path)

    async def get_file_content_bytes(self, plan_name: str, relative_path: str) -> bytes:
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.get_file_content_bytes(relative_path)

    async def save_file_content(self, plan_name: str, relative_path: str, content: Any):
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        await orchestrator.save_file_content(relative_path, content)
        logger.info(f"文件已通过Orchestrator异步保存: {relative_path}")

    def trigger_full_ui_update(self):
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
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.create_directory(relative_path)

    async def create_file(self, plan_name: str, relative_path: str, content: str = ""):
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.create_file(relative_path, content)

    async def rename_path(self, plan_name: str, old_relative_path: str, new_relative_path: str):
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.rename_path(old_relative_path, new_relative_path)

    async def delete_path(self, plan_name: str, relative_path: str):
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.delete_path(relative_path)

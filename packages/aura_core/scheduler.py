"""
定义了 `Scheduler`，这是 Aura 框架的中央协调器和生命周期管理器。

`Scheduler` 是整个系统的“大脑”和主入口点。它负责：
- 在一个独立的后台线程中运行主 `asyncio` 事件循环。
- 初始化、管理和协调所有核心后台服务，如 `ExecutionManager`、`SchedulingService`、
  `InterruptService` 和 `PlanManager`。
- 作为所有任务队列（主任务、事件任务、中断任务）的消费者，从队列中取出任务并
  分派给相应的处理器。
- 维护系统的共享状态，如正在运行的任务列表、计划任务的状态等，并提供线程安全的
  访问方法。
- 提供一个统一的、线程安全的API，供外部（如UI或其他线程）与框架交互，例如
  启动/停止调度器、手动运行任务、获取状态等。
- 编排框架资源的加载和重载流程。
"""
import asyncio
import queue
import threading
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

if TYPE_CHECKING:
    from packages.aura_core.orchestrator import Orchestrator


class Scheduler:
    """
    Aura 框架的中央调度器和生命周期管理器。

    这是一个单例（在实践中），负责编排所有核心服务和任务队列。
    """
    def __init__(self):
        """
        初始化调度器。

        此构造函数负责设置所有核心组件和服务的实例，并执行初始的资源加载。
        这是一个同步操作，应在应用程序启动时调用。
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

        # --- 异步组件 (将在每次启动时初始化，先置为None) ---
        self.is_running: Optional[asyncio.Event] = None
        self.task_queue: Optional[TaskQueue] = None
        self.event_task_queue: Optional[TaskQueue] = None
        self.interrupt_queue: Optional[asyncio.Queue[Dict[str, Any]]] = None
        self.api_log_queue: Optional[asyncio.Queue[Dict[str, Any]]] = None
        self.async_data_lock: Optional[asyncio.Lock] = None

        # --- 核心服务实例化 ---
        self.config_service = ConfigService()
        self.event_bus = EventBus()
        self.state_store = StateStoreService(config=self.config_service)
        self.plan_manager = PlanManager(str(self.base_path), self.pause_event)
        self.execution_manager = ExecutionManager(self)
        self.scheduling_service = SchedulingService(self)
        self.interrupt_service = InterruptService(self)

        # --- 状态与定义 (非异步部分) ---
        self.run_statuses: Dict[str, Dict[str, Any]] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.schedule_items: List[Dict[str, Any]] = []
        self.interrupt_definitions: Dict[str, Dict[str, Any]] = {}
        self.user_enabled_globals: set[str] = set()
        self.all_tasks_definitions: Dict[str, Any] = {}
        self.ui_event_queue: queue.Queue[Dict[str, Any]] = queue.Queue(maxsize=200)
        self.ui_update_queue: Optional[queue.Queue[Dict[str, Any]]] = None

        # --- 首次初始化流程 ---
        logger.setup(log_dir='logs', task_name='aura_session', api_log_queue=None)
        self._register_core_services()
        self.reload_plans()

    def _initialize_async_components(self):
        """在事件循环内部初始化或重置所有异步组件。"""
        logger.debug("Scheduler: 正在事件循环内初始化/重置异步组件...")
        self.is_running = asyncio.Event()

        if self.async_data_lock is None:
            self.async_data_lock = asyncio.Lock()

        self.task_queue = TaskQueue(maxsize=1000)
        self.event_task_queue = TaskQueue(maxsize=2000)
        self.interrupt_queue = asyncio.Queue(maxsize=100)
        self.api_log_queue = asyncio.Queue(maxsize=500)
        if hasattr(logger, 'update_api_queue'):
            logger.update_api_queue(self.api_log_queue)

    def get_async_lock(self) -> asyncio.Lock:
        """
        安全地获取异步数据锁。

        此方法为框架内其他需要访问共享状态的服务提供了一个统一的锁获取点。
        它包含一个回退机制，以便在异步循环尚未运行时使用线程锁。

        Returns:
            asyncio.Lock: 异步锁实例。
        """
        if self.async_data_lock is None:
            if self._loop and self._loop.is_running():
                self.async_data_lock = asyncio.Lock()
                logger.debug("异步数据锁被延迟初始化。")
            else:
                logger.warning("正在使用临时的线程锁，因为异步锁尚未初始化。")
                return self.fallback_lock  # type: ignore
        return self.async_data_lock

    async def _async_update_run_status(self, item_id: str, status_update: Dict[str, Any]):
        """异步地更新一个计划项的运行状态，并推送到UI队列。"""
        async with self.get_async_lock():
            if item_id:
                self.run_statuses.setdefault(item_id, {}).update(status_update)
                self._push_ui_update('run_status_single_update', {'id': item_id, **self.run_statuses[item_id]})

    async def _async_get_schedule_status(self) -> List[Dict[str, Any]]:
        """异步地获取所有计划任务的当前状态。"""
        async with self.get_async_lock():
            schedule_items_copy = list(self.schedule_items)
            run_statuses_copy = dict(self.run_statuses)
        status_list = []
        for item in schedule_items_copy:
            full_status = item.copy()
            full_status.update(run_statuses_copy.get(item.get('id'), {}))
            status_list.append(full_status)
        return status_list

    def set_ui_update_queue(self, q: queue.Queue[Dict[str, Any]]):
        """
        设置用于向UI发送更新的队列。

        Args:
            q (queue.Queue): 一个线程安全的队列实例。
        """
        self.ui_update_queue = q
        self.execution_manager.set_ui_update_queue(q)

    def _push_ui_update(self, msg_type: str, data: Any):
        """将一个UI更新消息放入队列。"""
        if self.ui_update_queue:
            try:
                self.ui_update_queue.put_nowait({'type': msg_type, 'data': data})
            except queue.Full:
                logger.warning(f"UI更新队列已满，丢弃消息: {msg_type}")

    def _register_core_services(self):
        """将所有核心服务注册到全局服务注册表中。"""
        from packages.aura_core.builder import set_project_base_path
        set_project_base_path(self.base_path)

        service_registry.register_instance('config', self.config_service, public=True, fqid='core/config')
        service_registry.register_instance('state_store', self.state_store, public=True, fqid='core/state_store')
        service_registry.register_instance('event_bus', self.event_bus, public=True, fqid='core/event_bus')
        service_registry.register_instance('scheduler', self, public=True, fqid='core/scheduler')
        service_registry.register_instance('plan_manager', self.plan_manager, public=False, fqid='core/plan_manager')
        service_registry.register_instance('execution_manager', self.execution_manager, public=False, fqid='core/execution_manager')
        service_registry.register_instance('scheduling_service', self.scheduling_service, public=False, fqid='core/scheduling_service')
        service_registry.register_instance('interrupt_service', self.interrupt_service, public=False, fqid='core/interrupt_service')

    def reload_plans(self):
        """
        重新加载所有方案及其相关的配置、计划任务和中断规则。
        这是一个重量级操作，通常在启动时或需要热重载时调用。
        """
        logger.info("======= Scheduler: 开始加载所有框架资源 =======")
        with self.fallback_lock:
            try:
                config_service = service_registry.get_service_instance('config')
                config_service.load_environment_configs(self.base_path)
                self.plan_manager.initialize()
                self._load_plan_specific_data()
                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(self._async_reload_subscriptions(), self._loop)
                self._push_ui_update('full_status_update', {'schedule': self.get_schedule_status(), 'services': self.get_all_services_status(), 'interrupts': self.get_all_interrupts_status(), 'workspace': {'plans': self.get_all_plans(), 'actions': self.actions.get_all_action_definitions()}})
            except Exception as e:
                logger.critical(f"框架资源加载失败: {e}", exc_info=True)
                raise
        logger.info(f"======= 资源加载完毕 ... =======")

    async def _async_reload_subscriptions(self):
        """异步地清除并重新建立所有事件触发的订阅。"""
        await self.event_bus.clear_subscriptions()
        await self.event_bus.subscribe(event_pattern='*', callback=self._mirror_event_to_ui_queue, channel='*')
        await self._subscribe_event_triggers()

    def start_scheduler(self):
        """
        在一个新的后台线程中启动调度器的主事件循环。
        此方法是非阻塞的。
        """
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            logger.warning("调度器已经在运行中。")
            return
        self.startup_complete_event.clear()
        logger.info("用户请求启动调度器及所有后台服务...")
        self.execution_manager.startup()
        self._scheduler_thread = threading.Thread(target=self._run_scheduler_in_thread, name="SchedulerThread", daemon=True)
        self._scheduler_thread.start()
        self._push_ui_update('master_status_update', {"is_running": True})

    def _run_scheduler_in_thread(self):
        """调度器后台线程的入口点，负责运行主事件循环。"""
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
        """
        平滑地停止调度器和所有后台服务。

        它会向事件循环发送停止信号，取消主任务，然后等待后台线程退出。
        """
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
        """
        调度器的异步主函数。

        此方法在 `asyncio` 事件循环中运行，负责初始化所有异步组件
        并使用 `TaskGroup` 启动所有核心的消费者/服务循环。
        """
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
                tg.create_task(self._log_consumer_loop())
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
        """主任务队列的消费者循环。"""
        while self.is_running.is_set():
            try:
                tasklet = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                if tasklet is None:
                    if hasattr(self.task_queue, 'task_done'): self.task_queue.task_done()
                    continue
                if not hasattr(tasklet, 'task_name') or not tasklet.task_name:
                    logger.warning(f"在队列中发现无效的tasklet，已跳过: {tasklet}")
                    self.task_queue.task_done()
                    continue
                submit_task = asyncio.create_task(self.execution_manager.submit(tasklet))
                self.running_tasks[tasklet.task_name] = submit_task
                submit_task.add_done_callback(lambda t: self.running_tasks.pop(tasklet.task_name, None))
                self.task_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info("主任务队列消费者被取消。")
                break
            except Exception as e:
                logger.error(f"主任务队列消费时发生异常: {e}", exc_info=True)
                if 'tasklet' in locals() and tasklet: self.task_queue.task_done()
                await asyncio.sleep(0.1)
        async with self.get_async_lock():
            self.running_tasks.clear()

    async def _consume_interrupt_queue(self):
        """中断队列的消费者循环。"""
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
        """事件触发任务队列的消费者循环。"""
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
        """获取所有已加载方案的 `Orchestrator` 实例的字典。"""
        return self.plan_manager.plans

    def _load_plan_specific_data(self):
        """加载所有方案特定的数据，如配置、计划、中断等。"""
        config_service = service_registry.get_service_instance('config')
        def load_core():
            logger.info("--- 加载方案包特定数据 ---")
            self.schedule_items.clear()
            self.interrupt_definitions.clear()
            self.user_enabled_globals.clear()
            self.all_tasks_definitions.clear()
            for plugin_def in self.plan_manager.plugin_manager.plugin_registry.values():
                if plugin_def.plugin_type != 'plan': continue
                plan_name = plugin_def.path.name
                config_path = plugin_def.path / 'config.yaml'
                if config_path.is_file():
                    try:
                        with open(config_path, 'r', encoding='utf-8') as f: config_data = yaml.safe_load(f) or {}
                        config_service.register_plan_config(plan_name, config_data)
                    except Exception as e: logger.error(f"加载配置文件 '{config_path}' 失败: {e}")
                self._load_schedule_file(plugin_def.path, plan_name)
                self._load_interrupt_file(plugin_def.path, plan_name)
            self._load_all_tasks_definitions()
        if self._loop and self._loop.is_running():
            async def async_load():
                async with self.get_async_lock(): load_core()
            future = asyncio.run_coroutine_threadsafe(async_load(), self._loop)
            try: future.result(timeout=5)
            except Exception as e:
                logger.error(f"异步加载计划数据失败: {e}")
                with self.fallback_lock: load_core()
        else:
            with self.fallback_lock: load_core()

    def _load_all_tasks_definitions(self):
        """从文件系统加载所有方案下的所有任务定义。"""
        logger.info("--- 加载所有任务定义 ---")
        self.all_tasks_definitions.clear()
        plans_dir = self.base_path / 'plans'
        if not plans_dir.is_dir(): return
        for plan_path in plans_dir.iterdir():
            if not plan_path.is_dir(): continue
            plan_name = plan_path.name
            tasks_dir = plan_path / "tasks"
            if not tasks_dir.is_dir(): continue
            for task_file_path in tasks_dir.rglob("*.yaml"):
                try:
                    with open(task_file_path, 'r', encoding='utf-8') as f: data = yaml.safe_load(f)
                    if not isinstance(data, dict): continue
                    def process_task_definitions(task_data: Dict[str, Any], base_id: str):
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
                except Exception as e: logger.error(f"加载任务文件 '{task_file_path}' 失败: {e}")
        logger.info(f"任务定义加载完毕，共找到 {len(self.all_tasks_definitions)} 个任务。")

    async def _subscribe_event_triggers(self):
        """订阅所有任务定义中声明的事件触发器。"""
        logger.info("--- 订阅事件触发器 ---")
        async with self.get_async_lock():
            subscribed_count = 0
            for task_id, task_data in self.all_tasks_definitions.items():
                triggers = task_data.get('triggers')
                if not isinstance(triggers, list): continue
                for trigger in triggers:
                    if not isinstance(trigger, dict) or 'event' not in trigger: continue
                    event_pattern = trigger['event']
                    plan_name = task_id.split('/')[0]
                    plugin_def = next((p for p in self.plan_manager.plugin_manager.plugin_registry.values() if p.path.name == plan_name), None)
                    if not plugin_def: continue
                    channel = trigger.get('channel', plugin_def.canonical_id)
                    from functools import partial
                    async def handler(event: Event, task_id_to_run: str): await self._handle_event_triggered_task(event, task_id_to_run)
                    callback = partial(handler, task_id_to_run=task_id)
                    callback.__name__ = f"event_trigger_for_{task_id.replace('/', '_')}"
                    await self.event_bus.subscribe(event_pattern, callback, channel=channel)
                    subscribed_count += 1
        logger.info(f"事件触发器订阅完成，共 {subscribed_count} 个订阅。")

    async def _handle_event_triggered_task(self, event: Event, task_id: str):
        """当事件触发时，创建并提交一个 Tasklet 到事件任务队列。"""
        logger.info(f"事件 '{event.name}' (频道: {event.channel}) 触发了任务 '{task_id}'")
        task_def = self.all_tasks_definitions.get(task_id, {})
        tasklet = Tasklet(task_name=task_id, triggering_event=event, execution_mode=task_def.get('execution_mode', 'sync'))
        await self.event_task_queue.put(tasklet)

    def _load_schedule_file(self, plan_dir: Path, plan_name: str):
        """从 schedule.yaml 加载计划任务项。"""
        schedule_path = plan_dir / "schedule.yaml"
        if schedule_path.exists():
            try:
                with open(schedule_path, 'r', encoding='utf-8') as f:
                    for item in yaml.safe_load(f) or []:
                        item['plan_name'] = plan_name
                        self.schedule_items.append(item)
                        if 'id' in item: self.run_statuses.setdefault(item['id'], {'status': 'idle'})
            except Exception as e: logger.error(f"加载调度文件 '{schedule_path}' 失败: {e}")

    def _load_interrupt_file(self, plan_dir: Path, plan_name: str):
        """从 interrupts.yaml 加载中断规则。"""
        interrupt_path = plan_dir / "interrupts.yaml"
        if interrupt_path.exists():
            try:
                with open(interrupt_path, 'r', encoding='utf-8') as f:
                    for rule in (yaml.safe_load(f) or {}).get('interrupts', []):
                        rule['plan_name'] = plan_name
                        self.interrupt_definitions[rule['name']] = rule
                        if rule.get('scope') == 'global' and rule.get('enabled_by_default', False): self.user_enabled_globals.add(rule['name'])
            except Exception as e: logger.error(f"加载中断文件 '{interrupt_path}' 失败: {e}")

    def update_run_status(self, item_id: str, status_update: Dict[str, Any]):
        """
        线程安全地更新一个计划项的运行状态。

        此方法可以从任何线程调用。它会将更新操作提交到调度器的事件循环中执行。
        """
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._async_update_run_status(item_id, status_update), self._loop)
            try: future.result(timeout=2)
            except Exception as e: logger.error(f"异步更新运行状态失败: {e}")
        else:
            with self.fallback_lock:
                if item_id:
                    self.run_statuses.setdefault(item_id, {}).update(status_update)
                    self._push_ui_update('run_status_single_update', {'id': item_id, **self.run_statuses[item_id]})

    def run_manual_task(self, task_id: str) -> Dict[str, str]:
        """
        手动触发一个在 `schedule.yaml` 中定义的任务。

        Args:
            task_id (str): `schedule.yaml` 中定义的任务的 `id`。

        Returns:
            Dict[str, str]: 一个包含操作状态和消息的字典。
        """
        with self.fallback_lock:
            if self.run_statuses.get(task_id, {}).get('status') in ['queued', 'running']: return {"status": "error", "message": "任务已在队列中或正在运行。"}
            item_to_run = next((item for item in self.schedule_items if item.get('id') == task_id), None)
            if not item_to_run: return {"status": "error", "message": "找不到指定的任务ID。"}
            logger.info(f"手动触发任务 '{item_to_run.get('name', task_id)}'...")
            full_task_id = f"{item_to_run['plan_name']}/{item_to_run['task']}"
            task_def = self.all_tasks_definitions.get(full_task_id, {})
            tasklet = Tasklet(task_name=full_task_id, payload=item_to_run, execution_mode=task_def.get('execution_mode', 'sync'))
            if self.is_running and self.is_running.is_set() and self._loop:
                future = asyncio.run_coroutine_threadsafe(self._async_update_run_status(task_id, {'status': 'queued', 'queued_at': datetime.now()}), self._loop)
                try: future.result(timeout=2)
                except Exception as e: logger.error(f"异步更新任务状态失败: {e}")
                future_put = asyncio.run_coroutine_threadsafe(self.task_queue.put(tasklet), self._loop)
                future_put.result(timeout=2)
                return {"status": "success"}
            else:
                self._pre_start_task_buffer.insert(0, tasklet)
                with self.fallback_lock: self.run_statuses.setdefault(task_id, {}).update({'status': 'queued', 'queued_at': datetime.now()})
                return {"status": "success"}

    def run_ad_hoc_task(self, plan_name: str, task_name: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        """
        运行一个临时的、未在 `schedule.yaml` 中定义的任务。

        Args:
            plan_name (str): 任务所属方案的名称。
            task_name (str): 要运行的任务的名称。
            params (Optional[Dict[str, Any]]): 要传递给任务的输入参数。

        Returns:
            Dict[str, str]: 一个包含操作状态和消息的字典。
        """
        async def async_run() -> Dict[str, str]:
            async with self.get_async_lock():
                orchestrator = self.plan_manager.get_plan(plan_name)
                if not orchestrator: return {"status": "error", "message": f"方案 '{plan_name}' 未找到或未加载。"}
                if orchestrator.task_loader.get_task_data(task_name) is None: return {"status": "error", "message": f"任务 '{task_name}' 在方案 '{plan_name}' 中未找到。"}
                full_task_id = f"{plan_name}/{task_name}"
                task_def = self.all_tasks_definitions.get(full_task_id) or orchestrator.task_loader.get_task_data(task_name)
                tasklet = Tasklet(task_name=full_task_id, is_ad_hoc=True, payload={'plan_name': plan_name, 'task_name': task_name}, execution_mode=task_def.get('execution_mode', 'sync'), initial_context=params or {})
            if self.task_queue:
                await self.task_queue.put(tasklet)
                await self._async_update_run_status(full_task_id, {'status': 'queued'})
            return {"status": "success", "message": f"任务 '{full_task_id}' 已加入执行队列。"}
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_run(), self._loop)
            try: return future.result(timeout=5)
            except Exception as e:
                logger.warning(f"运行临时任务 '{task_name}' 失败: {e}")
                return {"status": "error", "message": "任务队列已满或无响应。"}
        else:
            with self.fallback_lock:
                logger.info(f"调度器未运行，临时任务 '{plan_name}/{task_name}' 已加入启动前缓冲区。")
                full_task_id = f"{plan_name}/{task_name}"
                task_def = self.all_tasks_definitions.get(full_task_id, {})
                tasklet = Tasklet(task_name=full_task_id, is_ad_hoc=True, payload={'plan_name': plan_name, 'task_name': task_name}, execution_mode=task_def.get('execution_mode', 'sync'), initial_context=params or {})
                self._pre_start_task_buffer.append(tasklet)
                self.run_statuses.setdefault(full_task_id, {}).update({'status': 'queued', 'queued_at': datetime.now()})
                return {"status": "success", "message": f"任务 '{full_task_id}' 已加入执行队列。"}

    def get_master_status(self) -> Dict[str, bool]:
        """获取调度器的主要运行状态。"""
        is_running = self._scheduler_thread is not None and self._scheduler_thread.is_alive()
        return {"is_running": is_running}

    def get_schedule_status(self) -> List[Dict[str, Any]]:
        """获取所有计划任务的当前状态列表。"""
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._async_get_schedule_status(), self._loop)
            try: return future.result(timeout=2)
            except Exception as e:
                logger.error(f"异步获取调度状态失败: {e}")
                with self.fallback_lock:
                    schedule_items_copy = list(self.schedule_items)
                    run_statuses_copy = dict(self.run_statuses)
                status_list = []
                for item in schedule_items_copy:
                    full_status = item.copy()
                    full_status.update(run_statuses_copy.get(item.get('id'), {}))
                    status_list.append(full_status)
                return status_list
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
    def actions(self) -> 'ACTION_REGISTRY':
        """提供对全局行为注册表的快捷访问。"""
        return ACTION_REGISTRY

    async def _mirror_event_to_ui_queue(self, event: Event):
        """一个事件回调，用于将所有事件镜像到UI事件队列。"""
        if self.ui_event_queue:
            try: self.ui_event_queue.put_nowait(event.to_dict())
            except queue.Full: pass

    def get_ui_event_queue(self) -> queue.Queue[Dict[str, Any]]:
        """获取用于UI事件的队列。"""
        return self.ui_event_queue

    def get_all_plans(self) -> List[str]:
        """获取所有已加载方案的名称列表。"""
        async def async_get_plans() -> List[str]:
            async with self.get_async_lock(): return self.plan_manager.list_plans()
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_get_plans(), self._loop)
            try: return future.result(timeout=1)
            except Exception as e:
                logger.error(f"异步获取所有计划失败: {e}")
                with self.fallback_lock: return self.plan_manager.list_plans()
        else:
            with self.fallback_lock: return self.plan_manager.list_plans()

    def get_plan_files(self, plan_name: str) -> Dict[str, Any]:
        """获取指定方案的文件目录树结构。"""
        logger.debug(f"请求获取 '{plan_name}' 的文件树...")
        plan_path = self.base_path / 'plans' / plan_name
        if not plan_path.is_dir():
            error_msg = f"找不到方案 '{plan_name}' 的目录，路径: {plan_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        tree: Dict[str, Any] = {}
        for path in sorted(plan_path.rglob('*')):
            if any(part in ['.git', '__pycache__', '.idea'] for part in path.parts): continue
            relative_parts = path.relative_to(plan_path).parts
            current_level = tree
            for part in relative_parts[:-1]: current_level = current_level.setdefault(part, {})
            final_part = relative_parts[-1]
            if path.is_file(): current_level[final_part] = None
            elif path.is_dir() and not any(path.iterdir()): current_level.setdefault(final_part, {})
        logger.debug(f"为 '{plan_name}' 构建的文件树: {tree}")
        return tree

    def get_tasks_for_plan(self, plan_name: str) -> List[str]:
        """获取指定方案下的所有任务名称列表。"""
        async def async_get_tasks() -> List[str]:
            async with self.get_async_lock():
                tasks = []
                prefix = f"{plan_name}/"
                for task_id in self.all_tasks_definitions.keys():
                    if task_id.startswith(prefix): tasks.append(task_id[len(prefix):])
                return sorted(tasks)
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_get_tasks(), self._loop)
            try: return future.result(timeout=1)
            except Exception as e:
                logger.error(f"异步获取计划任务失败: {e}")
                with self.fallback_lock:
                    tasks = []
                    prefix = f"{plan_name}/"
                    for task_id in self.all_tasks_definitions.keys():
                        if task_id.startswith(prefix): tasks.append(task_id[len(prefix):])
                    return sorted(tasks)
        else:
            with self.fallback_lock:
                tasks = []
                prefix = f"{plan_name}/"
                for task_id in self.all_tasks_definitions.keys():
                    if task_id.startswith(prefix): tasks.append(task_id[len(prefix):])
                return sorted(tasks)

    def get_all_task_definitions_with_meta(self) -> List[Dict[str, Any]]:
        """
        返回一个包含所有任务详细信息的列表，专为UI构建而设计。

        Returns:
            List[Dict[str, Any]]: 每个任务都是一个包含 `full_task_id`, `plan_name`, `meta` 等键的字典。
        """
        with self.fallback_lock:
            detailed_tasks = []
            for full_task_id, task_def in self.all_tasks_definitions.items():
                try:
                    if not isinstance(task_def, dict): continue
                    plan_name, task_name_in_plan = full_task_id.split('/', 1)
                    detailed_tasks.append({'full_task_id': full_task_id, 'plan_name': plan_name, 'task_name_in_plan': task_name_in_plan, 'meta': task_def.get('meta', {}), 'definition': task_def})
                except ValueError:
                    logger.warning(f"无法从任务ID '{full_task_id}' 中解析方案名，已跳过。")
            return detailed_tasks

    def get_all_services_status(self) -> List[Dict[str, Any]]:
        """获取所有已注册服务的状态列表。"""
        async def async_get_services() -> List[Dict[str, Any]]:
            async with self.get_async_lock():
                service_defs = service_registry.get_all_service_definitions()
                return [s.__dict__ for s in service_defs]
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_get_services(), self._loop)
            try: return future.result(timeout=2)
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
        """获取所有已定义中断规则的状态列表。"""
        async def async_get() -> List[Dict[str, Any]]:
            async with self.get_async_lock():
                status_list = []
                for name, definition in self.interrupt_definitions.items():
                    status_item = definition.copy()
                    status_item['is_global_enabled'] = name in self.user_enabled_globals
                    status_list.append(status_item)
                return status_list
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_get(), self._loop)
            try: return future.result(timeout=2)
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
        """获取一个适合API序列化的服务列表。"""
        with self.fallback_lock:
            original_services = service_registry.get_all_service_definitions()
        api_safe_services = []
        for service_def in original_services:
            class_info = {'module': None, 'name': None}
            if hasattr(service_def.service_class, '__module__') and hasattr(service_def.service_class, '__name__'):
                class_info['module'] = service_def.service_class.__module__
                class_info['name'] = service_def.service_class.__name__
            plugin_info = None
            if service_def.plugin: plugin_info = {'name': service_def.plugin.name, 'canonical_id': service_def.plugin.canonical_id, 'version': service_def.plugin.version, 'plugin_type': service_def.plugin.plugin_type}
            api_safe_services.append({"alias": service_def.alias, "fqid": service_def.fqid, "status": service_def.status, "public": service_def.public, "service_class_info": class_info, "plugin": plugin_info})
        return api_safe_services

    async def get_file_content(self, plan_name: str, relative_path: str) -> str:
        """获取指定方案中文件的文本内容。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator: raise FileNotFoundError(f"方案 '{plan_name}' 未找到或未加载。")
        return await orchestrator.get_file_content(relative_path)

    async def get_file_content_bytes(self, plan_name: str, relative_path: str) -> bytes:
        """获取指定方案中文件的字节内容。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator: raise FileNotFoundError(f"方案 '{plan_name}' 未找到或未加载。")
        return await orchestrator.get_file_content_bytes(relative_path)

    async def save_file_content(self, plan_name: str, relative_path: str, content: Any):
        """将内容保存到指定方案的文件中。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator: raise FileNotFoundError(f"方案 '{plan_name}' 未找到或未加载。")
        await orchestrator.save_file_content(relative_path, content)
        logger.info(f"文件已通过Orchestrator异步保存: {relative_path}")

    def trigger_full_ui_update(self):
        """触发一次完整的UI状态更新。"""
        logger.debug("Scheduler: 正在为新客户端触发一次完整的UI状态更新。")
        payload = {'schedule': self.get_schedule_status(), 'services': self.get_all_services_status(), 'interrupts': self.get_all_interrupts_status(), 'workspace': {'plans': self.get_all_plans(), 'actions': self.actions.get_all_action_definitions()}}
        self._push_ui_update('full_status_update', payload)

    async def _log_consumer_loop(self):
        """异步日志队列的消费者循环。"""
        logger.info("日志消费者服务已启动。")
        while self.is_running.is_set():
            try:
                _ = await asyncio.wait_for(self.api_log_queue.get(), timeout=1.0)
                # 在这里可以添加将日志广播到WebSocket等逻辑
                self.api_log_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info("日志消费者服务已收到取消信号，正在关闭。")
                break
            except Exception as e:
                print(f"CRITICAL: 日志消费者循环出现严重错误: {e}")
                await asyncio.sleep(1)

    async def create_directory(self, plan_name: str, relative_path: str):
        """在指定方案内创建一个新目录。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator: raise FileNotFoundError(f"方案 '{plan_name}' 未找到或未加载。")
        return await orchestrator.create_directory(relative_path)

    async def create_file(self, plan_name: str, relative_path: str, content: str = ""):
        """在指定方案内创建一个新文件。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator: raise FileNotFoundError(f"方案 '{plan_name}' 未找到或未加载。")
        return await orchestrator.create_file(relative_path, content)

    async def rename_path(self, plan_name: str, old_relative_path: str, new_relative_path: str):
        """在指定方案内重命名一个文件或目录。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator: raise FileNotFoundError(f"方案 '{plan_name}' 未找到或未加载。")
        return await orchestrator.rename_path(old_relative_path, new_relative_path)

    async def delete_path(self, plan_name: str, relative_path: str):
        """在指定方案内删除一个文件或目录。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator: raise FileNotFoundError(f"方案 '{plan_name}' 未找到或未加载。")
        return await orchestrator.delete_path(relative_path)






# packages/aura_core/scheduler.py (MODIFIED AND FIXED VERSION)

import asyncio
import logging
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
from packages.aura_core.state_store import StateStore
from packages.aura_core.task_queue import TaskQueue, Tasklet
from packages.aura_core.logger import logger
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

        # 【新增】临时 fallback 锁（仅 init 阶段用，后续移除依赖）
        self.fallback_lock = threading.RLock()

        # --- 异步组件 (将在每次启动时初始化，先置为None) ---
        self.is_running: Optional[asyncio.Event] = None
        self.pause_event: Optional[asyncio.Event] = None
        self.task_queue: Optional[TaskQueue] = None
        self.event_task_queue: Optional[TaskQueue] = None
        self.interrupt_queue: Optional[asyncio.Queue[Dict]] = None
        self.api_log_queue: Optional[asyncio.Queue] = None
        self.async_data_lock: Optional[asyncio.Lock] = None  # 【确认】异步数据锁 placeholder

        # --- 核心服务实例 (只创建一次) ---
        self.state_store = StateStore()
        self.event_bus = EventBus()
        self.plan_manager = PlanManager(str(self.base_path), None)
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
        self.ui_event_queue = queue.Queue(maxsize=200)
        self.ui_update_queue: Optional[queue.Queue] = None

        # --- 首次初始化流程 ---
        logger.setup(log_dir='logs', task_name='aura_session', api_log_queue=None)
        self._register_core_services()
        self.reload_plans()

    def _initialize_async_components(self):
        logger.debug("Scheduler: 正在事件循环内初始化/重置异步组件...")
        self.is_running = asyncio.Event()
        self.pause_event = asyncio.Event()
        if self.async_data_lock is None:  # 【修改】确保创建
            self.async_data_lock = asyncio.Lock()
        self.plan_manager.pause_event = self.pause_event
        self.task_queue = TaskQueue(maxsize=1000)
        self.event_task_queue = TaskQueue(maxsize=2000)
        self.interrupt_queue = asyncio.Queue(maxsize=100)
        self.api_log_queue = asyncio.Queue(maxsize=500)
        if hasattr(logger, 'update_api_queue'):
            logger.update_api_queue(self.api_log_queue)

    def get_async_lock(self) -> asyncio.Lock:
        """
        【新增】获取异步数据锁。如果未初始化（非异步环境），fallback 到线程锁或 raise 错误。
        服务应在异步任务中调用此方法。
        """
        if self.async_data_lock is None:
            if self._loop and self._loop.is_running():
                # Lazy 创建（如果循环运行）
                self.async_data_lock = asyncio.Lock()
                logger.debug("异步数据锁 lazy 初始化。")
            else:
                # 同步 fallback（初始化阶段，临时）
                logger.warning("使用临时线程锁（异步锁未初始化）。")
                return self.fallback_lock  # 【修改】用 fallback_lock（线程锁兼容 with）
        return self.async_data_lock

    # 【新增】辅助方法：异步更新运行状态
    async def _async_update_run_status(self, item_id: str, status_update: Dict[str, Any]):
        async with self.async_data_lock:
            if item_id:
                self.run_statuses.setdefault(item_id, {}).update(status_update)
                # UI 更新保持原样（同步）
                if self.ui_update_queue:
                    try:
                        self.ui_update_queue.put_nowait(
                            {'type': 'run_status_single_update', 'data': {'id': item_id, **self.run_statuses[item_id]}})
                    except queue.Full:
                        logger.warning(f"UI更新队列已满，丢弃消息: run_status_single_update")

    # 【新增】辅助方法：异步获取调度状态
    async def _async_get_schedule_status(self):
        async with self.async_data_lock:
            schedule_items_copy = list(self.schedule_items)
            run_statuses_copy = dict(self.run_statuses)
        status_list = []
        for item in schedule_items_copy:
            full_status = item.copy()
            full_status.update(run_statuses_copy.get(item.get('id'), {}))
            status_list.append(full_status)
        return status_list

    # 【新增】辅助方法：异步更新共享状态（如 running_tasks）
    async def _async_update_shared_state(self, update_func: Callable[[], None], read_only: bool = False):
        """
        【增强】通用异步共享状态更新/读取。
        """
        if read_only:
            async with self.async_data_lock:
                update_func()  # 实际是读取
        else:
            async with self.async_data_lock:
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

    def _register_core_services(self):
        from plans.aura_base.services.config_service import ConfigService
        from packages.aura_core.builder import set_project_base_path
        set_project_base_path(self.base_path)
        service_registry.register_instance('config', ConfigService(), public=True, fqid='core/config')
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
        with self.fallback_lock:  # 【修改】用 fallback_lock 替换 shared_data_lock
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
        logger.info(f"======= 资源加载完毕 ... =======")

    async def _async_reload_subscriptions(self):
        await self.event_bus.clear_subscriptions()
        await self.event_bus.subscribe(event_pattern='*', callback=self._mirror_event_to_ui_queue, channel='*')
        await self._subscribe_event_triggers()

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

        # 【FIX #3 - Graceful Shutdown】步骤1: 首先发出停止信号
        if self.is_running:
            self._loop.call_soon_threadsafe(self.is_running.clear)

        # 【FIX #3 - Graceful Shutdown】步骤2: 然后取消主任务，以中断其等待
        if self._main_task:
            self._loop.call_soon_threadsafe(self._main_task.cancel)

        # 【FIX #3 - Graceful Shutdown】步骤3: 最后等待线程结束
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
        # 【修改】原 with self.shared_data_lock: 替换为 async with（因为 run 是 async）
        async with self.async_data_lock:
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
        while self.is_running.is_set():
            try:
                # 【修改】使用 wait_for 确保超时；防护 None
                tasklet = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                if tasklet is None:
                    logger.debug("主队列 get() 返回 None，跳过空任务。")  # 【新增】防护
                    # 如果 TaskQueue 支持 task_done on None，避免队列积累
                    if hasattr(self.task_queue, 'task_done'):
                        self.task_queue.task_done()
                    continue
                logger.debug(f"从主队列获取任务: {tasklet.task_name}")  # 【确认】原日志，现在安全
                # 【新增】额外检查 tasklet 有效性
                if not hasattr(tasklet, 'task_name') or not tasklet.task_name:
                    logger.warning(f"无效 tasklet 在队列中，跳过: {tasklet}")
                    self.task_queue.task_done()
                    continue
                # 【修改】submit 用 asyncio.create_task，避免直接 await 阻塞循环
                submit_task = asyncio.create_task(self.execution_manager.submit(tasklet))
                self.running_tasks[tasklet.task_name] = submit_task  # 【新增】跟踪 running_tasks
                submit_task.add_done_callback(lambda t: self.running_tasks.pop(tasklet.task_name, None))
                self.task_queue.task_done()
            except asyncio.TimeoutError:
                continue  # 正常超时
            except asyncio.CancelledError:
                logger.info("主任务队列消费者被取消。")
                break
            except Exception as e:  # 【新增】捕获 get/submit 意外，防 TaskGroup 崩溃
                logger.error(f"主任务队列消费异常 (tasklet=None 防护): {e}", exc_info=True)
                if 'tasklet' in locals() and tasklet:
                    self.task_queue.task_done()
                await asyncio.sleep(0.1)  # 短暂暂停，避免 CPU 循环

        # 【确认】结束时清理（原代码）
        async with self.async_data_lock:
            self.running_tasks.clear()

    async def _consume_interrupt_queue(self):
        # 【FIX #3 - Graceful Shutdown】循环条件依赖于 is_running 事件
        while self.is_running.is_set():
            try:
                # 【FIX #3 - Graceful Shutdown】使用带超时的 get
                handler_rule = await asyncio.wait_for(self.interrupt_queue.get(), timeout=1.0)
                rule_name = handler_rule.get('name', 'unknown_interrupt')
                logger.info(f"指挥官: 开始处理中断 '{rule_name}'...")
                tasks_to_cancel = []
                async with self.async_data_lock:  # 【修改】异步锁替换 with shared_data_lock
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
        # 【FIX #3 - Graceful Shutdown】循环条件依赖于 is_running 事件
        while self.is_running.is_set():
            try:
                # 【FIX #3 - Graceful Shutdown】使用带超时的 get
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
                async with self.async_data_lock:
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
        if not plans_dir.is_dir(): return
        for plan_path in plans_dir.iterdir():
            if not plan_path.is_dir(): continue
            plan_name = plan_path.name
            tasks_dir = plan_path / "tasks"
            if not tasks_dir.is_dir(): continue
            for task_file_path in tasks_dir.rglob("*.yaml"):
                try:
                    with open(task_file_path, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)
                    if not isinstance(data, dict): continue

                    # This logic now supports both single-file-single-task (old) and single-file-multiple-tasks (new)
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
        async with self.async_data_lock:  # 【确认】正确
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
                    # Assuming plan canonical_id is 'author/plan_name', we extract plan_name
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
                        if 'id' in item: self.run_statuses.setdefault(item['id'], {'status': 'idle'})
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

    def update_run_status(self, item_id: str, status_update: Dict[str, Any]):
        if self._loop and self._loop.is_running():
            # 【确认】异步调用辅助方法
            future = asyncio.run_coroutine_threadsafe(self._async_update_run_status(item_id, status_update), self._loop)
            try:
                future.result(timeout=2)  # 超时保护
            except Exception as e:
                logger.error(f"异步更新运行状态失败: {e}")
        else:
            # 【修改】fallback 用 fallback_lock 替换 RLock
            with self.fallback_lock:
                if item_id:
                    self.run_statuses.setdefault(item_id, {}).update(status_update)
                    if self.ui_update_queue:
                        try:
                            self.ui_update_queue.put_nowait({'type': 'run_status_single_update',
                                                             'data': {'id': item_id, **self.run_statuses[item_id]}})
                        except queue.Full:
                            logger.warning(f"UI更新队列已满，丢弃消息: run_status_single_update")


    def run_manual_task(self, task_id: str):
        with self.fallback_lock:  # 【修改】替换 with self.shared_data_lock
            if self.run_statuses.get(task_id, {}).get('status') in ['queued', 'running']:
                return {"status": "error", "message": "Task already queued or running."}
            item_to_run = next((item for item in self.schedule_items if item.get('id') == task_id), None)
            if not item_to_run:
                return {"status": "error", "message": "Task ID not found."}
            logger.info(f"手动触发任务 '{item_to_run.get('name', task_id)}'...")
            full_task_id = f"{item_to_run['plan_name']}/{item_to_run['task']}"
            task_def = self.all_tasks_definitions.get(full_task_id, {})
            tasklet = Tasklet(task_name=full_task_id, payload=item_to_run,
                              execution_mode=task_def.get('execution_mode', 'sync'))
            if self.is_running and self.is_running.is_set() and self._loop:
                future = asyncio.run_coroutine_threadsafe(
                    self._async_update_run_status(task_id, {'status': 'queued', 'queued_at': datetime.now()}),
                    self._loop)
                try:
                    future.result(timeout=2)
                except Exception as e:
                    logger.error(f"异步更新任务状态失败: {e}")
                # 【新增】队列 put 通过 executor
                future_put = asyncio.run_coroutine_threadsafe(self.task_queue.put(tasklet), self._loop)
                future_put.result(timeout=2)
                return {"status": "success"}
            else:
                # pre_start 缓冲
                self._pre_start_task_buffer.insert(0, tasklet)
                # 同步 fallback 更新
                with self.fallback_lock:
                    self.run_statuses.setdefault(task_id, {}).update({'status': 'queued', 'queued_at': datetime.now()})
                return {"status": "success"}

    def run_ad_hoc_task(self, plan_name: str, task_name: str, params: Optional[Dict[str, Any]] = None):
        async def async_run():
            async with self.async_data_lock:  # 【确认】正确
                # 【FIX #5 - Task ID Validation】步骤1: 获取对应方案的Orchestrator
                orchestrator = self.plan_manager.get_plan(plan_name)
                if not orchestrator:
                    return {"status": "error", "message": f"Plan '{plan_name}' not found or not loaded."}

                # 【FIX #5 - Task ID Validation】步骤2: 使用TaskLoader验证任务是否存在
                if orchestrator.task_loader.get_task_data(task_name) is None:
                    return {"status": "error", "message": f"Task '{task_name}' not found in plan '{plan_name}'."}

                full_task_id = f"{plan_name}/{task_name}"
                task_def = self.all_tasks_definitions.get(full_task_id)
                if not task_def:
                    # Fallback for old task format which might not be in all_tasks_definitions
                    task_def = orchestrator.task_loader.get_task_data(task_name)

                tasklet = Tasklet(task_name=full_task_id, is_ad_hoc=True,
                                  payload={'plan_name': plan_name, 'task_name': task_name},
                                  execution_mode=task_def.get('execution_mode', 'sync'),
                                  initial_context=params or {})
                # 【确认】队列 put（异步，直接）
                if self.task_queue:
                    await self.task_queue.put(tasklet)
                    # 更新状态
                    await self._async_update_run_status(full_task_id, {'status': 'queued'})
                return {"status": "success", "message": f"Task '{full_task_id}' queued for execution."}

        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_run(), self._loop)
            try:
                return future.result(timeout=5)  # 超时保护（ad-hoc 可能 I/O）
            except Exception as e:
                logger.warning(f"Ad-hoc task failed for '{task_name}': {e}")  # 【修改】用 full_task_id
                return {"status": "error", "message": "Task queue is full or unresponsive."}
        else:
            # fallback 同步（临时）
            with self.fallback_lock:  # 【确认】正确
                logger.info(f"调度器未运行，临时任务 '{plan_name}/{task_name}' 已加入启动前缓冲区。")
                # 【修改】创建实际 tasklet（替换 None）
                full_task_id = f"{plan_name}/{task_name}"
                task_def = self.all_tasks_definitions.get(full_task_id, {})
                tasklet = Tasklet(task_name=full_task_id, is_ad_hoc=True,
                                  payload={'plan_name': plan_name, 'task_name': task_name},
                                  execution_mode=task_def.get('execution_mode', 'sync'),
                                  initial_context=params or {})
                self._pre_start_task_buffer.append(tasklet)
                # 更新状态
                self.run_statuses.setdefault(full_task_id, {}).update({'status': 'queued', 'queued_at': datetime.now()})
                return {"status": "success", "message": f"Task '{full_task_id}' queued for execution."}

    def get_master_status(self) -> dict:
        is_running = self._scheduler_thread is not None and self._scheduler_thread.is_alive()
        return {"is_running": is_running}

    def get_schedule_status(self):
        if self._loop and self._loop.is_running():
            # 【确认】异步调用
            future = asyncio.run_coroutine_threadsafe(self._async_get_schedule_status(), self._loop)
            try:
                return future.result(timeout=2)
            except Exception as e:
                logger.error(f"异步获取调度状态失败: {e}")
                # 【修改】fallback 同步，用 fallback_lock 替换 threading.RLock()
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
    def actions(self):
        return ACTION_REGISTRY

    async def _mirror_event_to_ui_queue(self, event: Event):
        if self.ui_event_queue:
            try:
                self.ui_event_queue.put_nowait(event.to_dict())
            except queue.Full:
                pass

    def get_ui_event_queue(self) -> queue.Queue:
        return self.ui_event_queue

    def get_all_plans(self) -> List[str]:
        async def async_get_plans():
            async with self.async_data_lock:
                return self.plan_manager.list_plans()

        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_get_plans(), self._loop)
            try:
                return future.result(timeout=1)
            except Exception as e:
                logger.error(f"异步获取所有计划失败: {e}")
                # fallback
                with threading.RLock():
                    return self.plan_manager.list_plans()
        else:
            # fallback 同步
            with threading.RLock():
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
            async with self.async_data_lock:
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
                # fallback
                with threading.RLock():
                    tasks = []
                    prefix = f"{plan_name}/"
                    for task_id in self.all_tasks_definitions.keys():
                        if task_id.startswith(prefix):
                            tasks.append(task_id[len(prefix):])
                    return sorted(tasks)
        else:
            # fallback 同步
            with threading.RLock():
                tasks = []
                prefix = f"{plan_name}/"
                for task_id in self.all_tasks_definitions.keys():
                    if task_id.startswith(prefix):
                        tasks.append(task_id[len(prefix):])
                return sorted(tasks)

    def get_all_services_status(self) -> List[Dict[str, Any]]:
        async def async_get_services():
            async with self.async_data_lock:
                # This now returns dataclass objects, which need to be converted for some UIs
                service_defs = service_registry.get_all_service_definitions()
                return [s.__dict__ for s in service_defs]

        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(async_get_services(), self._loop)
            try:
                return future.result(timeout=2)
            except Exception as e:
                logger.error(f"异步获取所有服务状态失败: {e}")
                # fallback
                with threading.RLock():
                    service_defs = service_registry.get_all_service_definitions()
                    return [s.__dict__ for s in service_defs]
        else:
            # fallback 同步
            with threading.RLock():
                service_defs = service_registry.get_all_service_definitions()
                return [s.__dict__ for s in service_defs]

    def get_all_interrupts_status(self) -> List[Dict[str, Any]]:
        async def async_get():
            async with self.async_data_lock:
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
                # fallback
                with threading.RLock():
                    status_list = []
                    for name, definition in self.interrupt_definitions.items():
                        status_item = definition.copy()
                        status_item['is_global_enabled'] = name in self.user_enabled_globals
                        status_list.append(status_item)
                    return status_list
        else:
            with threading.RLock():
                status_list = []
                for name, definition in self.interrupt_definitions.items():
                    status_item = definition.copy()
                    status_item['is_global_enabled'] = name in self.user_enabled_globals
                    status_list.append(status_item)
                return status_list

    def get_all_services_for_api(self) -> List[Dict[str, Any]]:
        with self.fallback_lock:  # 【修改】替换 with self.shared_data_lock
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

    async def _log_consumer_loop(self):
        logger.info("日志消费者服务已启动。")
        underlying_logger = logger.logger
        handlers_to_use = [h for h in underlying_logger.handlers if h.name != "api_queue"]
        if not handlers_to_use:
            logger.warning("日志消费者启动，但没有找到文件或控制台等目标处理器。日志将不会被记录。")

        # 【FIX #3 - Graceful Shutdown】循环条件依赖于 is_running 事件
        while self.is_running.is_set():
            try:
                # 【FIX #3 - Graceful Shutdown】使用带超时的 get
                log_entry = await asyncio.wait_for(self.api_log_queue.get(), timeout=1.0)
                if log_entry and isinstance(log_entry, dict):
                    record = logging.makeLogRecord(log_entry)
                    for handler in handlers_to_use:
                        if record.levelno >= handler.level:
                            handler.handle(record)
                self.api_log_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info("日志消费者服务已收到取消信号，正在关闭。")
                break
            except Exception as e:
                # Use print here as the logger itself might be the source of the issue
                print(f"CRITICAL: 日志消费者循环出现严重错误: {e}")
                await asyncio.sleep(1)

    async def create_directory(self, plan_name: str, relative_path: str):
        """【新增】委托给Orchestrator创建目录。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.create_directory(relative_path)

    async def create_file(self, plan_name: str, relative_path: str, content: str = ""):
        """【新增】委托给Orchestrator创建文件。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.create_file(relative_path, content)

    async def rename_path(self, plan_name: str, old_relative_path: str, new_relative_path: str):
        """【新增】委托给Orchestrator重命名路径。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.rename_path(old_relative_path, new_relative_path)

    async def delete_path(self, plan_name: str, relative_path: str):
        """【新增】委托给Orchestrator删除路径。"""
        orchestrator = self.plan_manager.get_plan(plan_name)
        if not orchestrator:
            raise FileNotFoundError(f"Plan '{plan_name}' not found or not loaded.")
        return await orchestrator.delete_path(relative_path)






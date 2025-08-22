# packages/aura_core/scheduler.py (最终修正版)

import asyncio
import queue
import threading
import uuid
from asyncio import TaskGroup
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Any, List, Optional

import yaml

from packages.aura_core.api import service_registry, ACTION_REGISTRY, hook_manager
from packages.aura_core.event_bus import EventBus, Event
from packages.aura_core.state_store import StateStore
from packages.aura_core.task_queue import TaskQueue, Tasklet
from packages.aura_shared_utils.utils.logger import logger
from .execution_manager import ExecutionManager
from .interrupt_service import InterruptService
from .plugin_manager import PluginManager
from .scheduling_service import SchedulingService

if TYPE_CHECKING:
    from packages.aura_core.orchestrator import Orchestrator


class Scheduler:
    def __init__(self):
        # --- 核心属性与状态 ---
        self.base_path = Path(__file__).resolve().parents[2]
        self.is_running = asyncio.Event()
        self.pause_event = asyncio.Event()
        self._main_task: Optional[asyncio.Task] = None
        self._scheduler_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.num_event_workers = 4  # 可以根据需要调整
        self.base_path = Path(__file__).resolve().parents[2]
        self.is_running = asyncio.Event()


        # --- 遗留的线程安全锁，用于保护被UI线程访问的共享数据 ---
        self.shared_data_lock = threading.RLock()

        # --- 核心服务实例 ---
        self.state_store = StateStore()
        self.event_bus = EventBus()
        self.plugin_manager = PluginManager(self.base_path)
        self.execution_manager = ExecutionManager(self)
        self.scheduling_service = SchedulingService(self)
        self.interrupt_service = InterruptService(self)

        # --- 任务与执行状态 ---
        self.task_queue = TaskQueue(maxsize=1000)
        self.event_task_queue = TaskQueue(maxsize=2000)
        self.interrupt_queue: asyncio.Queue[Dict] = asyncio.Queue(maxsize=100)
        self.run_statuses: Dict[str, Dict[str, Any]] = {}

        # --- 运行中任务的追踪 (用于中断) ---
        self.running_tasks: Dict[str, asyncio.Task] = {}

        # --- 配置与定义 ---
        self.schedule_items: List[Dict[str, Any]] = []
        self.interrupt_definitions: Dict[str, Dict[str, Any]] = {}
        self.user_enabled_globals: set[str] = set()
        self.all_tasks_definitions: Dict[str, Any] = {}

        # --- UI 通信 ---
        self.ui_event_queue = queue.Queue(maxsize=200)
        self.ui_update_queue: Optional[queue.Queue] = None

        # 【新增】API实时通信队列
        self.api_log_queue: asyncio.Queue = asyncio.Queue(maxsize=500)

        # --- 初始化流程 ---
        logger.setup(
            log_dir='logs',
            task_name='aura_session',
            api_log_queue=self.api_log_queue
        )
        self._register_core_services()
        self.reload_plans()

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
        service_registry.register_instance('plugin_manager', self.plugin_manager, public=False,
                                           fqid='core/plugin_manager')
        service_registry.register_instance('execution_manager', self.execution_manager, public=False,
                                           fqid='core/execution_manager')
        service_registry.register_instance('scheduling_service', self.scheduling_service, public=False,
                                           fqid='core/scheduling_service')
        service_registry.register_instance('interrupt_service', self.interrupt_service, public=False,
                                           fqid='core/interrupt_service')

    def reload_plans(self):
        logger.info("======= Scheduler: 开始加载所有框架资源 =======")
        with self.shared_data_lock:
            try:
                config_service = service_registry.get_service_instance('config')
                config_service.load_environment_configs(self.base_path)
                self.plugin_manager.load_all_plugins(self.pause_event)
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
        if self.is_running.is_set():
            logger.warning("调度器已经在运行中。")
            return
        logger.info("用户请求启动调度器及所有后台服务...")
        self._scheduler_thread = threading.Thread(target=self._run_scheduler_in_thread, name="SchedulerThread",
                                                  daemon=True)
        self._scheduler_thread.start()
        self._push_ui_update('master_status_update', self.get_master_status())

    def _run_scheduler_in_thread(self):
        try:
            asyncio.run(self.run())
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("调度器事件循环被取消。")
        except Exception as e:
            logger.critical(f"调度器主事件循环崩溃: {e}", exc_info=True)
        finally:
            logger.info("调度器事件循环已终止。")

    def stop_scheduler(self):
        if not self.is_running.is_set() or not self._loop:
            logger.warning("调度器已经处于停止状态。")
            return
        logger.info("用户请求停止调度器及所有后台服务...")
        if self._main_task:
            self._loop.call_soon_threadsafe(self._main_task.cancel)
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=10)
        self.execution_manager.shutdown()
        logger.info("调度器已安全停止。")
        self._push_ui_update('master_status_update', self.get_master_status())

    async def run(self):
        self.is_running.set()
        self._loop = asyncio.get_running_loop()
        self._main_task = asyncio.current_task()
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
        except asyncio.CancelledError:
            logger.info("调度器主任务被取消，正在优雅关闭...")
        finally:
            self.is_running.clear()
            self._loop = None
            self._main_task = None
            logger.info("调度器主循环 (Commander) 已安全退出。")

    async def _consume_main_task_queue(self):
        """持续从主任务队列中消费并提交任务。"""
        while True:
            tasklet = await self.task_queue.get()
            logger.debug(f"从主队列获取任务: {tasklet.task_name}")
            asyncio.create_task(self.execution_manager.submit(tasklet))
            self.task_queue.task_done()

    async def _consume_interrupt_queue(self):
        """持续从中断队列中消费并处理中断。"""
        while True:
            handler_rule = await self.interrupt_queue.get()
            rule_name = handler_rule.get('name', 'unknown_interrupt')
            logger.info(f"指挥官: 开始处理中断 '{rule_name}'...")

            # 暂停主任务
            tasks_to_cancel = []
            with self.shared_data_lock:
                # 找到所有非中断处理任务并取消它们
                for task_id, task in self.running_tasks.items():
                    if not task_id.startswith('interrupt/'):
                        tasks_to_cancel.append(task)

            for task in tasks_to_cancel:
                task.cancel()

            # 创建中断处理任务
            handler_task_id = f"interrupt/{rule_name}/{uuid.uuid4()}"
            handler_item = {'plan_name': handler_rule['plan_name'], 'task_name': handler_rule['handler_task']}

            tasklet = Tasklet(
                task_name=handler_task_id,
                payload=handler_item,
                is_ad_hoc=True,
                execution_mode='sync'  # 中断任务通常是同步的
            )

            # 直接执行中断任务
            asyncio.create_task(self.execution_manager.submit(tasklet, is_interrupt_handler=True))
            self.interrupt_queue.task_done()

    async def _event_worker_loop(self, worker_id: int):
        while True:
            tasklet = await self.event_task_queue.get()
            await self.execution_manager.submit(tasklet)
            self.event_task_queue.task_done()

    @property
    def plans(self) -> Dict[str, 'Orchestrator']:
        return self.plugin_manager.plans

    def _load_plan_specific_data(self):
        # ... (此方法内容不变, 除了日志) ...
        logger.info("--- 加载方案包特定数据 ---")
        self.schedule_items.clear()
        self.interrupt_definitions.clear()
        self.user_enabled_globals.clear()
        self.all_tasks_definitions.clear()
        config_service = service_registry.get_service_instance('config')
        for plugin_def in self.plugin_manager.plugin_registry.values():
            if plugin_def.plugin_type != 'plan': continue
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

    def _load_all_tasks_definitions(self):
        # ... (此方法内容不变, 除了日志和增加 execution_mode) ...
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
                    relative_path_str = task_file_path.relative_to(tasks_dir).with_suffix('').as_posix()
                    for task_key, task_definition in data.items():
                        if isinstance(task_definition, dict) and 'steps' in task_definition:
                            # 【新增】为任务定义设置默认执行模式
                            task_definition.setdefault('execution_mode', 'sync')
                            full_task_id = f"{plan_name}/{relative_path_str}/{task_key}"
                            self.all_tasks_definitions[full_task_id] = task_definition
                except Exception as e:
                    logger.error(f"加载任务文件 '{task_file_path}' 失败: {e}")
        logger.info(f"任务定义加载完毕，共找到 {len(self.all_tasks_definitions)} 个任务。")

    async def _subscribe_event_triggers(self):
        logger.info("--- 订阅事件触发器 ---")
        subscribed_count = 0
        for task_id, task_data in self.all_tasks_definitions.items():
            triggers = task_data.get('triggers')
            if not isinstance(triggers, list): continue
            for trigger in triggers:
                if not isinstance(trigger, dict) or 'event' not in trigger: continue
                event_pattern = trigger['event']
                plan_name = task_id.split('/')[0]
                plugin_def = self.plugin_manager.plugin_registry.get(f"plan/{plan_name}")
                if not plugin_def: continue
                channel = trigger.get('channel', plugin_def.canonical_id)
                from functools import partial
                # 使用异步 partial
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
        tasklet = Tasklet(
            task_name=task_id,
            triggering_event=event,
            execution_mode=task_def.get('execution_mode', 'sync')
        )
        await self.event_task_queue.put(tasklet)

    # ... ( _load_schedule_file 和 _load_interrupt_file 内容不变) ...
    def _load_schedule_file(self, plan_dir: Path, plan_name: str):
        # ...
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
        # ...
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
        with self.shared_data_lock:
            if item_id:
                self.run_statuses.setdefault(item_id, {}).update(status_update)
                self._push_ui_update('run_status_single_update', {
                    'id': item_id,
                    **self.run_statuses[item_id]
                })

    # --- UI API (线程安全桥接) ---
    def run_manual_task(self, task_id: str):
        with self.shared_data_lock:
            if self.run_statuses.get(task_id, {}).get('status') in ['queued', 'running']:
                return {"status": "error", "message": "Task already queued or running."}

            item_to_run = next((item for item in self.schedule_items if item.get('id') == task_id), None)
            if item_to_run:
                logger.info(f"手动触发任务 '{item_to_run.get('name', task_id)}'，已高优先级加入队列。")

                full_task_id = f"{item_to_run['plan_name']}/{item_to_run['task']}"
                task_def = self.all_tasks_definitions.get(full_task_id, {})

                tasklet = Tasklet(
                    task_name=full_task_id,
                    payload=item_to_run,
                    execution_mode=task_def.get('execution_mode', 'sync')
                )
                try:
                    self.task_queue.put_nowait(tasklet, high_priority=True)
                    self.run_statuses.setdefault(task_id, {}).update({'status': 'queued', 'queued_at': datetime.now()})
                    return {"status": "success"}
                except asyncio.QueueFull:
                    return {"status": "error", "message": "Task queue is full."}

            return {"status": "error", "message": "Task ID not found."}

    def run_ad_hoc_task(self, plan_name: str, task_name: str):
        full_task_id = f"{plan_name}/{task_name}"
        if full_task_id not in self.all_tasks_definitions:
            return {"status": "error", "message": f"Task definition '{full_task_id}' not found."}

        task_def = self.all_tasks_definitions[full_task_id]
        tasklet = Tasklet(
            task_name=full_task_id,
            is_ad_hoc=True,
            payload={'plan_name': plan_name, 'task_name': task_name},
            execution_mode=task_def.get('execution_mode', 'sync')
        )
        try:
            self.task_queue.put_nowait(tasklet)
            logger.info(f"临时任务 '{full_task_id}' 已加入执行队列。")
            return {"status": "success"}
        except asyncio.QueueFull:
            return {"status": "error", "message": "Task queue is full."}

    def get_master_status(self) -> dict:
        return {"is_running": self.is_running.is_set()}

    # ... (其他所有 get/set/UI API 方法保持不变，但需要使用 self.shared_data_lock 保护共享数据) ...
    def get_schedule_status(self):
        with self.shared_data_lock:
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
        with self.shared_data_lock:
            return list(self.plans.keys())

        # 请将此方法添加到 packages/aura_core/scheduler.py 的 Scheduler 类中

    def get_plan_files(self, plan_name: str) -> Dict[str, Any]:
        """
        扫描指定plan的目录，并返回一个表示文件/文件夹结构的嵌套字典。
        【修正版】: 此版本直接使用 base_path 构建路径，不再依赖 PluginManager 的状态。
        """
        logger.debug(f"请求获取 '{plan_name}' 的文件树...")

        # 直接、可靠地构建 plan 的路径
        plan_path = self.base_path / 'plans' / plan_name

        if not plan_path.is_dir():
            # 如果 plan 目录本身就不存在，则抛出清晰的错误
            error_msg = f"Plan directory not found for plan '{plan_name}' at path: {plan_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        tree = {}
        # 使用 rglob 递归遍历所有文件和文件夹
        for path in sorted(plan_path.rglob('*')):
            # 忽略 .git, __pycache__ 等常见忽略目录
            if any(part in ['.git', '__pycache__', '.idea'] for part in path.parts):
                continue

            # 获取相对于 plan 根目录的路径部分
            relative_parts = path.relative_to(plan_path).parts

            current_level = tree
            # 遍历路径的每一部分，在字典中创建嵌套结构
            for part in relative_parts[:-1]:
                current_level = current_level.setdefault(part, {})

            # 处理路径的最后一部分（文件名或空目录名）
            final_part = relative_parts[-1]
            if path.is_file():
                current_level[final_part] = None  # 文件用 None 表示
            elif path.is_dir() and not any(path.iterdir()):
                # 仅当目录为空时才显式添加，否则它会作为父级自动存在
                current_level.setdefault(final_part, {})

        logger.debug(f"为 '{plan_name}' 构建的文件树: {tree}")
        return tree

    def get_tasks_for_plan(self, plan_name: str) -> List[str]:
        with self.shared_data_lock:
            tasks = []
            prefix = f"{plan_name}/"
            for task_id in self.all_tasks_definitions.keys():
                if task_id.startswith(prefix):
                    tasks.append(task_id[len(prefix):])
            return sorted(tasks)

    def get_all_services_status(self) -> List[Dict[str, Any]]:
        with self.shared_data_lock:
            return service_registry.get_all_service_definitions()

    def get_all_interrupts_status(self) -> List[Dict[str, Any]]:
        with self.shared_data_lock:
            status_list = []
            for name, definition in self.interrupt_definitions.items():
                status_item = definition.copy()
                status_item['is_global_enabled'] = name in self.user_enabled_globals
                status_list.append(status_item)
            return status_list

    def get_all_services_for_api(self) -> List[Dict[str, Any]]:
        """
        获取所有服务的状态，并将其格式化为适合API返回的、
        可JSON序列化的字典列表。
        这个返回的结构应该与 api_server.py 中定义的 ServiceInfoModel 匹配。
        """
        with self.shared_data_lock:
            original_services = service_registry.get_all_service_definitions()

        api_safe_services = []
        for service_def in original_services:
            # 安全地提取类信息
            class_info = {'module': None, 'name': None}
            if hasattr(service_def.service_class, '__module__') and hasattr(service_def.service_class, '__name__'):
                class_info['module'] = service_def.service_class.__module__
                class_info['name'] = service_def.service_class.__name__

            # 安全地提取插件信息（简化为字典）
            plugin_info = None
            if service_def.plugin:
                plugin_info = {
                    'name': service_def.plugin.name,
                    'canonical_id': service_def.plugin.canonical_id,
                    'version': service_def.plugin.version,
                    'plugin_type': service_def.plugin.plugin_type
                }

            api_safe_services.append({
                "alias": service_def.alias,
                "fqid": service_def.fqid,
                "status": service_def.status,
                "public": service_def.public,
                "service_class_info": class_info,
                "plugin": plugin_info
            })
        return api_safe_services




    def get_file_content(self, plan_name: str, relative_path: str) -> str:
        file_path = self.base_path / 'plans' / plan_name / relative_path
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()

    def get_file_content_bytes(self, plan_name: str, relative_path: str) -> bytes:
        file_path = self.base_path / 'plans' / plan_name / relative_path
        with open(file_path, 'rb') as f:
            return f.read()

    def save_file_content(self, plan_name: str, relative_path: str, content: str):
        file_path = self.base_path / 'plans' / plan_name / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"文件已保存: {relative_path}")

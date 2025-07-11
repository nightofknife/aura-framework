# packages/aura_core/scheduler.py (最终版 v4)

import threading
import time
import yaml
from collections import deque
from datetime import datetime
from pathlib import Path
import uuid
from typing import TYPE_CHECKING, Dict, Any, List, Optional
import queue

# 【修改】导入所有核心服务
from .plugin_manager import PluginManager
from .execution_manager import ExecutionManager
from .scheduling_service import SchedulingService
from .interrupt_service import InterruptService

from packages.aura_core.api import service_registry, ACTION_REGISTRY, hook_manager
from packages.aura_shared_utils.utils.logger import logger
from packages.aura_core.state_store import StateStore
from packages.aura_core.event_bus import EventBus, Event
from packages.aura_core.task_queue import TaskQueue, Tasklet

if TYPE_CHECKING:
    from packages.aura_core.orchestrator import Orchestrator


class Scheduler:
    """
    【最终重构版】Aura 框架的核心服务门面 (Facade) 与总指挥。
    职责：
    1. 初始化并协调框架内的所有核心服务。
    2. 管理主循环 (Commander)，作为任务和中断的最终消费者与协调者。
    3. 管理中断处理的善后逻辑。
    4. 为UI和其他外部组件提供一个稳定、高级的API。
    """

    def __init__(self):
        # --- 核心属性与状态 ---
        self.base_path = Path(__file__).resolve().parents[2]
        self.is_scheduler_running = threading.Event()
        self.pause_event = threading.Event()
        self.lock = threading.RLock()

        # --- 核心服务实例 ---
        self.state_store = StateStore()
        self.event_bus = EventBus()
        self.plugin_manager = PluginManager(self.base_path)
        self.execution_manager = ExecutionManager(self)
        self.scheduling_service = SchedulingService(self)
        # 【新增】持有 InterruptService 实例
        self.interrupt_service = InterruptService(self)

        # --- 任务与执行状态 ---
        self.task_queue = TaskQueue()
        self.event_task_queue = TaskQueue()
        self.interrupt_queue: deque = deque()
        self.run_statuses: Dict[str, Dict[str, Any]] = {}

        # --- 全局状态 (由其对应服务主要管理，但Scheduler仍需引用) ---
        self.current_running_task: Optional[Dict[str, Any]] = None
        self.current_running_thread: Optional[threading.Thread] = None
        self.interrupted_main_task: Optional[Dict[str, Any]] = None
        self.is_device_busy: bool = False

        # --- 配置与定义 (由PluginManager/Scheduler加载，供所有服务使用) ---
        self.schedule_items: List[Dict[str, Any]] = []
        self.interrupt_definitions: Dict[str, Dict[str, Any]] = {}
        self.user_enabled_globals: set[str] = set()
        self.interrupt_last_check_times: Dict[str, datetime] = {}
        self.interrupt_cooldown_until: Dict[str, datetime] = {}
        self.all_tasks_definitions: Dict[str, Any] = {}

        # --- 线程与工作者 ---
        self.scheduler_thread: Optional[threading.Thread] = None
        self.event_worker_threads: List[threading.Thread] = []
        self.num_event_workers = 2

        # --- UI 通信 ---
        self.ui_event_queue = queue.Queue(maxsize=200)

        # --- 初始化流程 ---
        self._register_core_services()
        self.reload_plans()

    def _register_core_services(self):
        """注册框架自身提供的核心服务。"""
        from plans.aura_base.services.config_service import ConfigService
        from packages.aura_core.builder import set_project_base_path

        set_project_base_path(self.base_path)
        service_registry.register_instance('config', ConfigService(), public=True, fqid='core/config')
        service_registry.register_instance('state_store', self.state_store, public=True, fqid='core/state_store')
        service_registry.register_instance('event_bus', self.event_bus, public=True, fqid='core/event_bus')
        service_registry.register_instance('scheduler', self, public=True, fqid='core/scheduler')
        # 注册所有后台服务
        service_registry.register_instance('plugin_manager', self.plugin_manager, public=False,
                                           fqid='core/plugin_manager')
        service_registry.register_instance('execution_manager', self.execution_manager, public=False,
                                           fqid='core/execution_manager')
        service_registry.register_instance('scheduling_service', self.scheduling_service, public=False,
                                           fqid='core/scheduling_service')
        service_registry.register_instance('interrupt_service', self.interrupt_service, public=False,
                                           fqid='core/interrupt_service')
        logger.debug("全局核心服务注册完毕。")

    def reload_plans(self):
        logger.info("======= Scheduler: 开始加载所有框架资源 =======")
        with self.lock:
            try:
                config_service = service_registry.get_service_instance('config')
                config_service.load_environment_configs(self.base_path)

                # 【修正】PluginManager 加载时需要 pause_event
                # 这是解耦的关键一步，Scheduler 将自己的 pause_event 注入给 PluginManager
                # PluginManager 再将其传递给 Orchestrator，避免了循环引用
                self.plugin_manager.load_all_plugins(self.pause_event)

                # 【移除】不再需要手动 set_scheduler，因为 Orchestrator 已经解耦
                # for orchestrator in self.plugin_manager.plans.values():
                #     orchestrator.set_scheduler(self)

                self._load_plan_specific_data()
                self.event_bus.clear_subscriptions()
                self.event_bus.subscribe(event_pattern='*', callback=self._mirror_event_to_ui_queue, channel='*')
                self._subscribe_event_triggers()
            except Exception as e:
                logger.critical(f"框架资源加载失败: {e}", exc_info=True)
                raise
        logger.info(f"======= 资源加载完毕 (服务: {len(service_registry.get_all_service_definitions())}, "
                    f"行为: {len(ACTION_REGISTRY)}, 方案包: {len(self.plans)}, 任务: {len(self.all_tasks_definitions)}) =======")

    # --- 启动/停止调度器及所有子服务 ---
    def start_scheduler(self):
        if self.is_scheduler_running.is_set():
            logger.warning("调度器已经在运行中。")
            return
        logger.info("用户请求启动调度器及所有后台服务...")
        self.is_scheduler_running.set()

        # 【修改】启动所有后台服务
        self.scheduling_service.start()
        self.interrupt_service.start()
        self._start_event_workers()

        self.scheduler_thread = threading.Thread(target=self._commander_loop, name="CommanderThread", daemon=True)
        self.scheduler_thread.start()

    def stop_scheduler(self):
        if not self.is_scheduler_running.is_set():
            logger.warning("调度器已经处于停止状态。")
            return
        logger.info("用户请求停止调度器及所有后台服务...")
        self.is_scheduler_running.clear()

        # 【修改】停止所有后台服务
        self.scheduling_service.stop()
        self.interrupt_service.stop()

        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=5)
        for worker in self.event_worker_threads:
            if worker.is_alive():
                worker.join(timeout=5)
        logger.info("调度器已安全停止。")

    # --- 主循环与工作者 ---
    def _commander_loop(self):
        """【最终版】任务调度器的主循环，只负责消费队列和决策。"""
        logger.info("任务调度器线程 (Commander) 已启动...")

        while self.is_scheduler_running.is_set():
            handler_rule = None
            tasklet_to_run = None

            with self.lock:
                if self.interrupt_queue:
                    handler_rule = self.interrupt_queue.popleft()
                elif not self.task_queue.empty() and not self.is_device_busy:
                    tasklet_to_run = self.task_queue.get()

            if handler_rule:
                self._execute_handler_task(handler_rule)
                continue

            if tasklet_to_run:
                self._execute_main_task(tasklet_to_run.payload)

            time.sleep(0.5)
        logger.info("调度器主循环 (Commander) 已安全退出。")

    def _start_event_workers(self):
        """只负责启动事件工作者线程。"""
        self.event_worker_threads.clear()
        for i in range(self.num_event_workers):
            worker = threading.Thread(target=self._event_worker_loop, args=(i + 1,), daemon=True)
            self.event_worker_threads.append(worker)
            worker.start()
        logger.info("事件工作者已启动。")

    # 【移除】所有与 Guardian 相关的私有方法
    # _guardian_loop, _get_active_interrupts, _should_check_interrupt, _submit_interrupt
    # 这些方法已经全部迁移到 InterruptService 中。

    # --- 【以下是所有其他方法的代码，大部分保持不变】 ---
    # ... (在你的文件中，请保留这些方法的原始代码) ...
    def get_master_status(self) -> dict:
        return {"is_running": self.is_scheduler_running.is_set()}

    def _execute_main_task(self, item_to_run: Dict[str, Any]):
        with self.lock:
            if self.is_device_busy:
                logger.warning(f"尝试执行主任务 {item_to_run.get('id')} 时发现设备已忙，放回队列。")
                # 【修正】使用正确的 Tasklet 构造函数
                tasklet = Tasklet(task_name=item_to_run.get('id'), payload=item_to_run)
                self.task_queue.put(tasklet)
                return
        self.execution_manager.execute_task(item_to_run, is_handler=False)

    def _execute_handler_task(self, handler_rule: Dict[str, Any]):
        rule_name = handler_rule.get('name', 'unknown_interrupt')
        logger.info(f"指挥官: 开始处理中断 '{rule_name}'...")
        with self.lock:
            if self.current_running_task:
                logger.info(f"指挥官: 命令主任务 '{self.current_running_task.get('name', 'N/A')}' 暂停。")
                self.pause_event.set()
                self.interrupted_main_task = self.current_running_task
        handler_item = {'plan_name': handler_rule['plan_name'], 'task_name': handler_rule['handler_task'],
                        'is_ad_hoc': True}
        self.execution_manager.execute_task(handler_item, is_handler=True, handler_rule=handler_rule)

    @property
    def plans(self) -> Dict[str, 'Orchestrator']:
        return self.plugin_manager.plans

    @property
    def services(self):
        return service_registry

    @property
    def actions(self):
        return ACTION_REGISTRY

    @property
    def hooks(self):
        return hook_manager

    def _load_plan_specific_data(self):
        logger.info("--- 阶段4: 加载方案包特定数据 ---")
        self.schedule_items.clear()
        self.interrupt_definitions.clear()
        self.user_enabled_globals.clear()
        self.all_tasks_definitions.clear()
        try:
            config_service = service_registry.get_service_instance('config')
        except Exception as e:
            logger.error(f"无法获取 ConfigService 实例: {e}")
            return
        for plugin_def in self.plugin_manager.plugin_registry.values():
            if plugin_def.plugin_type != 'plan': continue
            plan_name = plugin_def.path.name
            config_path = plugin_def.path / 'config.yaml'
            config_data = {}
            if config_path.is_file():
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = yaml.safe_load(f) or {}
                except Exception as e:
                    logger.error(f"加载配置文件 '{config_path}' 失败: {e}")
            config_service.register_plan_config(plan_name, config_data)
            self._load_schedule_file(plugin_def.path, plan_name)
            self._load_interrupt_file(plugin_def.path, plan_name)
        self._load_all_tasks_definitions()

    def _load_all_tasks_definitions(self):
        """
        【修正版】加载所有方案包中的所有任务定义。
        修正了对多任务格式文件 (一个文件包含多个任务) 的ID构建逻辑。
        """
        logger.info("--- 阶段 4.5: 加载所有任务定义 ---")
        self.all_tasks_definitions.clear()

        plans_dir = self.base_path / 'plans'
        if not plans_dir.is_dir():
            return

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

                    # 使用 as_posix() 来确保在 Windows 和 Linux 上路径分隔符一致
                    relative_path_str = task_file_path.relative_to(tasks_dir).with_suffix('').as_posix()

                    # 遍历文件中的所有顶层键
                    for task_key, task_definition in data.items():
                        if isinstance(task_definition, dict) and 'steps' in task_definition:
                            # 【修正】任务ID现在是 文件路径 + 任务键
                            # 例如: 'quests/daily.yaml' 中的 'main' 任务
                            # ID 将是 'MyPlan/quests/daily/main'
                            full_task_id = f"{plan_name}/{relative_path_str}/{task_key}"
                            self.all_tasks_definitions[full_task_id] = task_definition

                except Exception as e:
                    logger.error(f"加载任务文件 '{task_file_path}' 失败: {e}")

        logger.info(f"任务定义加载完毕，共找到 {len(self.all_tasks_definitions)} 个任务。")

    def _subscribe_event_triggers(self):
        logger.info("--- 阶段4.6: 订阅事件触发器 ---")
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
                callback = partial(self._handle_event_triggered_task, task_id=task_id)
                callback.__name__ = f"event_trigger_for_{task_id.replace('/', '_')}"
                self.event_bus.subscribe(event_pattern, callback, channel=channel)
                subscribed_count += 1
        logger.info(f"事件触发器订阅完成，共 {subscribed_count} 个订阅。")

    def _handle_event_triggered_task(self, event: Event, task_id: str):
        logger.info(f"事件 '{event.name}' (频道: {event.channel}) 触发了任务 '{task_id}'")
        # 【修正】使用正确的 Tasklet 构造函数
        tasklet = Tasklet(task_name=task_id, triggering_event=event)
        self.event_task_queue.put(tasklet)
    def _event_worker_loop(self, worker_id: int):
        logger.info(f"[EventWorker-{worker_id}] 事件工作线程已启动")
        while self.is_scheduler_running.is_set():
            try:
                # 【修正】从 PriorityQueue 获取的是 Tasklet 对象
                tasklet = self.event_task_queue.get(block=True, timeout=1)
                plan_name, task_name = tasklet.task_name.split('/', 1)
                logger.info(f"[EventWorker-{worker_id}] 执行事件触发的任务: '{tasklet.task_name}'")
                if plan_name in self.plans:
                    self.plans[plan_name].execute_task(task_name, tasklet.triggering_event)
                else:
                    logger.error(f"找不到方案 '{plan_name}' 的Orchestrator")
                self.event_task_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[EventWorker-{worker_id}] 处理事件任务时出错: {e}", exc_info=True)
        logger.info(f"[EventWorker-{worker_id}] 事件工作线程已停止")

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

    def _post_interrupt_handling(self, handler_rule: Dict):
        with self.lock:
            strategy = handler_rule.get('on_complete', 'resume')
            logger.info(f"指挥官: 中断处理完毕，执行善后策略: '{strategy}'")
            if self.interrupted_main_task:
                if strategy == 'resume':
                    logger.info(f"指挥官: 命令主任务 '{self.interrupted_main_task.get('name', 'N/A')}' 继续执行。")
                    self.pause_event.clear()
                elif strategy == 'restart_task':
                    logger.warning(f"指挥官: 策略为重启，原任务 '{self.interrupted_main_task.get('name', 'N/A')}' 将被放弃并重新入队。")
                    # 【修正】使用正确的 Tasklet 构造函数和 put 方法
                    tasklet = Tasklet(
                        task_name=self.interrupted_main_task['id'],
                        payload=self.interrupted_main_task
                    )
                    self.task_queue.put(tasklet, high_priority=True)
                    self.pause_event.clear()
            self.interrupted_main_task = None

    def run_manual_task(self, task_id: str):
        """
        【修正版】手动运行一个在 schedule.yaml 中定义的任务。
        这里的 task_id 是 schedule item 的 id，不是任务文件名。
        """
        with self.lock:
            if self.run_statuses.get(task_id, {}).get('status') in ['queued', 'running']:
                return {"status": "error", "message": "Task already queued or running."}

            item_to_run = next((item for item in self.schedule_items if item.get('id') == task_id), None)
            if item_to_run:
                logger.info(f"手动触发任务 '{item_to_run.get('name', task_id)}'，已高优先级加入队列。")

                # 【修正】这里的 payload 应该是整个 schedule item
                tasklet = Tasklet(task_name=item_to_run.get('task'), payload=item_to_run)
                self.task_queue.put(tasklet, high_priority=True)
                self.run_statuses.setdefault(task_id, {}).update({'status': 'queued', 'queued_at': datetime.now()})
                return {"status": "success"}

            return {"status": "error", "message": "Task ID not found."}

    def run_ad_hoc_task(self, plan_name: str, task_name: str):
        """
        【修正版】运行一个临时的、不在 schedule.yaml 中的任务。
        这里的 task_name 应该是完整的任务ID，例如 'quests/daily/main'。
        """
        if plan_name not in self.plans:
            return {"status": "error", "message": f"Plan '{plan_name}' not found."}

        # 【修正】这里的 task_name 已经是方案内的完整路径，直接拼接即可
        full_task_id = f"{plan_name}/{task_name}"

        # 验证任务是否存在于全局定义中
        if full_task_id not in self.all_tasks_definitions:
            logger.error(f"临时任务请求失败: 找不到任务定义 '{full_task_id}'")
            return {"status": "error", "message": f"Task definition '{full_task_id}' not found."}

        tasklet = Tasklet(
            task_name=full_task_id,
            is_ad_hoc=True,
            # payload 应该包含执行所需的最少信息
            payload={'plan_name': plan_name, 'task_name': task_name}
        )
        self.task_queue.put(tasklet)
        logger.info(f"临时任务 '{full_task_id}' 已加入执行队列。")
        return {"status": "success"}

    # ... (所有 get_*, save_*, UI API 方法等保持不变) ...
    def enable_global_interrupt(self, name: str):
        with self.lock:
            if name in self.interrupt_definitions and self.interrupt_definitions[name].get('scope') == 'global':
                self.user_enabled_globals.add(name)
                logger.info(f"UI: 已启用全局中断 '{name}'")

    def disable_global_interrupt(self, name: str):
        with self.lock:
            self.user_enabled_globals.discard(name)
            logger.info(f"UI: 已禁用全局中断 '{name}'")

    def get_all_interrupts_status(self) -> List[Dict[str, Any]]:
        with self.lock:
            status_list = []
            active_interrupts_snapshot = self.interrupt_service._get_active_interrupts() if self.interrupt_service.is_running.is_set() else set()
            for name, rule in self.interrupt_definitions.items():
                status = rule.copy()
                status['enabled'] = name in self.user_enabled_globals if status.get(
                    'scope') == 'global' else name in active_interrupts_snapshot
                status_list.append(status)
        return sorted(status_list, key=lambda x: (x.get('scope', ''), x.get('name', '')))

    def get_schedule_status(self):
        with self.lock:
            schedule_items_copy = list(self.schedule_items)
            run_statuses_copy = dict(self.run_statuses)
        status_list = []
        for item in schedule_items_copy:
            full_status = item.copy()
            full_status.update(run_statuses_copy.get(item.get('id'), {}))
            status_list.append(full_status)
        return status_list

    def _save_schedule_for_plan(self, plan_name: str):
        with self.lock:
            plan_items = [item for item in self.schedule_items if item.get('plan_name') == plan_name]
        items_to_save = [{k: v for k, v in item.items() if k != 'plan_name'} for item in plan_items]
        schedule_path = self.base_path / f"plans/{plan_name}/schedule.yaml"
        try:
            with open(schedule_path, 'w', encoding='utf-8') as f:
                yaml.dump(items_to_save, f, allow_unicode=True, sort_keys=False)
            logger.info(f"已更新调度文件: {schedule_path}")
        except Exception as e:
            logger.error(f"保存调度文件 '{schedule_path}' 失败: {e}")

    def toggle_task_enabled(self, task_id: str, enabled: bool):
        with self.lock:
            item_to_update = next((item for item in self.schedule_items if item.get('id') == task_id), None)
            if not item_to_update: return {"status": "error", "message": f"Task ID {task_id} not found."}
            item_to_update['enabled'] = enabled
            plan_name_to_save = item_to_update.get('plan_name')
            if plan_name_to_save:
                self._save_schedule_for_plan(plan_name_to_save)
                logger.info(f"任务 '{item_to_update.get('name', task_id)}' 已被 {'启用' if enabled else '禁用'}.")
                return {"status": "success", "message": f"Task {task_id} updated."}
            return {"status": "error", "message": f"Task {task_id} missing plan_name."}

    def get_all_plans(self) -> list[str]:
        return sorted(list(self.plans.keys()))

    def get_tasks_for_plan(self, plan_name: str) -> list[str]:
        return sorted([tid.split('/', 1)[1] for tid in self.all_tasks_definitions if tid.startswith(f"{plan_name}/")])

    def get_persistent_context(self, plan_name: str) -> dict:
        orchestrator = self.plans.get(plan_name)
        if not orchestrator: raise ValueError(f"Plan '{plan_name}' not found.")
        return orchestrator.get_persistent_context_data()

    def save_persistent_context(self, plan_name: str, data: dict):
        orchestrator = self.plans.get(plan_name)
        if not orchestrator: raise ValueError(f"Plan '{plan_name}' not found.")
        orchestrator.save_persistent_context_data(data)

    def get_plan_files(self, plan_name: str) -> dict:
        if plan_name not in self.plans: return {}
        plan_path = self.base_path / f"plans/{plan_name}"

        def recurse_path(current_path: Path) -> dict:
            structure = {}
            for item in sorted(current_path.iterdir(), key=lambda p: (p.is_file(), p.name)):
                if item.name.startswith('.') or item.name == '__pycache__': continue
                if item.is_dir():
                    structure[item.name] = recurse_path(item)
                else:
                    structure[item.name] = 'file'
            return structure

        return recurse_path(plan_path)

    def get_file_content(self, plan_name: str, file_path: str) -> str:
        orchestrator = self.plans.get(plan_name)
        if not orchestrator: raise ValueError(f"Plan '{plan_name}' not found.")
        return orchestrator.get_file_content(file_path)

    def get_file_content_bytes(self, plan_name: str, file_path: str) -> bytes:
        orchestrator = self.plans.get(plan_name)
        if not orchestrator: raise ValueError(f"Plan '{plan_name}' not found.")
        return orchestrator.get_file_content_bytes(file_path)

    def save_file_content(self, plan_name: str, file_path: str, content: str):
        orchestrator = self.plans.get(plan_name)
        if not orchestrator: raise ValueError(f"Plan '{plan_name}' not found.")
        orchestrator.save_file_content(file_path, content)

    def get_available_actions(self) -> dict:
        return {name: defn.docstring for name, defn in ACTION_REGISTRY.items()}

    def get_all_actions_with_signatures(self) -> Dict[str, Dict[str, Any]]:
        actions_with_sigs = {}
        for action_def in sorted(ACTION_REGISTRY.get_all_action_definitions(), key=lambda a: a.name):
            actions_with_sigs[action_def.name] = self.get_action_signature(action_def.name)
        return actions_with_sigs

    def get_action_signature(self, action_name: str) -> Optional[Dict[str, Any]]:
        action_def = ACTION_REGISTRY.get(action_name)
        if not action_def: return None
        from inspect import Parameter
        sig = action_def.signature
        params_info = []
        excluded_params = {'self', 'context', 'persistent_context', 'engine'}
        for param_name, param_spec in sig.parameters.items():
            if param_name in excluded_params or param_name in action_def.service_deps: continue
            params_info.append({'name': param_name, 'type': str(
                param_spec.annotation) if param_spec.annotation != Parameter.empty else 'Any',
                                'has_default': param_spec.default != Parameter.empty,
                                'default_value': param_spec.default if param_spec.default != Parameter.empty else None})
        return {'name': action_def.name, 'docstring': action_def.docstring, 'parameters': params_info}

    def get_all_services_status(self) -> List[Dict[str, Any]]:
        definitions = service_registry.get_all_service_definitions()
        status_list = []
        for s_def in definitions:
            plugin_info = {'canonical_id': s_def.plugin.canonical_id,
                           'path': str(s_def.plugin.path)} if s_def.plugin else {'canonical_id': 'core/framework',
                                                                                 'path': 'N/A'}
            status_list.append(
                {'fqid': s_def.fqid, 'alias': s_def.alias, 'status': s_def.status, 'public': s_def.public,
                 'is_extension': s_def.is_extension, 'parent_fqid': s_def.parent_fqid, 'plugin': plugin_info,
                 'service_class': {'name': s_def.service_class.__name__, 'module': s_def.service_class.__module__}})
        return status_list

    def add_schedule_item(self, data: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            plan_name = data.get('plan_name')
            if not plan_name: raise ValueError("添加调度项时必须提供 'plan_name'。")
            new_item = {'id': str(uuid.uuid4()), 'name': data.get('name', '未命名任务'),
                        'description': data.get('description', ''), 'enabled': data.get('enabled', True),
                        'plan_name': plan_name, 'task': data.get('task'),
                        'trigger': data.get('trigger', {'type': 'manual'}), 'run_options': data.get('run_options', {})}
            self.schedule_items.append(new_item)
            self.run_statuses[new_item['id']] = {'status': 'idle'}
            self._save_schedule_for_plan(plan_name)
            logger.info(f"已添加新调度任务: '{new_item['name']}' (ID: {new_item['id']})")
            return {"status": "success", "new_item": new_item}

    def update_schedule_item(self, item_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            item_to_update = next((item for item in self.schedule_items if item.get('id') == item_id), None)
            if not item_to_update: raise ValueError(f"找不到ID为 '{item_id}' 的调度项。")
            item_to_update.update(data)
            plan_name = item_to_update.get('plan_name')
            if plan_name: self._save_schedule_for_plan(plan_name)
            logger.info(f"已更新调度任务: '{item_to_update['name']}' (ID: {item_id})")
            return {"status": "success", "updated_item": item_to_update}

    def delete_schedule_item(self, item_id: str) -> Dict[str, Any]:
        with self.lock:
            item_to_delete = next((item for item in self.schedule_items if item.get('id') == item_id), None)
            if not item_to_delete: raise ValueError(f"找不到ID为 '{item_id}' 的调度项。")
            self.schedule_items.remove(item_to_delete)
            self.run_statuses.pop(item_id, None)
            plan_name_to_save = item_to_delete.get('plan_name')
            if plan_name_to_save: self._save_schedule_for_plan(plan_name_to_save)
            logger.info(f"已删除调度任务: '{item_to_delete.get('name')}' (ID: {item_id})")
            return {"status": "success", "deleted_id": item_id}

    def inspect_step(self, plan_name: str, task_path: str, step_index: int) -> Any:
        if plan_name not in self.plans: raise ValueError(f"找不到方案包 '{plan_name}'。")
        orchestrator = self.plans[plan_name]
        task_name = Path(task_path).relative_to('tasks').with_suffix('').as_posix()
        try:
            return orchestrator.inspect_step(task_name, step_index)
        except Exception as e:
            logger.error(f"调用 inspect_step API 时失败: {e}"); raise

    def publish_event_manually(self, event_name: str, payload: dict = None, source: str = "manual",
                               channel: str = "global") -> dict:
        try:
            event = Event(name=event_name, channel=channel, payload=payload or {}, source=source)
            self.event_bus.publish(event)
            return {"status": "success", "message": f"Event '{event_name}' on channel '{channel}' published."}
        except Exception as e:
            logger.error(f"手动发布事件失败: {e}", exc_info=True); return {"status": "error", "message": str(e)}

    def get_event_system_status(self) -> dict:
        # 【修正】调用正确的 qsize 方法
        return {
            "event_queue_size": self.event_task_queue.qsize(),
            "total_tasks": len(self.all_tasks_definitions),
            "event_workers": len(self.event_worker_threads),
            "event_workers_alive": sum(1 for t in self.event_worker_threads if t.is_alive())
        }
    def get_event_bus(self) -> EventBus:
        return self.event_bus

    def _mirror_event_to_ui_queue(self, event: Event):
        if self.ui_event_queue.full():
            try:
                self.ui_event_queue.get_nowait()
            except queue.Empty:
                pass
        self.ui_event_queue.put(
            {"name": event.name, "channel": event.channel, "payload": event.payload, "source": event.source,
             "id": event.id, "timestamp": event.timestamp, "causation_chain": event.causation_chain,
             "depth": event.depth})

    def get_ui_event_queue(self) -> queue.Queue:
        return self.ui_event_queue

    def update_task_in_file(self, plan_name: str, file_path: str, task_name: str, task_data: Dict[str, Any]):
        """
        【修正版】更新 YAML 文件中的任务定义。
        """
        orchestrator = self.plans.get(plan_name)
        if not orchestrator:
            raise ValueError(f"Plan '{plan_name}' not found.")

        # 【修正】使用 orchestrator.current_plan_path 而不是不存在的 orchestrator.base_path
        full_path = orchestrator.current_plan_path / file_path

        if not full_path.is_file():
            raise FileNotFoundError(f"File not found: {full_path}")

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                all_tasks_data = yaml.safe_load(f) or {}

            if not isinstance(all_tasks_data, dict):
                raise TypeError("Task file is not a valid dictionary.")

            all_tasks_data[task_name] = task_data

            with open(full_path, 'w', encoding='utf-8') as f:
                yaml.dump(all_tasks_data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

            logger.info(f"已在文件 '{file_path}' 中更新任务 '{task_name}'。")

            # 更新内存中的任务定义缓存
            full_task_id = f"{plan_name}/{task_name}"
            self.all_tasks_definitions[full_task_id] = task_data

            # 【可选但推荐】清除对应 Orchestrator 的 TaskLoader 缓存，以便下次能加载新内容
            if hasattr(orchestrator, 'task_loader') and hasattr(orchestrator.task_loader, 'cache'):
                orchestrator.task_loader.cache.clear()
                logger.debug(f"已清除方案 '{plan_name}' 的任务加载器缓存。")

        except Exception as e:
            logger.error(f"更新任务文件 '{full_path}' 失败: {e}", exc_info=True)
            raise

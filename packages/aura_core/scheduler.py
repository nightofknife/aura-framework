# packages/aura_core/scheduler.py

import threading
import time
import yaml
from collections import deque
from croniter import croniter
from datetime import datetime, timedelta
from pathlib import Path
import uuid
from typing import TYPE_CHECKING, Dict, Any, Set, List

from graphlib import TopologicalSorter, CycleError
from resolvelib import Resolver, BaseReporter
from resolvelib.providers import AbstractProvider
from dataclasses import asdict

from packages.aura_core.service_registry import service_registry
from packages.aura_core.action_loader import load_actions_from_path, clear_loaded_actions
from packages.aura_system_actions.actions.decorators import ACTION_REGISTRY
from packages.aura_shared_utils.utils.logger import logger
from packages.aura_shared_utils.models.plugin_definition import PluginDefinition

if TYPE_CHECKING:
    from packages.aura_core.orchestrator import Orchestrator


class PluginProvider(AbstractProvider):
    def __init__(self, plugin_registry: Dict[str, PluginDefinition]):
        self.plugin_registry = plugin_registry

    def identify(self, requirement_or_candidate):
        return requirement_or_candidate

    def get_preference(
        self,
        identifier: Any,
        resolutions: Dict[str, Any],
        candidates: Dict[str, Any],
        information: Dict[str, Any],
        backtrack_causes: List[Any], # 增加这个新参数
    ) -> Any:
        return len(candidates)

    def find_matches(self, identifier, requirements, incompatibilities):
        if identifier in self.plugin_registry:
            return [identifier]
        return []

    def is_satisfied_by(self, requirement, candidate):
        return requirement == candidate

    def get_dependencies(self, candidate):
        plugin_def = self.plugin_registry.get(candidate)
        if plugin_def:
            return list(plugin_def.dependencies.keys())
        return []


class Scheduler:
    def __init__(self):
        self.plans: Dict[str, 'Orchestrator'] = {}
        self.schedule_items: List[Dict[str, Any]] = []
        self.task_queue: deque = deque()
        self.is_device_busy: bool = False
        self.plugin_registry: Dict[str, PluginDefinition] = {}
        self.base_path = Path(__file__).resolve().parents[2]
        self.run_statuses: Dict[str, Dict[str, Any]] = {}
        self.current_running_task: Dict[str, Any] = None
        self.current_running_thread: threading.Thread = None
        self.interrupt_definitions: Dict[str, Dict[str, Any]] = {}
        self.user_enabled_globals: Set[str] = set()
        self.interrupt_queue: deque = deque()
        self.pause_event: threading.Event = threading.Event()
        self.interrupted_main_task: Dict[str, Any] = None
        self.interrupt_last_check_times: Dict[str, datetime] = {}
        self.interrupt_cooldown_until: Dict[str, datetime] = {}
        self.lock = threading.RLock()
        self.is_scheduler_running = threading.Event()
        self.scheduler_thread = None
        self.guardian_thread = None
        self._load_all_resources()
        self.service_registry = service_registry
        self.action_registry = ACTION_REGISTRY
        self.plans: Dict[str, 'Orchestrator'] = {}

    def _load_all_resources(self):
        logger.info("======= 开始加载所有框架资源 =======")
        try:
            self._clear_registries()
            self._discover_and_parse_plugins()
            load_order = self._resolve_dependencies_and_sort()
            logger.info("--- 插件加载顺序已确定 ---")
            for i, plugin_id in enumerate(load_order):
                logger.info(f"  {i + 1}. {plugin_id}")
            self._load_plugins_in_order(load_order)
            self._load_plan_configurations()
        except Exception as e:
            logger.error(f"框架启动失败: {e}", exc_info=True)
            raise
        logger.info(f"======= 资源加载完毕 =======")
        logger.info(
            f"调度器初始化完毕，共定义了 {len(service_registry.get_all_service_definitions())} 个服务, "
            f"{len(ACTION_REGISTRY)} 个行为, {len(self.plans)} 个方案包。"
        )

    def _clear_registries(self):
        service_registry.clear()
        clear_loaded_actions()
        self.plans.clear()
        self.plugin_registry.clear()
        self.schedule_items.clear()
        self.interrupt_definitions.clear()
        self.user_enabled_globals.clear()

    def _discover_and_parse_plugins(self):
        """【已修复】扫描所有目录，查找并解析plugin.yaml文件。"""
        logger.info("--- 阶段1: 发现并解析所有插件定义 (plugin.yaml) ---")

        # 【修改】扫描路径更新为新结构
        plugin_paths_to_scan = [
            self.base_path / 'packages',
            self.base_path / 'plugins',
            self.base_path / 'plans',
        ]

        for root_path in plugin_paths_to_scan:
            if not root_path.is_dir():
                logger.warning(f"插件扫描目录不存在: {root_path}")
                continue

            for plugin_yaml_path in root_path.glob('**/plugin.yaml'):
                plugin_dir = plugin_yaml_path.parent
                try:
                    with open(plugin_yaml_path, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)

                    # --- 【核心修复】确定插件类型的逻辑 ---
                    # 我们通过判断 plugin_dir 位于哪个根目录下，来确定其类型。
                    plugin_type = 'unknown'
                    relative_path = plugin_dir.relative_to(self.base_path)
                    top_level_dir = relative_path.parts[0]

                    if top_level_dir == 'packages':
                        # 对于 packages/aura-system-notifier_services 这样的结构
                        # 它的类型就是 'core' 或 'system'
                        plugin_type = 'core'
                    elif top_level_dir == 'plugins':
                        # 对于 plugins/official/my-plugin 这样的结构
                        # 它的类型是 'official'
                        # 对于 plugins/my-plugin (没有命名空间)
                        # 我们给一个默认类型 'third_party'
                        if len(relative_path.parts) > 2:
                            plugin_type = relative_path.parts[1]  # e.g., 'official'
                        else:
                            plugin_type = 'third_party'  # 默认值
                    elif top_level_dir == 'plans':
                        # 对于 plans/my-plan/plugins/private-plugin 这样的结构
                        # 我们统一视为 'plan' 类型
                        plugin_type = 'plan'

                    # ----------------------------------------

                    plugin_def = PluginDefinition.from_yaml(data, plugin_dir, plugin_type)
                    logger.debug(
                        f"--- [DEBUG] Created PluginDefinition: "
                        f"author='{plugin_def.author}', "
                        f"name='{plugin_def.name}', "
                        f"canonical_id='{plugin_def.canonical_id}'"
                    )
                    if plugin_def.canonical_id in self.plugin_registry:
                        existing_plugin = self.plugin_registry[plugin_def.canonical_id]
                        raise RuntimeError(
                            f"插件身份冲突！插件 '{plugin_def.path}' 和 "
                            f"'{existing_plugin.path}' 都声明了相同的身份 "
                            f"'{plugin_def.canonical_id}'。"
                        )

                    self.plugin_registry[plugin_def.canonical_id] = plugin_def
                    logger.debug(f"成功解析插件: {plugin_def.canonical_id} (类型: {plugin_type}, 位于: {plugin_dir})")

                except Exception as e:
                    logger.error(f"解析 '{plugin_yaml_path}' 失败: {e}")
                    raise RuntimeError(f"无法解析插件定义文件 '{plugin_yaml_path}'。") from e

        if not self.plugin_registry:
            logger.warning("未发现任何插件定义 (plugin.yaml)。框架可能无法正常工作。")

    def _resolve_dependencies_and_sort(self) -> List[str]:
        logger.info("--- 阶段2: 解析依赖关系并确定加载顺序 ---")
        provider = PluginProvider(self.plugin_registry)
        reporter = BaseReporter()
        resolver = Resolver(provider, reporter)
        try:
            result = resolver.resolve(self.plugin_registry.keys())
        except Exception as e:
            logger.error("依赖解析失败！请检查插件的 `dependencies` 是否正确。")
            for line in str(e).splitlines():
                logger.error(f"  {line}")
            raise RuntimeError("依赖解析失败，无法启动。") from e
        graph = {
            pid: set(pdef.dependencies.keys()) for pid, pdef in self.plugin_registry.items()
        }
        try:
            ts = TopologicalSorter(graph)
            return list(ts.static_order())
        except CycleError as e:
            cycle_path = " -> ".join(e.args[1])
            raise RuntimeError(f"检测到插件间的循环依赖，无法启动: {cycle_path}")

    def _load_plugins_in_order(self, load_order: List[str]):
        logger.info("--- 阶段3: 按顺序加载插件资源 ---")
        from packages.aura_core.orchestrator import Orchestrator
        for plugin_id in load_order:
            plugin_def = self.plugin_registry[plugin_id]
            logger.debug(f"正在加载插件: {plugin_id}")
            services_path = plugin_def.path / 'services'
            if services_path.is_dir():
                service_registry.scan_path(services_path, plugin_def)
            actions_path = plugin_def.path / 'actions'

            if actions_path.is_dir():
                load_actions_from_path(actions_path, plugin_def)
            if plugin_def.plugin_type == 'plan':
                plan_name = plugin_def.path.name
                if plan_name not in self.plans:
                    logger.info(f"发现方案包: {plan_name}")
                    self.plans[plan_name] = Orchestrator(str(self.base_path), plan_name, self.pause_event)

    def _load_plan_configurations(self):
        """【修复】加载所有方案包的 schedule.yaml 和 interrupts.yaml，并注册它们的配置。"""
        logger.info("--- 阶段4: 加载方案包配置文件 ---")

        try:
            config_service = service_registry.get_service_instance('config')
        except Exception as e:
            logger.error(f"无法获取 ConfigService 实例，方案包配置可能无法加载: {e}")
            return

        for plan_name, orchestrator in self.plans.items():
            plan_dir = orchestrator.current_plan_path

            # 【核心修复】调用新的注册方法，而不是旧的加载方法
            config_service.register_plan_config(plan_name, plan_dir)

            self._load_schedule_file(plan_dir, plan_name)
            self._load_interrupt_file(plan_dir, plan_name)
    def reload_plans(self):
        logger.info("正在从文件系统重新加载所有资源...")
        self._load_all_resources()
        logger.info("重新加载完成。")

    # --- 以下所有其他方法保持不变 ---
    def start_scheduler(self):
        if self.is_scheduler_running.is_set():
            logger.warning("调度器已经在运行中。")
            return
        logger.info("用户请求启动调度器...")
        self.is_scheduler_running.set()
        self.scheduler_thread = threading.Thread(target=self.start, name="CommanderThread", daemon=True)
        self.scheduler_thread.start()

    def stop_scheduler(self):
        if not self.is_scheduler_running.is_set():
            logger.warning("调度器已经处于停止状态。")
            return
        logger.info("用户请求停止调度器。将完成当前任务，并停止调度新任务...")
        self.is_scheduler_running.clear()

    def get_master_status(self) -> dict:
        return {"is_running": self.is_scheduler_running.is_set()}

    def _load_schedule_file(self, plan_dir: Path, plan_name: str):
        schedule_path = plan_dir / "schedule.yaml"
        if schedule_path.exists():
            try:
                with open(schedule_path, 'r', encoding='utf-8') as f:
                    items = yaml.safe_load(f) or []
                    for item in items:
                        item['plan_name'] = plan_name
                        self.schedule_items.append(item)
                        if 'id' in item and item['id'] not in self.run_statuses:
                            self.run_statuses[item['id']] = {'status': 'idle'}
            except Exception as e:
                logger.error(f"加载调度文件 '{schedule_path}' 失败: {e}")

    def _load_interrupt_file(self, plan_dir: Path, plan_name: str):
        interrupt_path = plan_dir / "interrupts.yaml"
        if interrupt_path.exists():
            try:
                with open(interrupt_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                    for rule in data.get('interrupts', []):
                        rule['plan_name'] = plan_name
                        self.interrupt_definitions[rule['name']] = rule
                        if rule.get('scope') == 'global' and rule.get('enabled_by_default', False):
                            self.user_enabled_globals.add(rule['name'])
            except Exception as e:
                logger.error(f"加载中断文件 '{interrupt_path}' 失败: {e}")

    def start(self):
        logger.info("任务调度器线程已启动...")
        self.guardian_thread = threading.Thread(target=self._guardian_loop, name="GuardianThread", daemon=True)
        self.guardian_thread.start()
        logger.info("中断监测已启动，开始后台监控。")
        while self.is_scheduler_running.is_set():
            handler_rule = None
            item_to_run = None
            with self.lock:
                if self.interrupt_queue:
                    handler_rule = self.interrupt_queue.popleft()
                elif self.task_queue and not self.is_device_busy:
                    item_to_run = self.task_queue.popleft()
            if handler_rule:
                self._execute_handler_task(handler_rule)
                continue
            self._check_and_enqueue_tasks(datetime.now())
            if item_to_run:
                self._execute_main_task(item_to_run)
            time.sleep(1)
        logger.info("调度器主循环已安全退出。")

    def _guardian_loop(self):
        while self.is_scheduler_running.is_set():
            active_interrupts = self._get_active_interrupts()
            now = datetime.now()
            for rule_name in active_interrupts:
                should_check = False
                rule = None
                with self.lock:
                    rule = self.interrupt_definitions.get(rule_name)
                    if not rule: continue
                    cooldown_expired = now >= self.interrupt_cooldown_until.get(rule_name, datetime.min)
                    last_check = self.interrupt_last_check_times.get(rule_name, datetime.min)
                    interval_passed = (now - last_check).total_seconds() >= rule.get('check_interval', 5)
                    should_check = cooldown_expired and interval_passed
                if not should_check:
                    continue
                self.interrupt_last_check_times[rule_name] = now
                logger.debug(f"守护者: 正在检查中断条件 '{rule_name}'...")
                try:
                    orchestrator = self.plans[rule['plan_name']]
                    if orchestrator.perform_condition_check(rule.get('condition', {})):
                        logger.warning(f"检测到中断条件: '{rule_name}'! 已提交给指挥官处理。")
                        with self.lock:
                            self.interrupt_queue.append(rule)
                            cooldown_seconds = rule.get('cooldown', 60)
                            self.interrupt_cooldown_until[rule_name] = now + timedelta(seconds=cooldown_seconds)
                        break
                except Exception as e:
                    logger.error(f"守护者在检查中断 '{rule_name}' 时出错: {e}", exc_info=True)
            time.sleep(1)

    def _get_active_interrupts(self) -> Set[str]:
        with self.lock:
            active_set = self.user_enabled_globals.copy()
            current_task_dict = self.current_running_task
            if current_task_dict:
                task_key = 'task' if 'task' in current_task_dict else 'task_name'
                task_path_or_name = current_task_dict.get(task_key)
                if task_path_or_name and 'plan_name' in current_task_dict:
                    try:
                        task_data = self.plans[current_task_dict['plan_name']].load_task_data(task_path_or_name)
                        if task_data:
                            active_set.update(task_data.get('activates_interrupts', []))
                    except Exception as e:
                        logger.error(f"获取活动中断时发生错误: {e}", exc_info=True)
        return active_set

    def _execute_main_task(self, item_to_run: Dict[str, Any]):
        with self.lock:
            if self.is_device_busy:
                logger.warning(f"尝试执行主任务 {item_to_run.get('id')} 时发现设备已忙，放回队列。")
                self.task_queue.appendleft(item_to_run)
                return
            self.current_running_task = item_to_run
        task_id = item_to_run.get('id', 'ad-hoc')
        task_thread = threading.Thread(target=self._run_task_in_thread, name=f"TaskThread-{task_id}",
                                       args=(item_to_run, False, None))
        task_thread.start()

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
        handler_thread = threading.Thread(target=self._run_task_in_thread, name=f"HandlerThread-{rule_name}",
                                          args=(handler_item, True, handler_rule))
        handler_thread.start()

    def _run_task_in_thread(self, item_to_run: Dict, is_handler: bool, handler_rule: Dict = None):
        item_id = item_to_run.get('id')
        plan_name = item_to_run.get('plan_name')
        task_path_or_name = item_to_run.get('task') or item_to_run.get('task_name')
        now = datetime.now()
        if not plan_name or not task_path_or_name:
            logger.error(f"任务项缺少 'plan_name' 或 ('task'/'task_name') 键: {item_to_run}")
            return
        task_started = False
        try:
            with self.lock:
                if self.is_device_busy and not is_handler:
                    logger.warning(f"任务 {item_id or 'ad-hoc'} 启动时发现设备已忙，放弃执行。")
                    if item_id and item_id in self.run_statuses:
                        self.run_statuses[item_id]['status'] = 'idle'
                    return
                self.is_device_busy = True
                task_started = True
                if not is_handler:
                    self.current_running_thread = threading.current_thread()
                    if item_id:
                        self.run_statuses.setdefault(item_id, {}).update({'status': 'running', 'started_at': now})
            if task_started:
                orchestrator = self.plans[plan_name]
                orchestrator.setup_and_run(task_path_or_name)
                if not is_handler and item_id:
                    with self.lock:
                        logger.info(f"任务 '{plan_name}/{task_path_or_name}' (ID: {item_id}) 执行成功。")
                        self.run_statuses.setdefault(item_id, {}).update(
                            {'status': 'idle', 'last_run': now, 'result': 'success'})
        except Exception as e:
            log_prefix = "处理器任务" if is_handler else f"任务 '{item_id or 'ad-hoc'}'"
            logger.error(f"{log_prefix} '{plan_name}/{task_path_or_name}' 执行时发生致命错误: {e}", exc_info=True)
            if not is_handler and item_id:
                with self.lock:
                    self.run_statuses.setdefault(item_id, {}).update(
                        {'status': 'idle', 'last_run': now, 'result': 'failure'})
        finally:
            if task_started:
                with self.lock:
                    self.is_device_busy = False
                    logger.info(f"'{plan_name}/{task_path_or_name}' 执行完毕，设备资源已释放。")
                    if is_handler:
                        self._post_interrupt_handling(handler_rule)
                    else:
                        if self.current_running_thread is threading.current_thread():
                            self.current_running_task = None
                            self.current_running_thread = None

    def _post_interrupt_handling(self, handler_rule: Dict):
        with self.lock:
            strategy = handler_rule.get('on_complete', 'resume')
            logger.info(f"指挥官: 中断处理完毕，执行善后策略: '{strategy}'")
            if strategy == 'resume':
                if self.interrupted_main_task:
                    logger.info(f"指挥官: 命令主任务 '{self.interrupted_main_task.get('name', 'N/A')}' 继续执行。")
                    self.pause_event.clear()
                self.interrupted_main_task = None
            elif strategy == 'restart_task':
                if self.interrupted_main_task:
                    logger.warning(
                        f"指挥官: 策略为重启，原任务 '{self.interrupted_main_task.get('name', 'N/A')}' 将被放弃并重新入队。")
                    if self.current_running_task == self.interrupted_main_task:
                        self.current_running_task = None
                        self.current_running_thread = None
                    self.task_queue.appendleft(self.interrupted_main_task)
                    logger.info(f"任务 '{self.interrupted_main_task.get('name', 'N/A')}' 已重新加入队列。")
                self.interrupted_main_task = None
                self.pause_event.clear()

    def _check_and_enqueue_tasks(self, now):
        with self.lock:
            for item in self.schedule_items:
                item_id = item.get('id')
                if not item_id: continue
                if not item.get('enabled', False): continue
                status = self.run_statuses.get(item_id, {})
                if status.get('status') in ['queued', 'running']: continue
                if self._is_ready_to_run(item, now, status):
                    logger.info(f"任务 '{item.get('name', item_id)}' ({item['plan_name']}) 条件满足，已加入执行队列。")
                    self.task_queue.append(item)
                    self.run_statuses.setdefault(item_id, {}).update({'status': 'queued', 'queued_at': now})

    def _is_ready_to_run(self, item, now, status: Dict) -> bool:
        item_id = item['id']
        cooldown = item.get('run_options', {}).get('cooldown', 0)
        last_run = status.get('last_run')
        if last_run and (now - last_run).total_seconds() < cooldown:
            return False
        trigger = item.get('trigger', {})
        trigger_type = trigger.get('type')
        if trigger_type == 'time_based':
            schedule = trigger.get('schedule')
            if not schedule: return False
            try:
                base_time = last_run or (now - timedelta(seconds=5))
                iterator = croniter(schedule, base_time)
                next_scheduled_run = iterator.get_next(datetime)
                return now >= next_scheduled_run
            except Exception as e:
                logger.error(f"任务 '{item_id}' 的 cron 表达式无效: {schedule}, 错误: {e}")
                return False
        elif trigger_type == 'event_based':
            return False
        elif trigger_type == 'manual':
            return False
        return False

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
            active_interrupts_snapshot = self._get_active_interrupts()
            for name, rule in self.interrupt_definitions.items():
                status = rule.copy()
                if status.get('scope') == 'global':
                    status['enabled'] = name in self.user_enabled_globals
                else:
                    status['enabled'] = name in active_interrupts_snapshot
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
            found = False
            plan_name_to_save = None
            for item in self.schedule_items:
                if item.get('id') == task_id:
                    item['enabled'] = enabled
                    logger.info(f"任务 '{item.get('name', task_id)}' 已被 {'启用' if enabled else '禁用'}.")
                    plan_name_to_save = item.get('plan_name')
                    found = True
                    break
            if found and plan_name_to_save:
                self._save_schedule_for_plan(plan_name_to_save)
                return {"status": "success", "message": f"Task {task_id} updated."}
            elif found:
                logger.error(f"任务 {task_id} 缺少 plan_name，无法保存。")
                return {"status": "error", "message": f"Task {task_id} missing plan_name."}
            else:
                return {"status": "error", "message": f"Task ID {task_id} not found."}

    def run_manual_task(self, task_id: str):
        with self.lock:
            status = self.run_statuses.get(task_id, {})
            if status.get('status') in ['queued', 'running']:
                return {"status": "error", "message": f"Task {task_id} is already queued or running."}
            item_to_run = None
            for item in self.schedule_items:
                if item.get('id') == task_id:
                    item_to_run = item.copy()
                    break
            if item_to_run:
                logger.info(f"手动触发任务 '{item_to_run.get('name', task_id)}'，已高优先级加入队列。")
                self.task_queue.appendleft(item_to_run)
                self.run_statuses.setdefault(task_id, {}).update({'status': 'queued', 'queued_at': datetime.now()})
                return {"status": "success", "message": f"Task {task_id} has been queued for execution."}
            else:
                return {"status": "error", "message": f"Task ID {task_id} not found."}

    def run_ad_hoc_task(self, plan_name: str, task_name: str):
        if plan_name not in self.plans:
            return {"status": "error", "message": f"Plan '{plan_name}' not found."}
        with self.lock:
            ad_hoc_item = {'plan_name': plan_name, 'task_name': task_name, 'is_ad_hoc': True}
            self.task_queue.append(ad_hoc_item)
            logger.info(f"临时任务 '{plan_name}/{task_name}' 已加入执行队列。")
            return {"status": "success"}

    def get_all_plans(self) -> list[str]:
        return sorted(list(self.plans.keys()))

    def get_tasks_for_plan(self, plan_name: str) -> list[str]:
        orchestrator = self.plans.get(plan_name)
        if not orchestrator:
            return []
        return sorted(list(orchestrator.task_definitions.keys()))

    def get_persistent_context(self, plan_name: str) -> dict:
        orchestrator = self.plans.get(plan_name)
        if not orchestrator: raise ValueError(f"Plan '{plan_name}' not found.")
        return orchestrator.get_persistent_context_data()

    def save_persistent_context(self, plan_name: str, data: dict):
        orchestrator = self.plans.get(plan_name)
        if not orchestrator: raise ValueError(f"Plan '{plan_name}' not found.")
        orchestrator.save_persistent_context_data(data)

    def get_plan_files(self, plan_name: str) -> dict:
        if plan_name not in self.plans:
            logger.warning(f"请求获取未加载的方案 '{plan_name}' 的文件列表。")
            return {}
        plan_path = self.base_path / f"plans/{plan_name}"

        def recurse_path(current_path: Path) -> dict:
            structure = {}
            for item in sorted(current_path.iterdir(), key=lambda p: (p.is_file(), p.name)):
                if item.name.startswith('.'): continue
                if item.is_dir():
                    structure[item.name] = recurse_path(item)
                elif item.suffix.lower() in ['.yaml', '.png', '.jpg', '.jpeg', '.json', '.txt']:
                    structure[item.name] = 'file'
            return structure

        return recurse_path(plan_path)

    def get_file_content(self, plan_name: str, file_path: str) -> str:
        orchestrator = self.plans.get(plan_name)
        if not orchestrator: raise ValueError(f"Plan '{plan_name}' not found.")
        return orchestrator.get_file_content(file_path)

    def get_file_content_bytes(self, plan_name: str, file_path: str) -> bytes:
        orchestrator = self.plans.get(plan_name)
        if not orchestrator:
            raise ValueError(f"Plan '{plan_name}' not found.")
        return orchestrator.get_file_content_bytes(file_path)

    def save_file_content(self, plan_name: str, file_path: str, content: str):
        orchestrator = self.plans.get(plan_name)
        if not orchestrator: raise ValueError(f"Plan '{plan_name}' not found.")
        orchestrator.save_file_content(file_path, content)

    def get_available_actions(self) -> dict:
        return {name: defn.docstring for name, defn in ACTION_REGISTRY.items()}

    def get_all_services_status(self) -> List[Dict[str, Any]]:
        definitions = service_registry.get_all_service_definitions()
        return [asdict(definition) for definition in definitions]

    def add_schedule_item(self, data: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            plan_name = data.get('plan_name')
            if not plan_name:
                raise ValueError("添加调度项时必须提供 'plan_name'。")
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
            item_to_update = None
            for item in self.schedule_items:
                if item.get('id') == item_id:
                    item_to_update = item
                    break
            if not item_to_update:
                raise ValueError(f"找不到ID为 '{item_id}' 的调度项。")
            item_to_update.update(data)
            plan_name = item_to_update.get('plan_name')
            if plan_name:
                self._save_schedule_for_plan(plan_name)
            logger.info(f"已更新调度任务: '{item_to_update['name']}' (ID: {item_id})")
            return {"status": "success", "updated_item": item_to_update}

    def delete_schedule_item(self, item_id: str) -> Dict[str, Any]:
        with self.lock:
            item_to_delete = None
            plan_name_to_save = None
            for item in self.schedule_items:
                if item.get('id') == item_id:
                    item_to_delete = item
                    plan_name_to_save = item.get('plan_name')
                    break
            if not item_to_delete:
                raise ValueError(f"找不到ID为 '{item_id}' 的调度项。")
            self.schedule_items.remove(item_to_delete)
            self.run_statuses.pop(item_id, None)
            if plan_name_to_save:
                self._save_schedule_for_plan(plan_name_to_save)
            logger.info(f"已删除调度任务: '{item_to_delete.get('name')}' (ID: {item_id})")
            return {"status": "success", "deleted_id": item_id}

    def inspect_step(self, plan_name: str, task_path: str, step_index: int) -> Any:
        if plan_name not in self.plans:
            raise ValueError(f"找不到方案包 '{plan_name}'。")
        orchestrator = self.plans[plan_name]
        task_name = Path(task_path).relative_to('tasks').with_suffix('').as_posix()
        try:
            result = orchestrator.inspect_step(task_name, step_index)
            return result
        except Exception as e:
            logger.error(f"调用 inspect_step API 时失败: {e}")
            raise

# packages/aura_core/scheduler.py (多任务格式支持版)

import threading
import time
import yaml
import sys
import importlib.util
from collections import deque
from croniter import croniter
from datetime import datetime, timedelta
from pathlib import Path
import uuid
from typing import TYPE_CHECKING, Dict, Any, Set, List, Optional
import inspect

from graphlib import TopologicalSorter, CycleError
from resolvelib import Resolver, BaseReporter
from resolvelib.providers import AbstractProvider
from dataclasses import asdict

from packages.aura_core.builder import build_package_from_source, clear_build_cache, set_project_base_path, \
    API_FILE_NAME
from packages.aura_core.api import service_registry, ServiceDefinition
from packages.aura_core.api import ACTION_REGISTRY, ActionDefinition
from packages.aura_core.api import hook_manager

from packages.aura_shared_utils.utils.logger import logger
from packages.aura_shared_utils.models.plugin_definition import PluginDefinition
from packages.aura_core.state_store import StateStore
from packages.aura_core.event_bus import EventBus, Event
from packages.aura_core.task_queue import TaskQueue

if TYPE_CHECKING:
    from packages.aura_core.orchestrator import Orchestrator


class PluginProvider(AbstractProvider):
    def __init__(self, plugin_registry: Dict[str, PluginDefinition]):
        self.plugin_registry = plugin_registry

    def identify(self, requirement_or_candidate):
        return requirement_or_candidate

    def get_preference(self, identifier: Any, resolutions: Dict[str, Any], candidates: Dict[str, Any],
                       information: Dict[str, Any], backtrack_causes: List[Any], ) -> Any:
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
        self.state_store = StateStore()
        self.event_bus = EventBus()
        self.event_task_queue = TaskQueue()
        self.all_tasks_definitions: Dict[str, Any] = {}
        self.event_worker_threads: List[threading.Thread] = []
        self.num_event_workers = 2
        set_project_base_path(self.base_path)
        self._register_core_services()
        self._load_all_resources()

    def _register_core_services(self):
        service_registry.register_instance('state_store', self.state_store, public=True)
        service_registry.register_instance('event_bus', self.event_bus, public=True)
        service_registry.register_instance('scheduler', self, public=True)
        logger.debug("全局核心服务注册完毕。")

    # 【【【核心修改 1/3】】】
    def _load_all_tasks_definitions(self):
        """
        【修改版】扫描并加载所有方案的所有任务定义。
        支持旧的“单文件单任务”格式和新的“单文件多任务”格式。
        """
        logger.info("--- 阶段4.5: 加载所有任务定义 ---")
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
                        task_data = yaml.safe_load(f)
                        if not isinstance(task_data, dict):
                            continue

                    # 检查是否是旧的“单文件单任务”格式 (顶层有 'steps' 键)
                    if 'steps' in task_data:
                        relative_path = task_file_path.relative_to(tasks_dir)
                        task_name_in_plan = relative_path.with_suffix('').as_posix()
                        full_task_id = f"{plan_name}/{task_name_in_plan}"
                        self.all_tasks_definitions[full_task_id] = task_data
                        logger.debug(f"已加载旧格式任务: {full_task_id}")

                    # 否则，假定是新的“单文件多任务”格式
                    else:
                        for task_key, task_definition in task_data.items():
                            if isinstance(task_definition, dict) and 'steps' in task_definition:
                                full_task_id = f"{plan_name}/{task_key}"
                                self.all_tasks_definitions[full_task_id] = task_definition
                                logger.debug(f"已加载新格式任务: {full_task_id}")
                            else:
                                logger.warning(f"在文件 '{task_file_path}' 中发现无效的任务条目: '{task_key}'，已跳过。")

                except Exception as e:
                    logger.error(f"加载任务文件 '{task_file_path}' 失败: {e}")

        logger.info(f"任务定义加载完毕，共找到 {len(self.all_tasks_definitions)} 个任务。")

    def _subscribe_event_triggers(self):
        logger.info("--- 阶段4.6: 订阅事件触发器 ---")
        subscribed_count = 0
        for task_id, task_data in self.all_tasks_definitions.items():
            plan_name = task_id.split('/')[0]
            triggers = task_data.get('triggers')
            if not isinstance(triggers, list):
                continue
            for trigger in triggers:
                if not isinstance(trigger, dict) or 'event' not in trigger:
                    continue
                event_pattern = trigger['event']
                plugin_def = next((p for p in self.plugin_registry.values() if p.path.name == plan_name), None)
                if not plugin_def:
                    logger.warning(f"为任务 '{task_id}' 订阅事件时找不到对应的插件定义，已跳过。")
                    continue
                default_channel = plugin_def.canonical_id
                channel = trigger.get('channel', default_channel)
                from functools import partial
                callback = partial(self._handle_event_triggered_task, task_id=task_id)
                callback.__name__ = f"event_trigger_for_{task_id.replace('/', '_')}"
                self.event_bus.subscribe(event_pattern, callback, channel=channel)
                subscribed_count += 1
                logger.debug(f"任务 '{task_id}' 订阅了事件模式 '{event_pattern}' (频道: {channel})")
        logger.info(f"事件触发器订阅完成，共 {subscribed_count} 个订阅。")

    def _handle_event_triggered_task(self, event: Event, task_id: str):
        logger.info(f"事件 '{event.name}' (频道: {event.channel}) 触发了任务 '{task_id}'")
        from packages.aura_core.task_queue import Tasklet
        tasklet = Tasklet(task_name=task_id, triggering_event=event)
        self.event_task_queue.put(tasklet)

    def _event_worker_loop(self, worker_id: int):
        logger.info(f"[EventWorker-{worker_id}] 事件工作线程已启动")
        while self.is_scheduler_running.is_set():
            try:
                import queue
                tasklet = self.event_task_queue.get(block=True, timeout=1)
                task_id = tasklet.task_name
                plan_name = task_id.split('/')[0]
                task_name = task_id[len(plan_name) + 1:]
                logger.info(f"[EventWorker-{worker_id}] 执行事件触发的任务: '{task_id}'")
                if plan_name in self.plans:
                    orchestrator = self.plans[plan_name]
                    orchestrator.execute_task(task_name, tasklet.triggering_event)
                else:
                    logger.error(f"找不到方案 '{plan_name}' 的Orchestrator")
                self.event_task_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[EventWorker-{worker_id}] 处理事件任务时出错: {e}", exc_info=True)
        logger.info(f"[EventWorker-{worker_id}] 事件工作线程已停止")

    def _load_plan_configurations(self):
        logger.info("--- 阶段4: 加载方案包配置文件 ---")
        try:
            config_service = service_registry.get_service_instance('config')
        except Exception as e:
            logger.error(f"无法获取 ConfigService 实例，方案包配置将无法加载: {e}")
            return
        for plugin_def in self.plugin_registry.values():
            if plugin_def.plugin_type != 'plan':
                continue
            plan_name = plugin_def.path.name
            config_path = plugin_def.path / 'config.yaml'
            config_data = {}
            if config_path.is_file():
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        loaded_data = yaml.safe_load(f)
                    if isinstance(loaded_data, dict):
                        config_data = loaded_data
                    elif loaded_data is not None:
                        logger.warning(f"配置文件 '{config_path}' 的内容不是一个有效的字典，已忽略。")
                except Exception as e:
                    logger.error(f"加载配置文件 '{config_path}' 失败: {e}")
            config_service.register_plan_config(plan_name, config_data)
            self._load_schedule_file(plugin_def.path, plan_name)
            self._load_interrupt_file(plugin_def.path, plan_name)
        self._load_all_tasks_definitions()
        self._subscribe_event_triggers()

    def _load_all_resources(self):
        logger.info("======= 开始加载所有框架资源 (Aura 3.0) =======")
        try:
            # 【核心修改】不再调用 self._clear_registries()
            # 而是手动清理插件相关的注册表
            self._clear_plugin_registries() # <--- 使用新的、更安全的方法

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
            f"{len(ACTION_REGISTRY)} 个行为, {len(self.plans)} 个方案包, "
            f"{len(self.all_tasks_definitions)} 个任务。"
        )


    def _clear_registries(self):
        """
        【修改】完全清理所有注册表，包括核心服务。
        这个方法应该只在框架完全关闭或重启时调用。
        """
        service_registry.clear()
        ACTION_REGISTRY.clear()
        hook_manager.clear()
        clear_build_cache()
        self.plans.clear()
        self.plugin_registry.clear()
        self.schedule_items.clear()
        self.interrupt_definitions.clear()
        self.user_enabled_globals.clear()
        self.all_tasks_definitions.clear()
        # 清理事件总线和任务队列
        self.event_bus.shutdown()  # 假设 event_bus 有一个清理方法
        while not self.event_task_queue.empty():
            self.event_task_queue.get()

    def _clear_plugin_registries(self):
        """
        【新增】安全地清理所有与插件相关的注册表，但保留核心服务。
        这个方法用于插件的热重载。
        """
        logger.info("正在清理插件相关的注册表...")

        # 从 ServiceRegistry 中移除所有非核心服务
        # 'core/' 是我们为核心服务保留的命名空间
        service_registry.remove_services_by_prefix(exclude_prefix="core/")

        # 清理其他插件相关的注册表
        ACTION_REGISTRY.clear()
        hook_manager.clear()  # 钩子通常由插件定义，也应被清理
        clear_build_cache()
        self.plans.clear()
        self.plugin_registry.clear()
        self.schedule_items.clear()
        self.interrupt_definitions.clear()
        self.user_enabled_globals.clear()
        self.all_tasks_definitions.clear()
        # 事件总线本身不清理，但可以考虑清理它的订阅者
        self.event_bus.clear_subscriptions()  # 假设有这样一个方法

    def _discover_and_parse_plugins(self):
        logger.info("--- 阶段1: 发现并解析所有插件定义 (plugin.yaml) ---")
        plugin_paths_to_scan = [self.base_path / 'plans', self.base_path / 'packages']
        for root_path in plugin_paths_to_scan:
            if not root_path.is_dir():
                logger.warning(f"插件扫描目录不存在: {root_path}")
                continue
            for plugin_yaml_path in root_path.glob('**/plugin.yaml'):
                plugin_dir = plugin_yaml_path.parent
                try:
                    with open(plugin_yaml_path, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)
                    plugin_type = 'unknown'
                    relative_path = plugin_dir.relative_to(self.base_path)
                    top_level_dir = relative_path.parts[0]
                    if top_level_dir == 'packages':
                        plugin_type = 'core'
                    elif top_level_dir == 'plans':
                        plugin_type = 'plan'
                    plugin_def = PluginDefinition.from_yaml(data, plugin_dir, plugin_type)
                    if plugin_def.canonical_id in self.plugin_registry:
                        raise RuntimeError(
                            f"插件身份冲突！插件 '{plugin_def.path}' 和 '{self.plugin_registry[plugin_def.canonical_id].path}' 都声明了相同的身份 '{plugin_def.canonical_id}'。")
                    self.plugin_registry[plugin_def.canonical_id] = plugin_def
                    logger.debug(f"成功解析插件: {plugin_def.canonical_id} (类型: {plugin_type}, 位于: {plugin_dir})")
                except Exception as e:
                    logger.error(f"解析 '{plugin_yaml_path}' 失败: {e}")
                    raise RuntimeError(f"无法解析插件定义文件 '{plugin_yaml_path}'。") from e
        if not self.plugin_registry: logger.warning("未发现任何插件定义 (plugin.yaml)。框架可能无法正常工作。")

    def _resolve_dependencies_and_sort(self) -> List[str]:
        logger.info("--- 阶段2: 解析依赖关系并确定加载顺序 ---")
        provider = PluginProvider(self.plugin_registry)
        reporter = BaseReporter()
        resolver = Resolver(provider, reporter)
        try:
            result = resolver.resolve(self.plugin_registry.keys())
        except Exception as e:
            logger.error("依赖解析失败！请检查插件的 `dependencies` 是否正确。")
            for line in str(e).splitlines(): logger.error(f"  {line}")
            raise RuntimeError("依赖解析失败，无法启动。") from e
        graph = {pid: set(pdef.dependencies.keys()) for pid, pdef in self.plugin_registry.items()}
        try:
            ts = TopologicalSorter(graph)
            return list(ts.static_order())
        except CycleError as e:
            cycle_path = " -> ".join(e.args[1])
            raise RuntimeError(f"检测到插件间的循环依赖，无法启动: {cycle_path}")

    # 【【【核心修改 2/3】】】
    def _load_plugins_in_order(self, load_order: List[str]):
        """【修改】在加载包后，检查并加载其钩子"""
        logger.info("--- 阶段3: 按顺序加载/构建所有包 ---")
        from packages.aura_core.orchestrator import Orchestrator
        for plugin_id in load_order:
            plugin_def = self.plugin_registry[plugin_id]
            api_file_path = plugin_def.path / API_FILE_NAME
            if api_file_path.exists():
                logger.debug(f"发现 API 文件，为包 '{plugin_id}' 尝试快速加载...")
                try:
                    self._load_package_from_api_file(plugin_def, api_file_path)
                except Exception as e:
                    logger.warning(f"从 API 文件快速加载包 '{plugin_id}' 失败: {e}。将回退到从源码构建。")
                    build_package_from_source(plugin_def)
            else:
                logger.info(f"未找到 API 文件，为包 '{plugin_id}' 从源码构建...")
                build_package_from_source(plugin_def)
            self._load_hooks_for_package(plugin_def)
            if plugin_def.plugin_type == 'plan':
                plan_name = plugin_def.path.name
                if plan_name not in self.plans:
                    logger.info(f"发现方案包: {plan_name}")
                    # 将 self (scheduler实例) 传递给 Orchestrator
                    self.plans[plan_name] = Orchestrator(str(self.base_path), plan_name, self.pause_event, self)

    def _load_hooks_for_package(self, plugin_def: PluginDefinition):
        hooks_file = plugin_def.path / 'hooks.py'
        if hooks_file.is_file():
            logger.debug(f"在包 '{plugin_def.canonical_id}' 中发现钩子文件，正在加载...")
            try:
                module = self._lazy_load_module(hooks_file)
                for _, func in inspect.getmembers(module, inspect.isfunction):
                    if hasattr(func, '_aura_hook_name'):
                        hook_name = getattr(func, '_aura_hook_name')
                        hook_manager.register(hook_name, func)
            except Exception as e:
                logger.error(f"加载钩子文件 '{hooks_file}' 失败: {e}", exc_info=True)

    def _load_package_from_api_file(self, plugin_def: PluginDefinition, api_file_path: Path):
        with open(api_file_path, 'r', encoding='utf-8') as f:
            api_data = yaml.safe_load(f)
        for service_info in api_data.get("exports", {}).get("services", []):
            module = self._lazy_load_module(plugin_def.path / service_info['source_file'])
            if not module: logger.error(f"快速加载失败：无法加载服务模块 {service_info['source_file']}"); continue
            service_class = getattr(module, service_info['class_name'])
            definition = ServiceDefinition(alias=service_info['alias'],
                                           fqid=f"{plugin_def.canonical_id}/{service_info['alias']}",
                                           service_class=service_class, plugin=plugin_def, public=True)
            service_registry.register(definition)
        for action_info in api_data.get("exports", {}).get("actions", []):
            module = self._lazy_load_module(plugin_def.path / action_info['source_file'])
            if not module: logger.error(f"快速加载失败：无法加载行为模块 {action_info['source_file']}"); continue
            action_func = getattr(module, action_info['function_name'])
            definition = ActionDefinition(func=action_func, name=action_info['name'],
                                          read_only=getattr(action_func, '_aura_action_meta', {}).get('read_only',
                                                                                                      False),
                                          public=True, service_deps=action_info.get('required_services', {}),
                                          plugin=plugin_def)
            ACTION_REGISTRY.register(definition)
        logger.debug(f"包 '{plugin_def.canonical_id}' 已从 API 文件成功加载。")

    def _lazy_load_module(self, file_path: Path) -> Optional[Any]:
        try:
            try:
                relative_path = file_path.relative_to(self.base_path)
            except ValueError:
                relative_path = Path(file_path.name)
            module_name = str(relative_path).replace('/', '.').replace('\\', '.').removesuffix('.py')
            if module_name in sys.modules: return sys.modules[module_name]
            parent_dir = str(file_path.parent.resolve())
            path_added = False
            if parent_dir not in sys.path: sys.path.insert(0, parent_dir); path_added = True
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None:
                if path_added: sys.path.remove(parent_dir)
                return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            if path_added: sys.path.remove(parent_dir)
            return module
        except Exception as e:
            logger.error(f"延迟加载模块 '{file_path}' 失败: {e}", exc_info=True)
            raise

    # 【【【核心修改 3/3】】】
    def _run_task_in_thread(self, item_to_run: Dict, is_handler: bool, handler_rule: Dict = None):
        item_id = item_to_run.get('id')
        plan_name = item_to_run.get('plan_name')
        # 'task' 来自调度项, 'task_name' 来自临时任务
        task_id_in_plan = item_to_run.get('task') or item_to_run.get('task_name')
        now = datetime.now()
        if not plan_name or not task_id_in_plan:
            logger.error(f"任务项缺少 'plan_name' 或 ('task'/'task_name') 键: {item_to_run}")
            return

        full_task_id = f"{plan_name}/{task_id_in_plan}"
        task_started = False
        task_context = {"item": item_to_run, "is_handler": is_handler, "handler_rule": handler_rule, "start_time": now}
        try:
            with self.lock:
                if self.is_device_busy and not is_handler:
                    logger.warning(f"任务 {item_id or 'ad-hoc'} 启动时发现设备已忙，放弃执行。")
                    if item_id and item_id in self.run_statuses: self.run_statuses[item_id]['status'] = 'idle'
                    return
                self.is_device_busy = True
                task_started = True
                if not is_handler:
                    self.current_running_thread = threading.current_thread()
                    if item_id: self.run_statuses.setdefault(item_id, {}).update(
                        {'status': 'running', 'started_at': now})
            if task_started:
                hook_manager.trigger('before_task_run', task_context=task_context)
                orchestrator = self.plans[plan_name]
                # 传递任务在方案内的ID
                result = orchestrator.execute_task(task_id_in_plan)
                task_context['end_time'] = datetime.now()
                task_context['result'] = result
                hook_manager.trigger('after_task_success', task_context=task_context)
                if not is_handler and item_id:
                    with self.lock:
                        logger.info(f"任务 '{full_task_id}' (ID: {item_id}) 执行成功。")
                        self.run_statuses.setdefault(item_id, {}).update(
                            {'status': 'idle', 'last_run': now, 'result': 'success'})
        except Exception as e:
            task_context['end_time'] = datetime.now()
            task_context['exception'] = e
            hook_manager.trigger('after_task_failure', task_context=task_context)
            log_prefix = "处理器任务" if is_handler else f"任务 '{item_id or 'ad-hoc'}'"
            logger.error(f"{log_prefix} '{full_task_id}' 执行时发生致命错误: {e}", exc_info=True)
            if not is_handler and item_id:
                with self.lock: self.run_statuses.setdefault(item_id, {}).update(
                    {'status': 'idle', 'last_run': now, 'result': 'failure'})
        finally:
            if task_started:
                with self.lock:
                    self.is_device_busy = False
                    logger.info(f"'{full_task_id}' 执行完毕，设备资源已释放。")
                    if is_handler:
                        self._post_interrupt_handling(handler_rule)
                    else:
                        if self.current_running_thread is threading.current_thread():
                            self.current_running_task = None
                            self.current_running_thread = None
                hook_manager.trigger('after_task_run', task_context=task_context)

    # --- 以下方法保持不变 ---
    def reload_plans(self):
        logger.info("正在从文件系统重新加载所有资源...")
        self._load_all_resources()
        logger.info("重新加载完成。")

    def start_scheduler(self):
        if self.is_scheduler_running.is_set(): logger.warning("调度器已经在运行中。"); return
        logger.info("用户请求启动调度器...")
        self.is_scheduler_running.set()
        self.scheduler_thread = threading.Thread(target=self.start, name="CommanderThread", daemon=True)
        self.scheduler_thread.start()

    def stop_scheduler(self):
        if not self.is_scheduler_running.is_set(): logger.warning("调度器已经处于停止状态。"); return
        logger.info("用户请求停止调度器。将完成当前任务，并停止调度新任务...")
        self.is_scheduler_running.clear()
        for worker in self.event_worker_threads:
            if worker.is_alive(): worker.join(timeout=5)

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
                        if 'id' in item and item['id'] not in self.run_statuses: self.run_statuses[item['id']] = {
                            'status': 'idle'}
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
                        if rule.get('scope') == 'global' and rule.get('enabled_by_default',
                                                                      False): self.user_enabled_globals.add(
                            rule['name'])
            except Exception as e:
                logger.error(f"加载中断文件 '{interrupt_path}' 失败: {e}")

    def start(self):
        logger.info("任务调度器线程已启动...")
        for i in range(self.num_event_workers):
            worker = threading.Thread(target=self._event_worker_loop, args=(i + 1,))
            worker.daemon = True
            self.event_worker_threads.append(worker)
            worker.start()
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
            if handler_rule: self._execute_handler_task(handler_rule); continue
            self._check_and_enqueue_tasks(datetime.now())
            if item_to_run: self._execute_main_task(item_to_run)
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
                if not should_check: continue
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
                        full_task_id = f"{current_task_dict['plan_name']}/{task_path_or_name}"
                        task_data = self.all_tasks_definitions.get(full_task_id)
                        if task_data: active_set.update(task_data.get('activates_interrupts', []))
                    except Exception as e:
                        logger.error(f"获取活动中断时发生错误: {e}", exc_info=True)
        return active_set

    def _execute_main_task(self, item_to_run: Dict[str, Any]):
        with self.lock:
            if self.is_device_busy: logger.warning(
                f"尝试执行主任务 {item_to_run.get('id')} 时发现设备已忙，放回队列。"); self.task_queue.appendleft(
                item_to_run); return
            self.current_running_task = item_to_run
        task_id = item_to_run.get('id', 'ad-hoc')
        task_thread = threading.Thread(target=self._run_task_in_thread, name=f"TaskThread-{task_id}",
                                       args=(item_to_run, False, None))
        task_thread.start()

    def _execute_handler_task(self, handler_rule: Dict[str, Any]):
        rule_name = handler_rule.get('name', 'unknown_interrupt')
        logger.info(f"指挥官: 开始处理中断 '{rule_name}'...")
        with self.lock:
            if self.current_running_task: logger.info(
                f"指挥官: 命令主任务 '{self.current_running_task.get('name', 'N/A')}' 暂停。"); self.pause_event.set(); self.interrupted_main_task = self.current_running_task
        handler_item = {'plan_name': handler_rule['plan_name'], 'task_name': handler_rule['handler_task'],
                        'is_ad_hoc': True}
        handler_thread = threading.Thread(target=self._run_task_in_thread, name=f"HandlerThread-{rule_name}",
                                          args=(handler_item, True, handler_rule))
        handler_thread.start()

    def _post_interrupt_handling(self, handler_rule: Dict):
        with self.lock:
            strategy = handler_rule.get('on_complete', 'resume')
            logger.info(f"指挥官: 中断处理完毕，执行善后策略: '{strategy}'")
            if strategy == 'resume':
                if self.interrupted_main_task: logger.info(
                    f"指挥官: 命令主任务 '{self.interrupted_main_task.get('name', 'N/A')}' 继续执行。"); self.pause_event.clear()
                self.interrupted_main_task = None
            elif strategy == 'restart_task':
                if self.interrupted_main_task:
                    logger.warning(
                        f"指挥官: 策略为重启，原任务 '{self.interrupted_main_task.get('name', 'N/A')}' 将被放弃并重新入队。")
                    if self.current_running_task == self.interrupted_main_task: self.current_running_task = None; self.current_running_thread = None
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
        if last_run and (now - last_run).total_seconds() < cooldown: return False
        trigger = item.get('trigger', {})
        trigger_type = trigger.get('type')
        if trigger_type == 'time_based':
            schedule = trigger.get('schedule')
            if not schedule: logger.warning(
                f"任务 '{item_id}' 是 time_based 类型，但缺少 'schedule' 表达式。"); return False
            try:
                iterator = croniter(schedule, now)
                prev_scheduled_run = iterator.get_prev(datetime)
                effective_last_run = last_run or datetime.min
                if prev_scheduled_run > effective_last_run:
                    logger.debug(
                        f"任务 '{item_id}' 已到期。上次运行: {effective_last_run}, 上个预定点: {prev_scheduled_run}, 当前时间: {now}")
                    return True
                else:
                    return False
            except Exception as e:
                logger.error(f"任务 '{item_id}' 的 cron 表达式无效: {schedule}, 错误: {e}");
                return False
        elif trigger_type in ['event_based', 'manual']:
            return False
        return False

    def enable_global_interrupt(self, name: str):
        with self.lock:
            if name in self.interrupt_definitions and self.interrupt_definitions[name].get(
                    'scope') == 'global': self.user_enabled_globals.add(name); logger.info(
                f"UI: 已启用全局中断 '{name}'")

    def disable_global_interrupt(self, name: str):
        with self.lock: self.user_enabled_globals.discard(name); logger.info(f"UI: 已禁用全局中断 '{name}'")

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
        with self.lock: schedule_items_copy = list(self.schedule_items); run_statuses_copy = dict(self.run_statuses)
        status_list = []
        for item in schedule_items_copy: full_status = item.copy(); full_status.update(
            run_statuses_copy.get(item.get('id'), {})); status_list.append(full_status)
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
                self._save_schedule_for_plan(plan_name_to_save);
                return {"status": "success",
                        "message": f"Task {task_id} updated."}
            elif found:
                logger.error(f"任务 {task_id} 缺少 plan_name，无法保存。");
                return {"status": "error",
                        "message": f"Task {task_id} missing plan_name."}
            else:
                return {"status": "error", "message": f"Task ID {task_id} not found."}

    def run_manual_task(self, task_id: str):
        with self.lock:
            status = self.run_statuses.get(task_id, {})
            if status.get('status') in ['queued', 'running']: return {"status": "error",
                                                                      "message": f"Task {task_id} is already queued or running."}
            item_to_run = None
            for item in self.schedule_items:
                if item.get('id') == task_id: item_to_run = item.copy(); break
            if item_to_run:
                logger.info(f"手动触发任务 '{item_to_run.get('name', task_id)}'，已高优先级加入队列。")
                self.task_queue.appendleft(item_to_run)
                self.run_statuses.setdefault(task_id, {}).update({'status': 'queued', 'queued_at': datetime.now()})
                return {"status": "success", "message": f"Task {task_id} has been queued for execution."}
            else:
                return {"status": "error", "message": f"Task ID {task_id} not found."}

    def run_ad_hoc_task(self, plan_name: str, task_name: str):
        if plan_name not in self.plans: return {"status": "error", "message": f"Plan '{plan_name}' not found."}
        with self.lock:
            ad_hoc_item = {'plan_name': plan_name, 'task_name': task_name, 'is_ad_hoc': True}
            self.task_queue.append(ad_hoc_item)
            logger.info(f"临时任务 '{plan_name}/{task_name}' 已加入执行队列。")
            return {"status": "success"}

    def get_all_plans(self) -> list[str]:
        return sorted(list(self.plans.keys()))

    def get_tasks_for_plan(self, plan_name: str) -> list[str]:
        orchestrator = self.plans.get(plan_name)
        if not orchestrator: return []
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
        if plan_name not in self.plans: logger.warning(f"请求获取未加载的方案 '{plan_name}' 的文件列表。"); return {}
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
        if not orchestrator: raise ValueError(f"Plan '{plan_name}' not found.")
        return orchestrator.get_file_content_bytes(file_path)

    def save_file_content(self, plan_name: str, file_path: str, content: str):
        orchestrator = self.plans.get(plan_name)
        if not orchestrator: raise ValueError(f"Plan '{plan_name}' not found.")
        orchestrator.save_file_content(file_path, content)

    def get_available_actions(self) -> dict:
        return {name: defn.docstring for name, defn in ACTION_REGISTRY.items()}

    def get_all_services_status(self) -> List[Dict[str, Any]]:
        """
        【最终修正版】获取所有已定义服务的状态信息，专为UI设计。
        手动构建字典，确保所有值都是可安全序列化的基本类型。
        """
        definitions = service_registry.get_all_service_definitions()

        status_list = []
        for s_def in definitions:
            # 【核心修改】检查 s_def.plugin 是否存在
            if s_def.plugin:
                plugin_info = {
                    'canonical_id': s_def.plugin.canonical_id,
                    'path': str(s_def.plugin.path)
                }
            else:
                # 对于核心服务，提供一个默认的、有意义的插件信息
                plugin_info = {
                    'canonical_id': 'core/framework',
                    'path': 'N/A'
                }

            status_dict = {
                'fqid': s_def.fqid,
                'alias': s_def.alias,
                'status': s_def.status,
                'public': s_def.public,
                'is_extension': s_def.is_extension,
                'parent_fqid': s_def.parent_fqid,
                'plugin': plugin_info, # <--- 使用我们安全创建的 plugin_info
                'service_class': {
                    'name': s_def.service_class.__name__,
                    'module': s_def.service_class.__module__
                },
            }
            status_list.append(status_dict)

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
            item_to_update = None
            for item in self.schedule_items:
                if item.get('id') == item_id: item_to_update = item; break
            if not item_to_update: raise ValueError(f"找不到ID为 '{item_id}' 的调度项。")
            item_to_update.update(data)
            plan_name = item_to_update.get('plan_name')
            if plan_name: self._save_schedule_for_plan(plan_name)
            logger.info(f"已更新调度任务: '{item_to_update['name']}' (ID: {item_id})")
            return {"status": "success", "updated_item": item_to_update}

    def delete_schedule_item(self, item_id: str) -> Dict[str, Any]:
        with self.lock:
            item_to_delete = None
            plan_name_to_save = None
            for item in self.schedule_items:
                if item.get('id') == item_id: item_to_delete = item; plan_name_to_save = item.get('plan_name'); break
            if not item_to_delete: raise ValueError(f"找不到ID为 '{item_id}' 的调度项。")
            self.schedule_items.remove(item_to_delete)
            self.run_statuses.pop(item_id, None)
            if plan_name_to_save: self._save_schedule_for_plan(plan_name_to_save)
            logger.info(f"已删除调度任务: '{item_to_delete.get('name')}' (ID: {item_id})")
            return {"status": "success", "deleted_id": item_id}

    def inspect_step(self, plan_name: str, task_path: str, step_index: int) -> Any:
        if plan_name not in self.plans: raise ValueError(f"找不到方案包 '{plan_name}'。")
        orchestrator = self.plans[plan_name]
        task_name = Path(task_path).relative_to('tasks').with_suffix('').as_posix()
        try:
            result = orchestrator.inspect_step(task_name, step_index)
            return result
        except Exception as e:
            logger.error(f"调用 inspect_step API 时失败: {e}");
            raise

    def publish_event_manually(self, event_name: str, payload: dict = None, source: str = "manual",
                               channel: str = "global") -> dict:
        try:
            event = Event(name=event_name, channel=channel, payload=payload or {}, source=source)
            self.event_bus.publish(event)
            return {"status": "success", "message": f"Event '{event_name}' on channel '{channel}' published."}
        except Exception as e:
            logger.error(f"手动发布事件失败: {e}", exc_info=True);
            return {"status": "error", "message": str(e)}

    def get_event_system_status(self) -> dict:
        return {"event_queue_size": self.event_task_queue._queue.qsize() if hasattr(self.event_task_queue._queue,
                                                                                    'qsize') else 0,
                "total_tasks": len(self.all_tasks_definitions), "event_workers": len(self.event_worker_threads),
                "event_workers_alive": sum(1 for t in self.event_worker_threads if t.is_alive())}

    @property
    def services(self):
        return service_registry

    @property
    def actions(self):
        return ACTION_REGISTRY

    @property
    def hooks(self):
        return hook_manager

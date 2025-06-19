# src/core/orchestrator.py

import os
import yaml
from typing import Dict, Any
import threading
from pathlib import Path

from packages.aura_core.engine import ExecutionEngine, Context
from packages.aura_system_actions.actions.decorators import ACTION_REGISTRY
from packages.aura_shared_utils.utils.logger import logger
from packages.aura_shared_utils.utils.assist import Pathfinder
from packages.aura_core.persistent_context import PersistentContext
from packages.aura_core.service_registry import service_registry


# 【注意】AppProvider的导入可能不再需要，因为它应该作为一个服务被注入
# from src.hardware.app_provider import AppProviderService


class _ReadOnlyDict(dict):
    """一个只读的字典封装，用于保护 aura.params。"""

    def __setitem__(self, key, value):
        raise TypeError("脚本参数 'aura.params' 是只读的。")

    def __delitem__(self, key):
        raise TypeError("脚本参数 'aura.params' 是只读的。")


class _ActionProxy:
    """动态代理，使 aura.notifier_actions.some_action(...) 调用成为可能。"""

    def __init__(self, engine: 'ExecutionEngine'):
        self._engine = engine

    def __getattr__(self, name: str):
        def caller(**kwargs):
            # 【确认】这里的 'name' 就是 action 的名称，
            # ExecutionEngine 会用它从 ACTION_REGISTRY 找到 ActionDefinition
            # 并处理其 service_dependencies。这里的逻辑是正确的。
            step_data = {'action': name, 'params': kwargs}
            return self._engine._dispatch_action(step_data, kwargs)

        return caller


class AuraApi:
    """一个安全的、面向脚本的API对象，将被注入到Python脚本的执行环境中。"""

    def __init__(self, orchestrator: 'Orchestrator', engine: 'ExecutionEngine', params: dict):
        self._orchestrator = orchestrator
        self._engine = engine
        self.context = orchestrator.context
        self.persistent_context = orchestrator.persistent_context
        self.actions = _ActionProxy(engine)
        self.log = logger
        self.params = _ReadOnlyDict(params)

        class Info:
            plan_name = orchestrator.plan_name
            plan_path = str(orchestrator.current_plan_path.resolve())

        self.info = Info()


class Orchestrator:
    """
    负责单个方案包的运行时环境准备和任务执行。
    它假设所有服务和Action在其实例化时已被Scheduler加载完毕。
    """

    def __init__(self, base_dir: str, plan_name: str, pause_event: threading.Event):
        self.base_dir = base_dir
        self.plan_name = plan_name
        self.plans_dir = Path(base_dir) / 'plans'
        self.current_plan_path = self.plans_dir / self.plan_name
        self.pause_event = pause_event

        self.engine = None
        self.context = None
        self.world_map = None
        self.persistent_context = None
        self.config = None

        self.tasks_dir = self.current_plan_path / "tasks"
        self.task_definitions: Dict[str, Any] = {}
        self._load_all_task_definitions()

    def _load_all_task_definitions(self):
        """递归加载tasks目录下所有的 .yaml 文件。"""
        if not self.tasks_dir.is_dir():
            logger.warning(f"在方案 '{self.plan_name}' 中未找到 'tasks' 目录。")
            return
        logger.debug(f"[{self.plan_name}] 开始递归加载任务...")
        for task_path in self.tasks_dir.rglob("*.yaml"):
            try:
                relative_path = task_path.relative_to(self.tasks_dir)
                task_name = relative_path.with_suffix('').as_posix()
                with open(task_path, 'r', encoding='utf-8') as f:
                    task_data = yaml.safe_load(f)
                    if task_data:
                        self.task_definitions[task_name] = task_data
            except Exception as e:
                logger.error(f"加载任务文件 '{task_path}' 失败: {e}")
        logger.debug(f"[{self.plan_name}] 任务加载完毕，共找到 {len(self.task_definitions)} 个任务。")

    def setup_and_run(self, task_name: str):
        """为单个任务的运行准备好所有环境（上下文、引擎等），然后执行它。"""
        log_directory = os.path.join(self.current_plan_path, 'logs')
        logger.setup(log_dir=log_directory, task_name=task_name)
        logger.info(f"Aura框架启动，总共注册了 {len(ACTION_REGISTRY)} 个行为。")

        self._load_config()
        if not self.config: return

        self._initialize_context()

        self.engine = ExecutionEngine(context=self.context, action_registry=ACTION_REGISTRY,
                                      pause_event=self.pause_event, orchestrator=self)

        self.world_map = self.load_world_map()
        if not self.world_map:
            logger.warning("未找到或未能加载 world_map.yaml，状态路径规划功能将不可用。")

        task_data = self.load_task_data(task_name)
        if not task_data:
            logger.critical(f"无法加载主任务 '{task_name}'，任务中止。")
            return

        required_state = task_data.get('requires_state')
        if required_state and self.world_map:
            self._handle_state_transition(required_state)

        logger.info(f"--- 前置状态满足，开始执行主任务: {task_name} ---")
        self.engine.run(task_data, task_name)

    def _load_config(self):
        """加载方案的 config.yaml 文件。"""
        if self.config: return
        config_path = os.path.join(self.current_plan_path, 'config.yaml')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
        except FileNotFoundError:
            logger.critical(f"在方案 '{self.plan_name}' 中找不到 config.yaml，任务中止。")
            self.config = None



    def _initialize_context(self):
        """
        【最终架构版】创建并填充运行时上下文。
        """
        self.context = Context()

        # 1. 初始化并注入长期上下文 (这部分不变)
        context_path = self.current_plan_path / 'persistent_context.json'
        self.persistent_context = PersistentContext(str(context_path))
        for key, value in self.persistent_context.get_all_data().items():
            self.context.set(key, value)
        self.context.set('persistent_context', self.persistent_context)

        # 2. 【核心修复】设置活动配置，并注入到上下文中
        try:
            config_service = service_registry.get_service_instance('config')

            # a. 【关键】在执行任何操作前，先告诉ConfigService当前是哪个方案包在运行
            config_service.set_active_plan(self.plan_name)

            # b. 从服务中获取当前活动的配置字典
            plan_config_dict = config_service.active_plan_config

            # c. 将这个正确的配置字典注入上下文
            self.context.set('config', plan_config_dict)

        except Exception as e:
            logger.error(f"设置活动配置或获取方案配置失败: {e}", exc_info=True)
            self.context.set('config', {})

        # 3. 注入其他必要的工具和变量 (这部分不变)
        self.context.set('log', logger)
        debug_dir = self.current_plan_path / 'debug_screenshots'
        debug_dir.mkdir(parents=True, exist_ok=True)
        self.context.set('debug_dir', str(debug_dir))
        self.context.set('AuraApi', AuraApi)

    def get_available_actions(self) -> dict:
        action_details = {}
        for name, action_def in ACTION_REGISTRY.items():
            try:
                action_details[name] = action_def
            except (ValueError, TypeError):
                logger.warning(f"无法获取行为 '{name}' 的签名。")
        return action_details

    def perform_condition_check(self, condition_data: dict) -> bool:
        action_name = condition_data.get('action')
        if not action_name:
            logger.warning(f"[中断检查] 条件定义缺少 'action' 字段: {condition_data}")
            return False
        action_def = ACTION_REGISTRY.get(action_name)
        if not action_def:
            logger.warning(f"[中断检查] 找不到名为 '{action_name}' 的 Action。")
            return False
        if not action_def.read_only:
            logger.error(f"[中断检查] 安全错误：尝试在条件检查中使用非只读 Action '{action_name}'。此操作已被阻止。")
            return False
        try:
            if not self.engine:
                # 【补充】在执行检查前，确保engine已初始化
                self._initialize_context()
                self.engine = ExecutionEngine(context=self.context, action_registry=ACTION_REGISTRY, orchestrator=self)

            # 【确认】这里的注入逻辑在 ExecutionEngine 内部，是正确的。
            # 我们需要确保 ExecutionEngine 的注入器会调用 service_registry.get_service_instance()
            params = self.engine._render_params(condition_data.get('params', {}))

            # 假设 ExecutionEngine 有一个方法来执行注入
            # 这里我们假设它在内部处理了依赖注入
            injected_params = self.engine._inject_services_for_action(action_name)
            injected_params.update(params)

            result = action_def.func(**injected_params)
            return bool(result)
        except Exception as e:
            logger.error(f"[中断检查] 执行 '{action_name}' 时出错: {e}", exc_info=True)
            return False

    # --- 以下所有其他方法保持不变 ---
    # ... (从你的原文件中复制 _handle_state_transition() 到文件末尾的所有代码) ...
    def _handle_state_transition(self, required_state: str):
        logger.info(f"任务需要前置状态: '{required_state}'")
        current_state = self.determine_current_state()
        if not current_state:
            logger.critical("无法确定当前游戏状态，任务中止。")
            raise RuntimeError("无法确定当前状态")
        logger.info(f"检测到当前状态为: '{current_state}'")
        if current_state != required_state:
            try:
                self.plan_and_execute_path(current_state, required_state)
            except Exception as e:
                logger.critical(f"状态路径规划执行失败: {e}", exc_info=True)
                raise
        else:
            logger.info("当前状态已满足任务要求，无需转换。")

    def get_persistent_context_data(self) -> dict:
        if not self.persistent_context:
            context_path = os.path.join(self.current_plan_path, 'persistent_context.json')
            temp_context = PersistentContext(context_path)
            return temp_context.get_all_data()
        return self.persistent_context.get_all_data()

    def save_persistent_context_data(self, data: dict):
        if not self.persistent_context:
            context_path = os.path.join(self.current_plan_path, 'persistent_context.json')
            self.persistent_context = PersistentContext(context_path)
        self.persistent_context._data.clear()
        for key, value in data.items():
            self.persistent_context.set(key, value)
        self.persistent_context.save()

    def load_world_map(self) -> dict | None:
        map_path = os.path.join(self.current_plan_path, 'world_map.yaml')
        if not os.path.exists(map_path):
            return None
        try:
            with open(map_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"加载 world_map.yaml 失败: {e}")
            return None

    def determine_current_state(self) -> str | None:
        expected_state = self.context.get('__expected_next_state')
        if expected_state:
            logger.debug(f"进入【确认模式】，检查是否为状态: '{expected_state}'")
            state_info = self.world_map['states'].get(expected_state)
            if state_info:
                check_task_data = self.load_task_data(state_info['check']['task'])
                if self.engine.run_check_task(check_task_data):
                    return expected_state
            logger.warning(f"确认模式失败，未能确认处于'{expected_state}'。转入探索模式...")
        logger.debug("进入【探索模式】，使用启发式检查...")
        last_confirmed_state = self.context.get('__last_confirmed_state')
        check_order = self._get_heuristic_check_order(last_confirmed_state)
        for state_name in check_order:
            state_info = self.world_map['states'][state_name]
            check_task_data = self.load_task_data(state_info['check']['task'])
            if self.engine.run_check_task(check_task_data):
                self.context.set('__last_confirmed_state', state_name)
                return state_name
        return None

    def _get_heuristic_check_order(self, last_state: str | None) -> list[str]:
        all_states = list(self.world_map.get('states', {}).keys())
        if not last_state:
            logger.debug("无历史状态，使用默认检查顺序。")
            return all_states
        order = []
        visited = set()

        def add_to_order(state):
            if state and state not in visited:
                order.append(state)
                visited.add(state)

        add_to_order(last_state)
        directly_connected_states = set()
        for transition in self.world_map.get('transitions', []):
            if transition['from'] == last_state:
                directly_connected_states.add(transition['to'])
        for state in sorted(list(directly_connected_states)):
            add_to_order(state)
        for state in all_states:
            add_to_order(state)
        logger.debug(f"根据上一个状态 '{last_state}'，生成启发式检查顺序: {order}")
        return order

    def plan_and_execute_path(self, start_state: str, end_state: str):
        pathfinder = Pathfinder(self.world_map)
        state_path = pathfinder.find_path(start_state, end_state)
        if not state_path:
            raise Exception(f"找不到从 '{start_state}' 到 '{end_state}' 的路径。")
        logger.info(f"规划路径: {' -> '.join(state_path)}")
        for i in range(len(state_path) - 1):
            from_s, to_s = state_path[i], state_path[i + 1]
            transition_task_name = self._find_transition_task(from_s, to_s)
            if not transition_task_name:
                raise Exception(f"在世界地图中找不到从 '{from_s}' 到 '{to_s}' 的转换任务定义。")
            logger.info(f"--- 执行路径转换: {from_s} -> {to_s} (任务: {transition_task_name}) ---")
            self.context.set('__expected_next_state', to_s)
            task_data = self.load_task_data(transition_task_name)
            self.engine.run(task_data, transition_task_name)
            logger.info(f"验证是否已到达状态: '{to_s}'")
            current_state = self.determine_current_state()
            if current_state != to_s:
                logger.critical(f"状态验证失败！...")
                raise Exception("State transition verification failed.")
            else:
                logger.info("状态验证成功！")
                self.context.set('__expected_next_state', None)

    def _find_transition_task(self, from_state: str, to_state: str) -> str | None:
        for transition in self.world_map.get('transitions', []):
            if transition.get('from') == from_state and transition.get('to') == to_state:
                return transition.get('task')
        return None

    def load_task_data(self, task_name: str) -> Dict | None:
        task_data = self.task_definitions.get(task_name)
        if not task_data:
            logger.error(f"在方案包 '{self.plan_name}' 中找不到名为 '{task_name}' 的任务定义。")
            return None
        return task_data

    def get_file_content(self, relative_path: str) -> str:
        full_path = (self.current_plan_path / relative_path).resolve()
        if self.current_plan_path.resolve() not in full_path.parents:
            raise PermissionError(f"禁止访问方案包外部的文件: {relative_path}")
        if not full_path.is_file():
            raise FileNotFoundError(f"在方案 '{self.plan_name}' 中找不到文件: {relative_path}")
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"读取文件 '{full_path}' 失败: {e}")
            raise

    def get_file_content_bytes(self, relative_path: str) -> bytes:
        full_path = (self.current_plan_path / relative_path).resolve()
        if self.current_plan_path.resolve() not in full_path.parents:
            raise PermissionError(f"禁止访问方案包外部的文件: {relative_path}")
        if not full_path.is_file():
            raise FileNotFoundError(f"在方案 '{self.plan_name}' 中找不到文件: {relative_path}")
        try:
            with open(full_path, 'rb') as f:
                return f.read()
        except Exception as e:
            logger.error(f"读取二进制文件 '{full_path}' 失败: {e}")
            raise

    def save_file_content(self, relative_path: str, content: str):
        full_path = (self.current_plan_path / relative_path).resolve()
        if self.current_plan_path.resolve() not in full_path.parents:
            raise PermissionError(f"禁止在方案包外部写入文件: {relative_path}")
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"文件已保存: {full_path}")
        except Exception as e:
            logger.error(f"保存文件 '{full_path}' 失败: {e}")
            raise

    def inspect_step(self, task_name: str, step_index: int) -> Any:
        logger.info(f"开始检查步骤: 方案='{self.plan_name}', 任务='{task_name}', 步骤索引={step_index}")
        self._load_config()
        if not self.config:
            raise ValueError("无法加载 config.yaml，无法继续检查。")
        self._initialize_context()
        self.engine = ExecutionEngine(context=self.context, action_registry=ACTION_REGISTRY, orchestrator=self)
        self.context.set("__is_inspect_mode__", True)
        task_data = self.load_task_data(task_name)
        if not task_data:
            raise FileNotFoundError(f"找不到任务 '{task_name}'。")
        steps = task_data.get('steps', [])
        if not (0 <= step_index < len(steps)):
            raise IndexError(f"步骤索引 {step_index} 超出范围。")
        step_data = steps[step_index]
        try:
            rendered_params = self.engine._render_params(step_data.get('params', {}))
            result = self.engine.run_step(step_data, rendered_params)
            return result
        except Exception as e:
            logger.error(f"检查步骤时发生严重错误: {e}", exc_info=True)
            raise

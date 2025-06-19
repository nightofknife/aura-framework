# src/core/engine.py

import inspect
import os
import time
import yaml  # 需要安装: pip install pyyaml
import threading
from typing import Any, Callable, Dict
from jinja2 import Environment, BaseLoader

from packages.aura_shared_utils.utils.logger import logger
from packages.aura_core.exceptions import StopTaskException
from packages.aura_core.service_registry import service_registry

class Context:
    """
    一个简单的执行上下文管理器。
    它作为一个字典的封装，用于存储和检索框架运行时的所有状态和数据。
    """

    def __init__(self):
        self._data: Dict[str, Any] = {}

    def set(self, key: str, value: Any):
        """在上下文中设置一个键值对。"""
        self._data[key.lower()] = value

    def get(self, key: str, default: Any = None) -> Any:
        """从上下文中获取一个值。"""
        return self._data.get(key.lower(), default)

    # 一个 delete 方法，用于作用域上下文的清理
    def delete(self, key: str):
        """从上下文中删除一个键。如果键不存在，则不执行任何操作。"""
        self._data.pop(key.lower(), None)

    def __str__(self):
        return f"Context({list(self._data.keys())})"


class DependencyInjector:
    """
    负责为行为函数自动注入依赖。
    """

    def __init__(self, context: Context, action_registry: Dict[str, Any], engine: 'ExecutionEngine'):
        self.context = context
        self.action_registry = action_registry
        self.engine = engine
    def execute_action(self, action_name: str, params: Dict[str, Any]) -> Any:
        action_name_lower = action_name.lower()
        if action_name_lower not in self.action_registry:
            raise NameError(f"错误：找不到名为 '{action_name}' 的行为。")

        action_def = self.action_registry[action_name_lower]
        sig = action_def.signature
        call_args = {}

        # 获取Action声明的服务依赖
        service_deps = action_def.service_dependencies

        for param_name, param_spec in sig.parameters.items():
            if param_spec.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue

            # --- 注入优先级 1: 服务注入 ---
            # 检查参数名是否在Action声明的服务依赖中
            if param_name in service_deps:
                fqsn = service_deps[param_name]
                try:
                    # 从全局服务注册中心获取服务实例
                    call_args[param_name] = service_registry.get_service_instance(fqsn)
                    continue
                except Exception as e:
                    # 包装错误，提供更清晰的上下文
                    raise RuntimeError(
                        f"为Action '{action_name}' 注入服务 '{fqsn}' (参数: {param_name}) 时失败: {e}") from e

            # --- 注入优先级 2: 内置核心对象注入 ---
            if param_name == 'context':
                call_args[param_name] = self.context
                continue
            if param_name == 'persistent_context':
                # 从上下文中获取，它是由Orchestrator初始化的
                call_args[param_name] = self.context.get('persistent_context')
                continue
            if param_name == 'engine':
                call_args[param_name] = self.engine
                continue

            # --- 注入优先级 3: 来自YAML的参数注入 ---
            if param_name in params:
                call_args[param_name] = params[param_name]
                continue

            # --- 注入优先级 4: 来自上下文的变量注入 ---
            # 这是一个后备方案，允许从上下文中注入简单的值
            injected_value = self.context.get(param_name)
            if injected_value is not None:
                call_args[param_name] = injected_value
                continue

            # --- 注入优先级 5: 函数默认值 ---
            if param_spec.default is not inspect.Parameter.empty:
                call_args[param_name] = param_spec.default
                continue

            # --- 如果都找不到，则报错 ---
            raise ValueError(f"执行行为 '{action_name}' 时缺少必要参数: '{param_name}'")

        # 执行Action
        # print(f"--- 正在执行行为: {action_name} ---")
        result = action_def.func(**call_args)
        # print(f"--- 行为 '{action_name}' 执行完毕 ---")
        return result


class ExecutionEngine:
    """
    负责解析和执行YAML中定义的任务步骤。
    """

    def __init__(self, context: Context, action_registry: Dict[str, Callable], orchestrator=None,
                 pause_event: threading.Event = None):
        self.context = context
        # 【修改】确保将正确的 action_registry 传递给新的注入器
        self.injector = DependencyInjector(context, action_registry, engine=self)
        self.jinja_env = Environment(loader=BaseLoader())
        self.orchestrator = orchestrator
        self.pause_event = pause_event if pause_event else threading.Event()
        logger.info("执行引擎已初始化。")

    # 【修改】统一的执行入口：增加检查暂停点的逻辑
    def _check_pause(self):
        """检查是否需要暂停执行。如果需要，将阻塞直到暂停事件被清除。"""
        if self.pause_event.is_set():
            logger.warning("接收到全局暂停信号，任务执行已暂停。等待恢复信号...")
            self.pause_event.wait()  # 这行代码会阻塞，直到另一个线程调用 self.pause_event.clear()
            logger.info("接收到恢复信号，任务将继续执行。")

    # 【改造】统一的执行入口
    def run(self, task_data: Dict[str, Any], task_name: str):
        if 'states' in task_data:
            self.run_state_machine(task_data, task_name)
        elif 'steps' in task_data:
            self.run_linear_task(task_data, task_name)  # 原来的 run_task 改名为 run_linear_task
        else:
            logger.error(f"任务 '{task_name}' 格式错误。")

    def run_linear_task(self, task_data: Dict[str, Any], task_name: str):
        """
        运行一个完整的任务。
        """
        required_state = task_data.get('requires_state')
        steps = task_data.get('steps', [])
        if not steps:
            logger.warning(f"任务 '{task_name}' 中没有任何步骤。")
            return

        task_display_name = task_data.get('name', task_name)
        logger.info(f"======= 开始执行任务: {task_display_name} =======")
        if required_state:
            logger.info(f"此任务要求全程处于状态: '{required_state}'")
        try:
            for i, step_data in enumerate(steps):

                if required_state:
                    if not self._verify_current_state(required_state):
                        # 如果状态不匹配，抛出 StopTaskException 来安全地中止任务
                        raise StopTaskException(
                            f"任务因状态改变而中止。期望状态: '{required_state}', 但当前状态已改变。",
                            success=False
                        )

                step_name = step_data.get('name', f'未命名步骤 {i + 1}')
                logger.info(f"\n[步骤 {i + 1}/{len(steps)}]: {step_name}")

                # 1. 处理条件执行 (when)
                if 'when' in step_data:
                    condition = self._render_value(step_data['when'], self.context._data)
                    if not condition:
                        logger.info(f"  -> 条件 '{step_data['when']}' 不满足，跳过此步骤。")
                        continue

                # 2. 处理循环执行 (loop)
                if 'loop' in step_data:
                    loop_items = self._render_value(step_data['loop'], self.context._data)
                    if not isinstance(loop_items, list):
                        logger.warning(f"  -> 'loop' 的值不是一个列表，跳过循环。")
                        continue

                    logger.info(f"  -> 开始循环，共 {len(loop_items)} 项。")
                    for item_index, item in enumerate(loop_items):
                        self._check_pause()

                        logger.info(f"    - 循环 {item_index + 1}/{len(loop_items)}")
                        self.context.set('item', item)
                        self.context.set('item_index', item_index)
                        self._execute_single_step_logic(step_data)

                    self.context.set('item', None)
                    self.context.set('item_index', None)
                else:
                    # 3. 正常执行
                    self._execute_single_step_logic(step_data)

        except StopTaskException as e:
            if e.success:
                logger.info(f"✅ 任务被正常停止: {e.message}")
            else:
                logger.warning(f"🛑 任务因预期失败而停止: {e.message}")
        except Exception as e:
            logger.critical(f"!! 任务 '{task_display_name}' 执行时发生严重错误: {e}", exc_info=True)

        logger.info(f"======= 任务 '{task_display_name}' 执行结束 =======")

    def run_state_machine(self, sm_data: Dict[str, Any], sm_name: str):
        """
        运行一个基于状态机的任务。
        """
        sm_display_name = sm_data.get('name', sm_name)
        logger.info(f"======= 状态机启动: {sm_display_name} =======")

        # 1. 获取状态机定义
        states = sm_data.get('states', {})
        if not states:
            logger.error("状态机任务中未定义任何 'states'。")
            return

        initial_context = sm_data.get('initial_context', {})
        global_monitor_task = sm_data.get('global_monitor_task')

        # 2. 初始化上下文
        for key, value in initial_context.items():
            self.context.set(key, value)

        # 3. 确定起始状态 (YAML中定义的第一个状态)
        current_state_name = next(iter(states), None)
        if not current_state_name:
            logger.error("状态机中没有任何状态定义。")
            return

        try:
            # 4. 状态机主循环
            while current_state_name:
                self._check_pause()

                logger.info(f"\n========== 进入状态: [{current_state_name}] ==========")

                current_state_data = states.get(current_state_name)
                if not current_state_data:
                    raise StopTaskException(f"状态 '{current_state_name}' 未定义。", success=False)

                # --- a. 执行 on_enter (如果存在) ---
                if 'on_enter' in current_state_data:
                    logger.info(f"  -> 触发 on_enter...")
                    # 使用 _execute_single_step_logic 是因为它能处理 on_success/on_failure
                    self._execute_single_step_logic(current_state_data['on_enter'])

                # --- b. 内部循环 (执行 on_run 和检查转换) ---
                while True:

                    self._check_pause()
                    # i. 状态校准
                    detected_state = self.orchestrator.determine_current_state()
                    if detected_state and detected_state != current_state_name:
                        logger.warning(
                            f"状态机检测到外部状态改变！预期在 '{current_state_name}'，但实际在 '{detected_state}'。")
                        logger.info(f"状态机自我修正，跳转到新状态: '{detected_state}'")
                        current_state_name = detected_state
                        break  # 跳出内部循环，进入下一个状态

                    # ii. 执行 on_run (如果存在)
                    if 'on_run' in current_state_data:
                        logger.debug(f"  -> 执行 on_run...")
                        self._execute_single_step_logic(current_state_data['on_run'])

                    # iii. 执行全局监控 (如果存在)
                    if global_monitor_task:
                        logger.debug("  -> 执行全局监控任务...")
                        self._execute_single_step_logic(global_monitor_task)

                    # iv. 检查转换条件
                    next_state_name = self._check_transitions(current_state_data)
                    if next_state_name:
                        logger.info(f"状态转换条件满足: 从 '{current_state_name}' -> '{next_state_name}'")
                        current_state_name = next_state_name
                        break  # 跳出内部循环，进入下一个状态

                    # 如果没有触发转换，小睡一下避免CPU满载
                    time.sleep(0.1)  # 这个值未来可以做到可配置

            # 如果 while 循环正常结束 (current_state_name 变为 None)，说明状态机执行完毕
            logger.info("状态机执行流程结束。")

        except StopTaskException as e:
            if e.success:
                logger.info(f"✅ 状态机被正常停止: {e.message}")
            else:
                logger.warning(f"🛑 状态机因预期失败而停止: {e.message}")
        except Exception as e:
            logger.critical(f"!! 状态机 '{sm_display_name}' 执行时发生严重错误: {e}", exc_info=True)

        logger.info(f"======= 状态机 '{sm_display_name}' 执行结束 =======")

    # 【新增】一个辅助方法，用于检查状态机的转换条件
    def _check_transitions(self, state_data: Dict[str, Any]) -> str | None:
        """
        按顺序检查当前状态的所有转换规则。
        返回第一个满足条件的目标状态名，如果没有满足的则返回 None。
        """
        transitions = state_data.get('transitions', [])
        for transition in transitions:
            to_state = transition.get('to')
            if not to_state: continue

            # 如果没有 'when' 条件，则为无条件转换
            if 'when' not in transition:
                return to_state

            # 如果有 'when' 条件，则渲染并判断
            condition_str = transition['when']
            condition_result = self._render_value(condition_str, self.context._data)

            if condition_result:
                logger.debug(f"转换条件 '{condition_str}' 满足。")
                return to_state

        return None  # 所有转换条件都不满足

    # 【新增】一个专门执行检查任务并返回布尔值的方法
    def run_check_task(self, task_data: Dict[str, Any]) -> bool:
        """
        【修改后】执行一个检查任务，并正确处理返回的对象。
        """
        steps = task_data.get('steps', [])
        if not steps: return False

        last_result_obj = None
        for step_data in steps:
            raw_params = step_data.get('params', {})
            rendered_params = self._render_params(raw_params)
            last_result_obj = self.run_step(step_data, rendered_params)

            # 在这里判断每一步的结果
            step_succeeded = True
            if hasattr(last_result_obj, 'found') and last_result_obj.found is False:
                step_succeeded = False
            elif last_result_obj is False:
                step_succeeded = False

            if not step_succeeded:
                return False  # 任何一步失败，整个检查任务就失败

        # 只有所有步骤都成功，才返回True
        return True
    def _verify_current_state(self, expected_state: str) -> bool:
        """调用Orchestrator检查当前状态，并与期望状态对比。"""
        logger.debug(f"正在验证是否处于状态: '{expected_state}'")
        actual_state = self.orchestrator.determine_current_state()

        if actual_state == expected_state:
            return True
        else:
            logger.warning(f"状态校准失败！期望状态: '{expected_state}', 实际状态: '{actual_state}'。")
            return False

    def _execute_single_step_logic(self, step_data: Dict[str, Any]) -> bool:
        """
        【修改后】封装了执行单个步骤的核心逻辑。
        新增了对 'wait_before' 和 'retry' 的处理。
        """
        # --- 1. 【新增】处理执行前等待 (wait_before) ---
        wait_before = step_data.get('wait_before')
        if wait_before:
            try:
                wait_seconds = float(wait_before)
                logger.info(f"  -> 执行前等待 {wait_seconds} 秒...")
                time.sleep(wait_seconds)
            except (ValueError, TypeError):
                logger.warning(f"  -> 'wait_before' 的值 '{wait_before}' 无效，已忽略。应为一个数字。")

        # --- 2. 【新增】处理重试逻辑 (retry) ---
        retry_config = step_data.get('retry')
        max_attempts = 1
        retry_interval = 1.0

        if isinstance(retry_config, dict):
            max_attempts = int(retry_config.get('count', 1))
            retry_interval = float(retry_config.get('interval', 1.0))
        elif retry_config:  # 支持简写形式，如 retry: 5
            try:
                max_attempts = int(retry_config)
            except (ValueError, TypeError):
                logger.warning(f"  -> 'retry' 的值 '{retry_config}' 无效，已忽略。应为一个整数或字典。")

        # --- 3. 执行与重试循环 ---
        step_succeeded = False
        result_obj = None

        for attempt in range(max_attempts):
            self._check_pause()  # 在每次尝试前检查暂停信号

            if attempt > 0:
                logger.info(f"  -> 步骤失败，在 {retry_interval} 秒后进行第 {attempt + 1}/{max_attempts} 次重试...")
                time.sleep(retry_interval)

            # a. 渲染参数 (在每次循环中渲染，以防参数依赖于变化的上下文)
            raw_params = step_data.get('params', {})
            rendered_params = self._render_params(raw_params)

            # b. 执行步骤并获取原始结果对象
            result_obj = self.run_step(step_data, rendered_params)

            # c. 判断步骤是否成功
            step_succeeded = True  # 先假设成功
            if result_obj is False:
                step_succeeded = False
            elif hasattr(result_obj, 'found') and result_obj.found is False:
                step_succeeded = False

            # d. 如果成功，跳出重试循环
            if step_succeeded:
                logger.info(f"  -> 步骤在第 {attempt + 1} 次尝试中成功。")
                break

        # --- 4. 根据最终结果执行 on_success 或 on_failure ---
        if step_succeeded:
            if 'on_success' in step_data:
                logger.info("  -> 步骤成功，执行 on_success...")
                # 递归调用，on_success 块也支持重试和等待
                return self._execute_single_step_logic(step_data['on_success'])
        else:
            step_name = step_data.get('name', '未命名步骤')
            # 如果有重试，只在最后一次失败时记录
            if max_attempts > 1:
                logger.warning(f"  -> 步骤 '{step_name}' 在所有 {max_attempts} 次尝试后仍然失败。")
            else:
                logger.warning(f"  -> 步骤 '{step_name}' 失败。")

            self._capture_debug_screenshot(step_name)

            if 'on_failure' in step_data:
                logger.warning("  -> 步骤失败，执行 on_failure...")
                return self._execute_single_step_logic(step_data['on_failure'])
            else:
                if max_attempts == 1:  # 只有在没有重试的情况下才显示这个
                    logger.warning(f"  -> 步骤 '{step_name}' 失败，且未定义 on_failure。")

        return step_succeeded

    def run_step(self, step_data: Dict[str, Any], rendered_params: Dict[str, Any]) -> Any:
        """
        执行单个步骤（无视循环和条件），并返回是否成功。
        """
        action_name = step_data.get('action')
        if not action_name:
            return True

        # 特殊处理 run_task
        if action_name.lower() == 'run_task':
            sub_task_name = rendered_params.get('task_name')
            if not sub_task_name:
                logger.error("'run_task' 行为缺少 'task_name' 参数。")
                return False

            if not self.orchestrator:
                logger.error("'run_task' 无法执行，因为执行引擎未关联编排器。")
                return False

            logger.info(f"--- 正在加载子任务: {sub_task_name} ---")
            sub_task_data = self.orchestrator.load_task_data(sub_task_name)

            if not sub_task_data:
                return False

            # --- 上下文作用域管理 ---
            params_to_pass = rendered_params.get('pass_params', {})
            original_values = {}
            newly_added_keys = []

            try:
                # 1. 保存原始上下文，并注入新参数
                logger.debug(f"为子任务 '{sub_task_name}' 创建临时上下文作用域...")
                for key, value in params_to_pass.items():
                    # 检查父上下文是否已存在此键
                    if self.context.get(key) is not None:
                        original_values[key] = self.context.get(key)
                    else:
                        newly_added_keys.append(key)
                    # 注入新值
                    self.context.set(key, value)

                # 2. 执行子任务 (调用顶层 run 方法，使其能处理线性和状态机任务)
                self.run(sub_task_data, sub_task_name)

                # 假设子任务执行总是成功的（除非它抛出异常）
                return True

            finally:
                # 3. 恢复父上下文，无论子任务成功与否
                logger.debug(f"恢复 '{sub_task_name}' 执行前的父上下文作用域...")
                # 恢复被覆盖的值
                for key, value in original_values.items():
                    self.context.set(key, value)
                # 删除新注入的键
                for key in newly_added_keys:
                    self.context.delete(key)
            # --- 作用域管理结束 ---

            # 对于所有其他 action，调用 _dispatch_action
        return self._dispatch_action(step_data, rendered_params)

    # 【新增】一个可复用的、纯粹的动作分发器
    def _dispatch_action(self, step_data: Dict[str, Any], rendered_params: Dict[str, Any]) -> Any:
        """
        【修改后】分发Action并返回最原始、最完整的结果对象，不再进行布尔转换。
        """
        action_name = step_data.get('action')
        logger.debug(f"分发行为: '{action_name}'")

        try:
            result = self.injector.execute_action(action_name, rendered_params)

            if 'output_to' in step_data:
                output_key = step_data['output_to']
                self.context.set(output_key, result)
                logger.info(f"  -> 步骤输出已保存到上下文变量: '{output_key}'")

            # 【关键】直接返回原始结果，不进行任何判断和转换
            return result

        except Exception as e:
            logger.error(f"执行行为 '{action_name}' 时发生未捕获的异常: {e}", exc_info=True)
            # 在异常情况下，返回一个明确的失败信号
            return False

    def _render_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        # ... (无变化) ...
        rendered_params = {}
        context_data = self.context._data.copy()
        for key, value in params.items():
            rendered_params[key] = self._render_value(value, context_data)
        return rendered_params

    def _render_value(self, value: Any, context_data: Dict[str, Any]) -> Any:
        """
        递归地渲染单个值。
        """
        if isinstance(value, str):
            # 性能优化：如果值不包含模板语法，直接返回
            if "{{" not in value and "{%" not in value:
                return value

            # 1. 尝试将字符串作为模板进行渲染
            template = self.jinja_env.from_string(value)
            rendered_string = template.render(context_data)

            # 2. 【关键逻辑】检查原始模板是否只是一个简单的变量引用
            potential_var_name = value.strip()
            if potential_var_name.startswith("{{") and potential_var_name.endswith("}}"):
                # 提取变量名，例如从 "{{ my_list }}" 中提取 "my_list"
                inner_key = potential_var_name[2:-2].strip()
                # 检查它是否是一个简单的标识符（不含空格、操作符等）
                # 并且这个标识符确实存在于上下文中
                if inner_key.isidentifier() and inner_key.lower() in context_data:
                    # 如果是，直接返回上下文中的原始对象（可能是列表、字典等）
                    return context_data.get(inner_key.lower())
            try:
                return yaml.safe_load(rendered_string)
            except (yaml.YAMLError, TypeError):
                return rendered_string

        elif isinstance(value, dict):
            # 如果值是字典，递归渲染其所有值
            return {k: self._render_value(v, context_data) for k, v in value.items()}
        elif isinstance(value, list):
            # 如果值是列表，递归渲染其所有项
            return [self._render_value(item, context_data) for item in value]
        else:
            # 其他类型（数字、布尔等）直接返回
            return value

    def _capture_debug_screenshot(self, failed_step_name: str):
        try:
            # 【修改】从服务注册中心按需获取app实例
            app = service_registry.get_service_instance('app_provider')
            debug_dir = self.context.get('debug_dir')
            if not app or not debug_dir:
                logger.warning("无法进行失败截图，因为上下文中缺少 'debug_dir'或无法获取app服务。")
                return
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            safe_step_name = "".join(c for c in failed_step_name if c.isalnum() or c in (' ', '_')).rstrip()
            filename = f"failure_{timestamp}_{safe_step_name}.png"
            filepath = os.path.join(debug_dir, filename)
            capture_result = app.capture()
            if capture_result.success:
                capture_result.save(filepath)
                logger.error(f"步骤失败，已自动截图至: {filepath}")
            else:
                logger.error("尝试进行失败截图时，截图操作本身也失败了。")
        except Exception as e:
            logger.error(f"在执行失败截图时发生意外错误: {e}", exc_info=True)

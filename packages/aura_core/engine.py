# packages/aura_core/engine.py (最终修正版)

import inspect
import os
import time
import yaml
import threading
from typing import Any, Callable, Dict
# 【修改】导入新需要的模块
from ast import literal_eval
from jinja2 import Environment, BaseLoader, UndefinedError

from packages.aura_core.context import Context
from packages.aura_shared_utils.utils.logger import logger
from packages.aura_core.exceptions import StopTaskException
from packages.aura_core.api import service_registry, ACTION_REGISTRY, ActionDefinition
from packages.aura_core.middleware import middleware_manager


class DependencyInjector:
    def __init__(self, context: Context, engine: 'ExecutionEngine'):
        self.context = context
        self.engine = engine

    def _prepare_action_arguments(self, action_def: ActionDefinition, params: Dict[str, Any]) -> Dict[str, Any]:
        sig = action_def.signature
        call_args = {}
        service_deps = action_def.service_deps

        for param_name, param_spec in sig.parameters.items():
            if param_spec.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if param_name in service_deps:
                fqsn = service_deps[param_name]
                try:
                    call_args[param_name] = service_registry.get_service_instance(fqsn)
                    continue
                except Exception as e:
                    raise RuntimeError(
                        f"为Action '{action_def.name}' 注入服务 '{fqsn}' (参数: {param_name}) 时失败: {e}") from e
            if param_name == 'context':
                call_args[param_name] = self.context
                continue
            if param_name == 'persistent_context':
                call_args[param_name] = self.context.get('persistent_context')
                continue
            if param_name == 'engine':
                call_args[param_name] = self.engine
                continue
            if param_name in params:
                call_args[param_name] = params[param_name]
                continue
            injected_value = self.context.get(param_name)
            if injected_value is not None:
                call_args[param_name] = injected_value
                continue
            if param_spec.default is not inspect.Parameter.empty:
                call_args[param_name] = param_spec.default
                continue
            raise ValueError(f"执行行为 '{action_def.name}' 时缺少必要参数: '{param_name}'")
        return call_args

    def _final_action_executor(self, action_def: ActionDefinition, context: Context, params: Dict[str, Any]) -> Any:
        call_args = self._prepare_action_arguments(action_def, params)
        return action_def.func(**call_args)

    def execute_action(self, action_name: str, params: Dict[str, Any]) -> Any:
        action_name_lower = action_name.lower()
        action_def = ACTION_REGISTRY.get(action_name_lower)
        if not action_def:
            raise NameError(f"错误：找不到名为 '{action_name}' 的行为。")

        return middleware_manager.process(
            action_def=action_def,
            context=self.context,
            params=params,
            final_handler=self._final_action_executor
        )


class ExecutionEngine:
    def __init__(self, context: Context, orchestrator=None, pause_event: threading.Event = None):
        self.context = context
        self.injector = DependencyInjector(context, engine=self)
        self.jinja_env = Environment(loader=BaseLoader())
        self.orchestrator = orchestrator
        self.pause_event = pause_event if pause_event else threading.Event()
        self._initialize_middlewares()
        logger.info("执行引擎已初始化。")

    def _initialize_middlewares(self):
        pass

    def _check_pause(self):
        if self.pause_event.is_set():
            logger.warning("接收到全局暂停信号，任务执行已暂停。等待恢复信号...")
            self.pause_event.wait()
            logger.info("接收到恢复信号，任务将继续执行。")

    def run(self, task_data: Dict[str, Any], task_name: str):
        if 'states' in task_data:
            self.run_state_machine(task_data, task_name)
        elif 'steps' in task_data:
            self.run_linear_task(task_data, task_name)
        else:
            logger.error(f"任务 '{task_name}' 格式错误。")

    def run_linear_task(self, task_data: Dict[str, Any], task_name: str):
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
                # 【修改】将 step_data 检查提前，避免在渲染 'when' 之前就崩溃
                if not isinstance(step_data, dict):
                    logger.error(f"步骤 {i + 1} 的格式无效，不是一个字典。已跳过。")
                    continue

                if required_state:
                    if not self._verify_current_state(required_state):
                        raise StopTaskException(f"任务因状态改变而中止。期望状态: '{required_state}', 但当前状态已改变。",
                                                success=False)
                step_name = step_data.get('name', f'未命名步骤 {i + 1}')
                logger.info(f"\n[步骤 {i + 1}/{len(steps)}]: {step_name}")

                if 'when' in step_data:
                    # 【修改】现在 _render_value 会安全地处理 UndefinedError
                    condition = self._render_value(step_data['when'], self.context._data)
                    if not condition:
                        logger.info(f"  -> 条件 '{step_data['when']}' 不满足，跳过此步骤。")
                        continue

                # 【修改】将 continue_on_failure 逻辑移到 _execute_single_step_logic 之外
                # 以便更好地控制整个任务的流程
                step_succeeded = self._execute_single_step_logic(step_data)

                # 如果步骤失败且没有设置 continue_on_failure，则中止任务
                if not step_succeeded and not step_data.get('continue_on_failure', False):
                    raise StopTaskException(f"步骤 '{step_name}' 失败且未设置 continue_on_failure，任务中止。",
                                            success=False)

        except StopTaskException as e:
            if e.success:
                logger.info(f"✅ 任务被正常停止: {e.message}")
            else:
                logger.warning(f"🛑 任务因预期失败而停止: {e.message}")
        except Exception as e:
            # 【修改】修复日志调用，移除不支持的 exc_info 参数
            # 同时使用 logger.error 而不是 logger.info
            logger.error(f"!! 任务 '{task_display_name}' 执行时发生严重错误: {e}")
            # 如果需要堆栈跟踪，可以单独打印
            import traceback
            logger.debug(traceback.format_exc())

        logger.info(f"======= 任务 '{task_display_name}' 执行结束 =======")

    # ... (run_state_machine, _check_transitions, run_check_task, _verify_current_state 保持不变) ...
    def run_state_machine(self, sm_data: Dict[str, Any], sm_name: str):
        sm_display_name = sm_data.get('name', sm_name)
        logger.info(f"======= 状态机启动: {sm_display_name} =======")
        states = sm_data.get('states', {})
        if not states:
            logger.error("状态机任务中未定义任何 'states'。")
            return
        initial_context = sm_data.get('initial_context', {})
        global_monitor_task = sm_data.get('global_monitor_task')
        for key, value in initial_context.items():
            self.context.set(key, value)
        current_state_name = next(iter(states), None)
        if not current_state_name:
            logger.error("状态机中没有任何状态定义。")
            return
        try:
            while current_state_name:
                self._check_pause()
                logger.info(f"\n========== 进入状态: [{current_state_name}] ==========")
                current_state_data = states.get(current_state_name)
                if not current_state_data:
                    raise StopTaskException(f"状态 '{current_state_name}' 未定义。", success=False)
                if 'on_enter' in current_state_data:
                    logger.info(f"  -> 触发 on_enter...")
                    self._execute_single_step_logic(current_state_data['on_enter'])
                while True:
                    self._check_pause()
                    detected_state = self.orchestrator.determine_current_state()
                    if detected_state and detected_state != current_state_name:
                        logger.warning(
                            f"状态机检测到外部状态改变！预期在 '{current_state_name}'，但实际在 '{detected_state}'。")
                        logger.info(f"状态机自我修正，跳转到新状态: '{detected_state}'")
                        current_state_name = detected_state
                        break
                    if 'on_run' in current_state_data:
                        logger.debug(f"  -> 执行 on_run...")
                        self._execute_single_step_logic(current_state_data['on_run'])
                    if global_monitor_task:
                        logger.debug("  -> 执行全局监控任务...")
                        self._execute_single_step_logic(global_monitor_task)
                    next_state_name = self._check_transitions(current_state_data)
                    if next_state_name:
                        logger.info(f"状态转换条件满足: 从 '{current_state_name}' -> '{next_state_name}'")
                        current_state_name = next_state_name
                        break
                    time.sleep(0.1)
            logger.info("状态机执行流程结束。")
        except StopTaskException as e:
            if e.success:
                logger.info(f"✅ 状态机被正常停止: {e.message}")
            else:
                logger.warning(f"🛑 状态机因预期失败而停止: {e.message}")
        except Exception as e:
            logger.error(f"!! 状态机 '{sm_display_name}' 执行时发生严重错误: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        logger.info(f"======= 状态机 '{sm_display_name}' 执行结束 =======")

    def _check_transitions(self, state_data: Dict[str, Any]) -> str | None:
        transitions = state_data.get('transitions', [])
        for transition in transitions:
            to_state = transition.get('to')
            if not to_state: continue
            if 'when' not in transition:
                return to_state
            condition_str = transition['when']
            condition_result = self._render_value(condition_str, self.context._data)
            if condition_result:
                logger.debug(f"转换条件 '{condition_str}' 满足。")
                return to_state
        return None

    def run_check_task(self, task_data: Dict[str, Any]) -> bool:
        steps = task_data.get('steps', [])
        if not steps: return False
        last_result_obj = None
        for step_data in steps:
            raw_params = step_data.get('params', {})
            rendered_params = self._render_params(raw_params)
            last_result_obj = self.run_step(step_data, rendered_params)
            step_succeeded = True
            if hasattr(last_result_obj, 'found') and last_result_obj.found is False:
                step_succeeded = False
            elif last_result_obj is False:
                step_succeeded = False
            if not step_succeeded:
                return False
        return True

    def _verify_current_state(self, expected_state: str) -> bool:
        logger.debug(f"正在验证是否处于状态: '{expected_state}'")
        actual_state = self.orchestrator.determine_current_state()
        if actual_state == expected_state:
            return True
        else:
            logger.warning(f"状态校准失败！期望状态: '{expected_state}', 实际状态: '{actual_state}'。")
            return False

    def _execute_single_step_logic(self, step_data: Dict[str, Any]) -> bool:
        # (这个方法基本保持不变，但移除了 loop 逻辑，因为它已在 run_linear_task 中处理)
        wait_before = step_data.get('wait_before')
        if wait_before:
            try:
                wait_seconds = float(wait_before)
                logger.info(f"  -> 执行前等待 {wait_seconds} 秒...")
                time.sleep(wait_seconds)
            except (ValueError, TypeError):
                logger.warning(f"  -> 'wait_before' 的值 '{wait_before}' 无效，已忽略。应为一个数字。")

        # 循环逻辑现在由 run_linear_task 处理
        if 'loop' in step_data:
            loop_items = self._render_value(step_data['loop'], self.context._data)
            if not isinstance(loop_items, list):
                logger.warning(f"  -> 'loop' 的值不是一个列表，跳过循环。")
                return True  # 跳过循环不应算作失败

            logger.info(f"  -> 开始循环，共 {len(loop_items)} 项。")
            all_loop_steps_succeeded = True
            # 创建一个不包含 loop 键的新 step_data 用于递归执行
            step_without_loop = step_data.copy()
            del step_without_loop['loop']

            for item_index, item in enumerate(loop_items):
                self._check_pause()
                logger.info(f"    - 循环 {item_index + 1}/{len(loop_items)}")
                self.context.set('item', item)
                self.context.set('item_index', item_index)

                # 递归调用，执行循环体内的逻辑
                if not self._execute_single_step_logic(step_without_loop):
                    all_loop_steps_succeeded = False
                    # 你可以决定循环中的一次失败是否要中止整个循环
                    # break

            self.context.delete('item')
            self.context.delete('item_index')
            return all_loop_steps_succeeded

        # 非循环步骤的执行逻辑
        retry_config = step_data.get('retry')
        max_attempts = 1
        retry_interval = 1.0
        if isinstance(retry_config, dict):
            max_attempts = int(retry_config.get('count', 1))
            retry_interval = float(retry_config.get('interval', 1.0))
        elif retry_config:
            try:
                max_attempts = int(retry_config)
            except (ValueError, TypeError):
                logger.warning(f"  -> 'retry' 的值 '{retry_config}' 无效，已忽略。应为一个整数或字典。")

        step_succeeded = False
        result_obj = None
        for attempt in range(max_attempts):
            self._check_pause()
            if attempt > 0:
                logger.info(f"  -> 步骤失败，在 {retry_interval} 秒后进行第 {attempt + 1}/{max_attempts} 次重试...")
                time.sleep(retry_interval)

            raw_params = step_data.get('params', {})
            rendered_params = self._render_params(raw_params)
            result_obj = self.run_step(step_data, rendered_params)

            step_succeeded = True
            if result_obj is False:
                step_succeeded = False
            elif hasattr(result_obj, 'found') and result_obj.found is False:
                step_succeeded = False

            if step_succeeded:
                if max_attempts > 1:
                    logger.info(f"  -> 步骤在第 {attempt + 1} 次尝试中成功。")
                break

        if not step_succeeded:
            step_name = step_data.get('name', '未命名步骤')
            if max_attempts > 1:
                logger.warning(f"  -> 步骤 '{step_name}' 在所有 {max_attempts} 次尝试后仍然失败。")
            else:
                logger.warning(f"  -> 步骤 '{step_name}' 失败。")
            self._capture_debug_screenshot(step_name)

        if step_succeeded and 'on_success' in step_data:
            logger.info("  -> 步骤成功，执行 on_success...")
            return self._execute_single_step_logic(step_data['on_success'])

        if not step_succeeded and 'on_failure' in step_data:
            logger.warning("  -> 步骤失败，执行 on_failure...")
            return self._execute_single_step_logic(step_data['on_failure'])

        return step_succeeded

    # ... (run_step, _dispatch_action, _render_params 保持不变) ...
    def run_step(self, step_data: Dict[str, Any], rendered_params: Dict[str, Any]) -> Any:
        action_name = step_data.get('action')
        if not action_name:
            return True
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
            params_to_pass = rendered_params.get('pass_params', {})
            original_values = {}
            newly_added_keys = []
            try:
                logger.debug(f"为子任务 '{sub_task_name}' 创建临时上下文作用域...")
                for key, value in params_to_pass.items():
                    if self.context.get(key) is not None:
                        original_values[key] = self.context.get(key)
                    else:
                        newly_added_keys.append(key)
                    self.context.set(key, value)
                self.run(sub_task_data, sub_task_name)
                return True
            finally:
                logger.debug(f"恢复 '{sub_task_name}' 执行前的父上下文作用域...")
                for key, value in original_values.items():
                    self.context.set(key, value)
                for key in newly_added_keys:
                    self.context.delete(key)
        return self._dispatch_action(step_data, rendered_params)

    def _dispatch_action(self, step_data: Dict[str, Any], rendered_params: Dict[str, Any]) -> Any:
        action_name = step_data.get('action')
        logger.debug(f"分发行为: '{action_name}'")
        try:
            result = self.injector.execute_action(action_name, rendered_params)
            if 'output_to' in step_data:
                output_key = step_data['output_to']
                self.context.set(output_key, result)
                logger.info(f"  -> 步骤输出已保存到上下文变量: '{output_key}'")
            return result
        except Exception as e:
            logger.error(f"执行行为 '{action_name}' 时发生未捕获的异常: {e}", exc_info=True)
            return False

    def _render_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        rendered_params = {}
        context_data = self.context._data.copy()
        for key, value in params.items():
            rendered_params[key] = self._render_value(value, context_data)
        return rendered_params

    def _render_value(self, value: Any, context_data: Dict[str, Any]) -> Any:
        """
        【已修复和优化】递归渲染一个值。
        - 使用Jinja2模板渲染字符串。
        - 优雅地处理 UndefinedError，使其在 'when' 条件中安全地评估为 False。
        - 使用 ast.literal_eval 安全地将渲染后的字符串转换为Python对象。
        """
        if isinstance(value, str):
            if "{{" not in value and "{%" not in value:
                return value
            try:
                template = self.jinja_env.from_string(value)
                rendered_string = template.render(context_data)

                # 尝试将渲染结果解析为Python字面量（如 "true" -> True, "123" -> 123）
                try:
                    return literal_eval(rendered_string)
                except (ValueError, SyntaxError, MemoryError, TypeError):
                    # 如果不能解析，就返回原始的渲染字符串
                    return rendered_string

            except UndefinedError:
                # 当 'when' 条件中的变量不存在时 (e.g., {{ undefined_var.found }})
                # 我们将其安全地评估为 False。这对于条件判断至关重要。
                return False
            except Exception as e:
                logger.error(f"渲染Jinja2模板 '{value}' 时出错: {e}")
                # 重新抛出其他类型的异常，但不建议在这里崩溃，返回None或False可能更安全
                return None

        elif isinstance(value, dict):
            return {k: self._render_value(v, context_data) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._render_value(item, context_data) for item in value]
        else:
            return value

    def _capture_debug_screenshot(self, failed_step_name: str):
        try:
            # 【修改】使用更健壮的方式获取服务，并处理服务不存在的情况
            app_service = service_registry.get_service_instance('app', resolution_chain=[])
            debug_dir = self.context.get('debug_dir')
            if not app_service:
                logger.warning("无法进行失败截图，因为 'app' 服务不可用。")
                return
            if not debug_dir:
                logger.warning("无法进行失败截图，因为上下文中缺少 'debug_dir'。")
                return

            timestamp = time.strftime("%Y%m%d-%H%M%S")
            safe_step_name = "".join(c for c in failed_step_name if c.isalnum() or c in (' ', '_')).rstrip()
            filename = f"failure_{timestamp}_{safe_step_name}.png"
            filepath = os.path.join(debug_dir, filename)

            capture_result = app_service.capture()

            if hasattr(capture_result, 'success') and capture_result.success:
                capture_result.save(filepath)
                logger.error(f"步骤失败，已自动截图至: {filepath}")
            else:
                # 假设 capture() 直接返回图像数据
                with open(filepath, "wb") as f:
                    f.write(capture_result)
                logger.error(f"步骤失败，已自动截图至: {filepath}")

        except NameError:
            logger.warning("无法进行失败截图，因为 'app' 服务当前未注册或初始化。")
        except Exception as e:
            logger.error(f"在执行失败截图时发生意外错误: {e}")


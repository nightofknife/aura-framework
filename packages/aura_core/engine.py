# packages/aura_core/engine.py (已集成增强的 run_task)

import inspect
import os
import time
import yaml
import threading
from typing import Any, Callable, Dict, Iterable
from ast import literal_eval
from jinja2 import Environment, BaseLoader, UndefinedError

from packages.aura_core.context import Context  # 确保导入的是更新后的 Context
from packages.aura_shared_utils.utils.logger import logger
from packages.aura_core.exceptions import StopTaskException
from packages.aura_core.api import service_registry, ACTION_REGISTRY, ActionDefinition
from packages.aura_core.middleware import middleware_manager


class DependencyInjector:
    # ... (这部分代码保持不变) ...
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
    # ... (__init__ 和其他方法保持不变，除了 run_step) ...
    def __init__(self, context: Context, orchestrator=None, pause_event: threading.Event = None):
        self.context = context
        self.injector = DependencyInjector(context, engine=self)
        self.jinja_env = Environment(loader=BaseLoader())
        self.orchestrator = orchestrator
        self.pause_event = pause_event if pause_event else threading.Event()

        # 【新增】获取 config 服务并注入到 Jinja2
        try:
            self.config_service = service_registry.get_service_instance('config')
            self.jinja_env.globals['config'] = self.config_service.get
        except Exception as e:
            logger.warning(f"无法获取ConfigService，Jinja2中的 'config()' 函数将不可用: {e}")
            self.config_service = None
            self.jinja_env.globals['config'] = lambda key, default=None: default

        self._initialize_middlewares()
        if not self.context.is_sub_context():
            logger.info("执行引擎已初始化。")

    def _initialize_middlewares(self):
        pass

    def _check_pause(self):
        if self.pause_event.is_set():
            logger.warning("接收到全局暂停信号，任务执行已暂停。等待恢复信号...")
            self.pause_event.wait()
            logger.info("接收到恢复信号，任务将继续执行。")

    def run(self, task_data: Dict[str, Any], task_name: str):

        if 'steps' in task_data:
            self.run_linear_task(task_data, task_name)
        else:
            logger.error(f"任务 '{task_name}' 格式错误。")

    def run_linear_task(self, task_data: Dict[str, Any], task_name: str):

        steps = task_data.get('steps', [])
        if not steps:
            logger.warning(f"任务 '{task_name}' 中没有任何步骤。")
            return

        is_sub_block = self.context.is_sub_context()
        if not is_sub_block:
            task_display_name = task_data.get('name', task_name)
            logger.info(f"======= 开始执行任务: {task_display_name} =======")
        else:
            task_display_name = task_name

        try:
            for i, step_data in enumerate(steps):
                if not isinstance(step_data, dict):
                    logger.error(f"步骤 {i + 1} 的格式无效，不是一个字典。已跳过。")
                    continue

                step_name = step_data.get('name', f'未命名步骤 {i + 1}')
                control_keys = {'if', 'switch', 'while', 'for'}
                is_control_block = any(key in step_data for key in control_keys)
                if is_control_block:
                    log_name = step_name if step_data.get('name') else "逻辑控制块"
                    logger.info(f"\n[步骤 {i + 1}/{len(steps)}]: {log_name}")
                else:
                    logger.info(f"\n[步骤 {i + 1}/{len(steps)}]: {step_name}")

                if 'when' in step_data:
                    condition = self._render_value(step_data['when'], self.context._data)
                    if not condition:
                        logger.info(f"  -> 前置条件 'when: {step_data['when']}' 不满足，跳过此步骤。")
                        continue

                # --- 流程控制分派器 ---
                if 'if' in step_data:
                    self._execute_if_block(step_data)
                    continue
                if 'switch' in step_data:
                    self._execute_switch_block(step_data)
                    continue
                if 'while' in step_data:
                    self._execute_while_block(step_data)
                    continue
                if 'for' in step_data:
                    self._execute_for_block(step_data)
                    continue

                step_succeeded = self._execute_single_step_logic(step_data)
                if not step_succeeded and not step_data.get('continue_on_failure', False):
                    raise StopTaskException(f"步骤 '{step_name}' 失败且未设置 continue_on_failure，任务中止。",
                                            success=False)

        except StopTaskException as e:
            if not is_sub_block:
                if e.success:
                    logger.info(f"✅ 任务被正常停止: {e.message}")
                else:
                    logger.warning(f"🛑 任务因预期失败而停止: {e.message}")
        except Exception as e:
            logger.error(f"!! 任务 '{task_display_name}' 执行时发生严重错误: {e}")
            import traceback
            logger.debug(traceback.format_exc())

        if not is_sub_block:
            logger.info(f"======= 任务 '{task_display_name}' 执行结束 =======")

    # 【核心修改】run_step 现在只处理 run_task，其他 action 交给 _dispatch_action
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

            logger.info(f"--- 正在调用子任务: {sub_task_name} ---")
            sub_task_data = self.orchestrator.load_task_data(sub_task_name)
            if not sub_task_data:
                return False  # load_task_data 内部应有日志

            # 1. 创建隔离的子上下文
            sub_context = self.context.fork()
            logger.debug(f"为子任务 '{sub_task_name}' 创建了新的隔离上下文。")

            # 2. 传递参数
            params_to_pass = rendered_params.get('pass_params', {})
            if params_to_pass:
                logger.debug(f"向子任务传递参数: {list(params_to_pass.keys())}")
            for key, value in params_to_pass.items():
                sub_context.set(key, value)

            # 3. 创建子引擎并执行
            # 将当前引擎的关键组件传递给子引擎
            sub_engine = ExecutionEngine(sub_context, self.orchestrator, self.pause_event)
            sub_engine.run(sub_task_data, "sub-task")

            # 4. 处理子任务的返回值
            task_outputs = sub_task_data.get('outputs')
            return_value = {}
            if isinstance(task_outputs, dict):
                logger.info("  -> 正在处理子任务的返回值...")
                for key, value_expr in task_outputs.items():
                    # 使用子任务的上下文来渲染返回值表达式
                    return_value[key] = sub_engine._render_value(value_expr, sub_context._data)
                logger.debug(f"子任务返回数据: {list(return_value.keys())}")

            # 5. 将返回值设置到父任务的上下文中
            if 'output_to' in step_data:
                output_key = step_data['output_to']
                self.context.set(output_key, return_value)
                logger.info(f"  -> 子任务返回值已保存到父上下文变量: '{output_key}'")

            logger.info(f"--- 子任务 '{sub_task_name}' 调用结束 ---")
            return True

        # 对于所有其他 action，直接分发
        return self._dispatch_action(step_data, rendered_params)

    # ... (其他辅助方法 _execute_if_block, _execute_switch_block 等保持不变) ...
    def _execute_if_block(self, step_data: Dict[str, Any]):
        condition_str = step_data['if']
        condition = self._render_value(condition_str, self.context._data)

        if condition:
            logger.info(f"  -> 条件 'if: {condition_str}' 满足，执行 then 块...")
            self._execute_steps_block(step_data.get('then', []))
        else:
            if 'else' in step_data:
                logger.info(f"  -> 条件不满足，执行 else 块...")
                self._execute_steps_block(step_data.get('else', []))
            else:
                logger.info(f"  -> 条件 'if: {condition_str}' 不满足，且无 else 块，跳过。")

    def _execute_switch_block(self, step_data: Dict[str, Any]):
        switch_str = step_data['switch']
        switch_value = self._render_value(switch_str, self.context._data)
        logger.info(f"  -> Switch on value: '{switch_value}' (from '{switch_str}')")

        case_executed = False
        cases = step_data.get('cases', [])
        for case_block in cases:
            if not isinstance(case_block, dict) or 'case' not in case_block:
                continue

            case_condition = case_block.get('case')
            match = False

            if isinstance(case_condition, list):
                if switch_value in case_condition:
                    match = True
            elif isinstance(case_condition, str) and '{{' in case_condition:
                case_context = self.context._data.copy()
                case_context['value'] = switch_value
                match = self._render_value(case_condition, case_context)
            else:
                if switch_value == case_condition:
                    match = True

            if match:
                logger.info(f"  -> Case '{case_condition}' 匹配，执行 then 块...")
                self._execute_steps_block(case_block.get('then', []))
                case_executed = True
                break

        if not case_executed and 'default' in step_data:
            logger.info("  -> 所有 Case 均不匹配，执行 default 块...")
            self._execute_steps_block(step_data.get('default', []))

    def _execute_while_block(self, step_data: Dict[str, Any]):
        condition_str = step_data['while']
        do_steps = step_data.get('do', [])
        max_loops = int(step_data.get('max_loops', 1000))

        loop_count = 0
        logger.info(f"  -> Entering while loop (condition: {condition_str})")

        self._check_pause()
        while self._render_value(condition_str, self.context._data):
            if loop_count >= max_loops:
                logger.warning(f"  -> While loop terminated: maximum loop count ({max_loops}) reached.")
                break

            loop_count += 1
            logger.info(f"  -> While loop iteration {loop_count}/{max_loops}")
            self._execute_steps_block(do_steps)
            self._check_pause()

        logger.info(f"  -> Exited while loop after {loop_count} iterations.")

    def _execute_for_block(self, step_data: Dict[str, Any]):
        for_config = step_data.get('for', {})
        if not isinstance(for_config, dict):
            logger.error(f"  -> For loop configuration is invalid (not a dictionary). Skipping.")
            return

        as_variable = for_config.get('as')
        do_steps = step_data.get('do', [])

        if not as_variable:
            logger.error("  -> For loop is missing 'as' variable name. Skipping.")
            return

        try:
            if 'count' in for_config:
                count = int(self._render_value(for_config['count'], self.context._data))
                logger.info(f"  -> Entering for-count loop (count: {count}, as: '{as_variable}')")
                for i in range(count):
                    self._check_pause()
                    logger.info(f"  -> For loop iteration {i + 1}/{count}")
                    self.context.set(as_variable, i)
                    self._execute_steps_block(do_steps)

            elif 'in' in for_config:
                items_str = for_config['in']
                items = self._render_value(items_str, self.context._data)
                if not isinstance(items, Iterable) or isinstance(items, (str, bytes)):
                    logger.error(
                        f"  -> For-in loop failed: value from '{items_str}' is not a valid iterable collection (e.g., a list). Got type: {type(items).__name__}. Skipping.")
                    return
                num_items = len(items)
                logger.info(f"  -> Entering for-in loop ({num_items} items, as: '{as_variable}')")
                for i, item in enumerate(items):
                    self._check_pause()
                    logger.info(f"  -> For loop iteration {i + 1}/{num_items}")
                    self.context.set(as_variable, item)
                    self._execute_steps_block(do_steps)
            else:
                logger.error("  -> Invalid for loop configuration. Missing 'count' or 'in'. Skipping.")
        finally:
            self.context.delete(as_variable)
            logger.info(f"  -> Exited for loop. Cleaned up context variable '{as_variable}'.")

    def _execute_steps_block(self, steps_to_run: list):
        if not isinstance(steps_to_run, list):
            logger.error("逻辑块中的步骤定义不是一个列表，无法执行。")
            return
        sub_context = self.context.fork()
        sub_engine = ExecutionEngine(sub_context, self.orchestrator, self.pause_event)

        # 【修正】这里的 task_name 只是为了日志清晰，不再用于逻辑判断
        sub_engine.run_linear_task({"steps": steps_to_run}, "sub-block")



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

    def _execute_single_step_logic(self, step_data: Dict[str, Any]) -> bool:
        wait_before = step_data.get('wait_before')
        if wait_before:
            try:
                wait_seconds = float(wait_before)
                logger.info(f"  -> 执行前等待 {wait_seconds} 秒...")
                time.sleep(wait_seconds)
            except (ValueError, TypeError):
                logger.warning(f"  -> 'wait_before' 的值 '{wait_before}' 无效，已忽略。应为一个数字。")

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

    def _dispatch_action(self, step_data: Dict[str, Any], rendered_params: Dict[str, Any]) -> Any:
        # ... (这部分代码保持不变) ...
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
        # ... (这部分代码保持不变) ...
        rendered_params = {}
        context_data = self.context._data.copy()
        for key, value in params.items():
            rendered_params[key] = self._render_value(value, context_data)
        return rendered_params

    def _render_value(self, value: Any, context_data: Dict[str, Any]) -> Any:
        if isinstance(value, str):
            # 如果字符串是纯粹的Jinja2表达式，我们才尝试 literal_eval
            is_pure_expression = value.startswith("{{") and value.endswith("}}")

            if "{{" not in value and "{%" not in value:
                return value
            try:
                template = self.jinja_env.from_string(value)
                rendered_string = template.render(context_data)

                # 【修改】只有在原始值是纯表达式时才尝试 literal_eval
                if is_pure_expression:
                    try:
                        return literal_eval(rendered_string)
                    except (ValueError, SyntaxError, MemoryError, TypeError):
                        return rendered_string
                else:
                    return rendered_string

            except UndefinedError as e:
                # 【修改】提供更友好的未定义变量错误提示
                logger.warning(f"渲染模板 '{value}' 时出错: 变量 {e.message} 未定义。")
                return value  # 返回原始字符串，而不是False
            except Exception as e:
                logger.error(f"渲染Jinja2模板 '{value}' 时出错: {e}")
                return None
        elif isinstance(value, dict):
            return {k: self._render_value(v, context_data) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._render_value(item, context_data) for item in value]
        else:
            return value
    def _capture_debug_screenshot(self, failed_step_name: str):
        # ... (这部分代码保持不变) ...
        try:
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
                with open(filepath, "wb") as f:
                    f.write(capture_result)
                logger.error(f"步骤失败，已自动截图至: {filepath}")
        except NameError:
            logger.warning("无法进行失败截图，因为 'app' 服务当前未注册或初始化。")
        except Exception as e:
            logger.error(f"在执行失败截图时发生意外错误: {e}")


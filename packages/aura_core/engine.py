# packages/aura_core/engine.py (已修复)

import os
import threading
import time
from typing import Any, Dict, Iterable, List, Optional

from packages.aura_shared_utils.utils.logger import logger
from .action_injector import ActionInjector
from .api import service_registry
from .context import Context
from .exceptions import StopTaskException


class JumpSignal(Exception):
    """
    【修改】将 JumpSignal 从普通类改为异常类。
    这使得我们可以通过 raise 来中断深层递归，比层层 return 更干净。
    """

    def __init__(self, jump_type: str, target: str):
        self.type = jump_type  # 'go_step' or 'go_task'
        self.target = target
        super().__init__(f"JumpSignal: type={self.type}, target={self.target}")

    def __repr__(self):
        return f"JumpSignal(type={self.type}, target={self.target})"


class ExecutionEngine:
    """
    【重构后】Aura 任务执行引擎。
    """

    def __init__(self, context: Context, orchestrator=None, pause_event: threading.Event = None):
        self.context = context
        self.orchestrator = orchestrator
        self.pause_event = pause_event if pause_event else threading.Event()
        self.injector = ActionInjector(context, engine=self)
        self.next_task_target: Optional[str] = None
        self.step_map: Dict[str, int] = {}

        if not self.context.is_sub_context():
            logger.info("执行引擎已初始化。")

    def _check_pause(self):
        if self.pause_event.is_set():
            logger.warning("接收到全局暂停信号，任务执行已暂停。等待恢复信号...")
            self.pause_event.wait()
            logger.info("接收到恢复信号，任务将继续执行。")

    # 【【【 Bug修复点 2/2 】】】
    def _build_step_map(self, steps: List[Dict], top_level_index: Optional[int] = None):
        """
        【修正版】递归构建步骤ID到其顶层父步骤索引的映射。
        """
        for i, step in enumerate(steps):
            # 对于顶层步骤，其父索引就是它自己的索引
            current_top_level_index = i if top_level_index is None else top_level_index

            if isinstance(step, dict) and 'id' in step:
                step_id = step['id']
                if step_id in self.step_map:
                    logger.warning(f"检测到重复的步骤 ID: '{step_id}'。go_step 可能跳转到非预期的位置。")
                self.step_map[step_id] = current_top_level_index

            # 递归遍历所有可能的子步骤列表
            if isinstance(step, dict):
                for child_list_key in ['then', 'else', 'do']:
                    if child_list_key in step and isinstance(step[child_list_key], list):
                        self._build_step_map(step[child_list_key], top_level_index=current_top_level_index)
                if 'cases' in step and isinstance(step['cases'], list):
                    for case in step['cases']:
                        if isinstance(case, dict) and 'then' in case and isinstance(case['then'], list):
                            self._build_step_map(case['then'], top_level_index=current_top_level_index)

    def run(self, task_data: Dict[str, Any], task_name: str) -> Dict[str, Any]:
        steps = task_data.get('steps', [])
        if not steps:
            logger.warning(f"任务 '{task_name}' 中没有任何步骤。")
            return {'status': 'success', 'next_task': None}

        self.step_map.clear()
        self._build_step_map(steps)

        is_sub_task = self.context.is_sub_context()
        if not is_sub_task:
            task_display_name = task_data.get('meta', {}).get('title', task_name)
            logger.info(f"======= 开始执行任务: {task_display_name} =======")

        current_index = 0
        while current_index < len(steps):
            self.next_task_target = None
            step_data = steps[current_index]

            if not isinstance(step_data, dict):
                logger.error(f"步骤 {current_index + 1} 格式无效，已跳过。")
                current_index += 1
                continue

            step_name = step_data.get('name', f'未命名步骤 {current_index + 1}')
            logger.info(f"\n[步骤 {current_index + 1}/{len(steps)}]: {step_name}")

            try:
                self._execute_step_recursively(step_data)

            except JumpSignal as signal:
                if signal.type == 'go_task':
                    logger.info(f"接收到 go_task 信号，目标: {signal.target}。任务将中止并跳转。")
                    return {'status': 'go_task', 'next_task': signal.target}

                if signal.type == 'go_step':
                    target_id = self.injector._render_value(signal.target, self.context._data)
                    if target_id in self.step_map:
                        logger.info(f"接收到 go_step 信号，跳转到步骤 ID: '{target_id}'")
                        current_index = self.step_map[target_id]
                        continue
                    else:
                        raise StopTaskException(f"go_step 目标 '{target_id}' 未找到", success=False) from signal

            except StopTaskException as e:
                if not is_sub_task:
                    log_func = logger.info if e.success else logger.warning
                    log_func(f"🛑 任务被停止: {e.message}")
                return {'status': 'stopped', 'next_task': None}
            except Exception as e:
                logger.error(f"!! 任务 '{task_name}' 执行时发生严重错误: {e}", exc_info=True)
                return {'status': 'error', 'next_task': None}

            if self.next_task_target:
                return {'status': 'success', 'next_task': self.next_task_target}

            current_index += 1

        if not is_sub_task:
            logger.info(f"======= 任务 '{task_data.get('meta', {}).get('title', task_name)}' 执行结束 =======")
        return {'status': 'success', 'next_task': self.next_task_target}

    def _execute_step_recursively(self, step_data: Dict[str, Any]):
        self._check_pause()

        if 'when' in step_data:
            condition = self.injector._render_value(step_data['when'], self.context._data)
            if not condition:
                logger.info(f"  -> 前置条件 'when: {step_data['when']}' 不满足，跳过。")
                return

        if 'go_step' in step_data: raise JumpSignal('go_step', step_data['go_step'])
        if 'go_task' in step_data: raise JumpSignal('go_task', self.injector._render_value(step_data['go_task'],
                                                                                           self.context._data))
        if 'next' in step_data: self.next_task_target = self.injector._render_value(step_data['next'],
                                                                                    self.context._data)

        if 'if' in step_data:
            self._execute_if_block(step_data)
        elif 'for' in step_data:
            self._execute_for_block(step_data)
        elif 'while' in step_data:
            self._execute_while_block(step_data)
        else:
            step_succeeded = self._execute_single_action_step(step_data)
            if not step_succeeded and not step_data.get('continue_on_failure', False):
                raise StopTaskException(f"步骤 '{step_data.get('name')}' 失败且未设置 continue_on_failure。",
                                        success=False)

    def _execute_if_block(self, step_data: dict):
        condition_str = step_data['if']
        condition = self.injector._render_value(condition_str, self.context._data)

        logger.info(f"  -> 条件 'if: {condition_str}' 的值为: {condition}")
        target_block = 'then' if condition else 'else'

        if target_block in step_data:
            logger.info(f"  -> 执行 {target_block} 块...")
            self._execute_steps_block(step_data.get(target_block, []))

    def _execute_for_block(self, step_data: dict):
        for_config = step_data.get('for', {})
        if not isinstance(for_config, dict): return

        as_variable = for_config.get('as')
        items_str = for_config.get('in')
        if not as_variable or not items_str: return

        items = self.injector._render_value(items_str, self.context._data)
        if not isinstance(items, Iterable) or isinstance(items, (str, bytes)):
            logger.error(f"  -> For-in 循环失败: '{items_str}' 的结果不是可迭代对象。")
            return

        loop_len = len(items) if hasattr(items, '__len__') else '未知'
        logger.info(f"  -> 进入 for-in 循环 (迭代 {loop_len} 个元素, 变量为 '{as_variable}')")

        try:
            for i, item in enumerate(items):
                self._check_pause()
                logger.info(f"  -> For 循环迭代 {i + 1}/{loop_len}")
                self.context.set(as_variable, item)
                self._execute_steps_block(step_data.get('do', []))
        finally:
            self.context.delete(as_variable)
            logger.info(f"  -> 退出 for 循环，已清理上下文变量 '{as_variable}'。")

    def _execute_while_block(self, step_data: dict):
        condition_str = step_data.get('while')
        do_steps = step_data.get('do', [])
        max_loops = int(self.injector._render_value(step_data.get('max_loops', 1000), self.context._data))
        loop_count = 0
        logger.info(f"  -> 进入 while 循环 (condition: {condition_str})")

        while self.injector._render_value(condition_str, self.context._data):
            self._check_pause()
            if loop_count >= max_loops:
                logger.warning(f"  -> While 循环终止: 已达到最大循环次数 ({max_loops})。")
                break
            loop_count += 1
            logger.info(f"  -> While 循环迭代 {loop_count}/{max_loops}")
            self._execute_steps_block(do_steps)

        logger.info(f"  -> 退出 while 循环，共执行 {loop_count} 次。")

    def _execute_steps_block(self, steps_to_run: list):
        if not isinstance(steps_to_run, list): return
        for sub_step_data in steps_to_run:
            self._execute_step_recursively(sub_step_data)

    # 【【【 Bug修复点 1/2 】】】
    def _execute_single_action_step(self, step_data: Dict[str, Any]) -> bool:
        """
        【修正版】执行单个 Action 步骤。
        在步骤最终失败时，如果设置了 output_to，会向上下文中写入 False。
        """
        wait_before = step_data.get('wait_before')
        if wait_before:
            try:
                wait_seconds = float(self.injector._render_value(wait_before, self.context._data))
                logger.info(f"  -> 执行前等待 {wait_seconds} 秒...")
                time.sleep(wait_seconds)
            except (ValueError, TypeError):
                logger.warning(f"  -> 'wait_before' 的值 '{wait_before}' 无效，已忽略。")

        retry_config = step_data.get('retry', {})
        max_attempts = int(retry_config.get('count', 1))
        retry_interval = float(retry_config.get('interval', 1.0))

        for attempt in range(max_attempts):
            self._check_pause()
            if attempt > 0:
                logger.info(f"  -> 步骤失败，在 {retry_interval} 秒后进行第 {attempt + 1}/{max_attempts} 次重试...")
                time.sleep(retry_interval)

            try:
                action_name = step_data.get('action')
                if action_name and action_name.lower() == 'run_task':
                    result = self._run_sub_task(step_data)
                    if isinstance(result, JumpSignal):
                        raise result
                elif action_name:
                    raw_params = step_data.get('params', {})
                    result = self.injector.execute(action_name, raw_params)
                else:
                    result = True

                # 判断步骤是否成功
                step_succeeded = True
                if result is False:
                    step_succeeded = False
                # 兼容 find_* 系列 action 的返回对象
                elif hasattr(result, 'found') and result.found is False:
                    step_succeeded = False

                if step_succeeded:
                    if 'output_to' in step_data:
                        self.context.set(step_data['output_to'], result)
                        logger.info(f"  -> 步骤输出已保存到上下文变量: '{step_data['output_to']}'")
                    if max_attempts > 1:
                        logger.info(f"  -> 步骤在第 {attempt + 1} 次尝试中成功。")
                    return True

            except JumpSignal:
                raise
            except Exception as e:
                logger.error(f"  -> 执行行为 '{step_data.get('action')}' 时发生异常: {e}", exc_info=False)  # 减少冗余堆栈

        # --- 步骤最终失败的处理逻辑 ---
        step_name = step_data.get('name', '未命名步骤')
        logger.warning(f"  -> 步骤 '{step_name}' 在所有 {max_attempts} 次尝试后仍然失败。")

        # 【修正】如果步骤失败了，但设置了 output_to，则将 False 写入上下文
        if 'output_to' in step_data:
            output_var = step_data['output_to']
            self.context.set(output_var, False)
            logger.info(f"  -> 因步骤失败，已将上下文变量 '{output_var}' 设置为 False。")

        self._capture_debug_screenshot(step_name)
        return False
    def _run_sub_task(self, step_data: Dict[str, Any]) -> Any:
        if not self.orchestrator:
            logger.error("'run_task' 无法执行，引擎未关联编排器。")
            return False

        raw_params = step_data.get('params', {})
        rendered_params = self.injector._render_params(raw_params)
        sub_task_id = rendered_params.get('task_name')

        if not sub_task_id:
            logger.error("'run_task' 行为缺少 'task_name' 参数。")
            return False

        logger.info(f"--- 正在调用子任务: {sub_task_id} ---")

        sub_task_data = self.orchestrator.load_task_data(sub_task_id)
        if not sub_task_data: return False

        sub_context = self.context.fork()
        params_to_pass = rendered_params.get('pass_params', {})
        for key, value in params_to_pass.items():
            sub_context.set(key, value)

        sub_engine = ExecutionEngine(sub_context, self.orchestrator, self.pause_event)
        sub_task_result = sub_engine.run(sub_task_data, sub_task_id)

        if sub_task_result['status'] == 'go_task':
            return JumpSignal('go_task', sub_task_result['next_task'])
        elif sub_task_result['status'] == 'success' and sub_task_result['next_task']:
            self.next_task_target = sub_task_result['next_task']

        task_outputs = sub_task_data.get('outputs')
        return_value = {}
        if isinstance(task_outputs, dict):
            sub_injector = ActionInjector(sub_context, sub_engine)
            for key, value_expr in task_outputs.items():
                return_value[key] = sub_injector._render_value(value_expr, sub_context._data)

        logger.info(f"--- 子任务 '{sub_task_id}' 调用结束 ---")
        return return_value

    def _capture_debug_screenshot(self, failed_step_name: str):
        try:
            app_service = service_registry.get_service_instance('app')
            debug_dir = self.context.get('debug_dir')
            if not app_service or not debug_dir: return

            timestamp = time.strftime("%Y%m%d-%H%M%S")
            safe_step_name = "".join(c for c in failed_step_name if c.isalnum() or c in (' ', '_')).rstrip()
            filename = f"failure_{timestamp}_{safe_step_name}.png"
            filepath = os.path.join(debug_dir, filename)

            image_data = app_service.capture()

            image_data.save(filepath)
            logger.error(f"步骤失败，已自动截图至: {filepath}")
        except Exception as e:
            logger.error(f"在执行失败截图时发生意外错误: {e}")

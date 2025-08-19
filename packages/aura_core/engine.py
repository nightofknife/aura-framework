import asyncio
import os
import time
from typing import Any, Dict, Iterable, List, Optional

from packages.aura_shared_utils.utils.logger import logger
from .action_injector import ActionInjector
from .api import service_registry
from .context import Context
from .exceptions import StopTaskException


class JumpSignal(Exception):
    def __init__(self, jump_type: str, target: str):
        self.type = jump_type
        self.target = target
        super().__init__(f"JumpSignal: type={self.type}, target={self.target}")


class ExecutionEngine:
    """
    【Async Refactor】Aura 异步任务执行引擎。
    """

    def __init__(self, context: Context, orchestrator=None, pause_event: asyncio.Event = None):
        self.context = context
        self.orchestrator = orchestrator
        self.pause_event = pause_event if pause_event else asyncio.Event()
        self.injector = ActionInjector(context, engine=self)
        self.next_task_target: Optional[str] = None
        self.step_map: Dict[str, int] = {}

    async def _check_pause(self):
        if self.pause_event.is_set():
            logger.warning("接收到全局暂停信号，任务执行已暂停。等待恢复信号...")
            await self.pause_event.wait()
            logger.info("接收到恢复信号，任务将继续执行。")

    def _build_step_map(self, steps: List[Dict], top_level_index: Optional[int] = None):
        # ... (此方法逻辑不变) ...
        for i, step in enumerate(steps):
            current_top_level_index = i if top_level_index is None else top_level_index
            if isinstance(step, dict) and 'id' in step:
                step_id = step['id']
                if step_id in self.step_map: logger.warning(f"检测到重复的步骤 ID: '{step_id}'。")
                self.step_map[step_id] = current_top_level_index
            if isinstance(step, dict):
                for child_list_key in ['then', 'else', 'do']:
                    if child_list_key in step and isinstance(step[child_list_key], list):
                        self._build_step_map(step[child_list_key], top_level_index=current_top_level_index)
                if 'cases' in step and isinstance(step['cases'], list):
                    for case in step['cases']:
                        if isinstance(case, dict) and 'then' in case and isinstance(case['then'], list):
                            self._build_step_map(case['then'], top_level_index=current_top_level_index)

    async def run(self, task_data: Dict[str, Any], task_name: str) -> Dict[str, Any]:
        steps = task_data.get('steps', [])
        if not steps:
            return {'status': 'success', 'next_task': None}

        self._build_step_map(steps)
        task_display_name = task_data.get('meta', {}).get('title', task_name)
        logger.info(f"======= 开始执行任务: {task_display_name} =======")

        current_index = 0
        while current_index < len(steps):
            self.next_task_target = None
            step_data = steps[current_index]
            step_name = step_data.get('name', f'未命名步骤 {current_index + 1}')
            logger.info(f"\n[步骤 {current_index + 1}/{len(steps)}]: {step_name}")

            try:
                await self._execute_step_recursively(step_data)
            except JumpSignal as signal:
                if signal.type == 'go_task': return {'status': 'go_task', 'next_task': signal.target}
                if signal.type == 'go_step':
                    target_id = await self.injector._render_value(signal.target, self.context._data)
                    if target_id in self.step_map:
                        current_index = self.step_map[target_id]
                        continue
                    raise StopTaskException(f"go_step 目标 '{target_id}' 未找到", success=False) from signal
            except StopTaskException as e:
                log_func = logger.info if e.success else logger.warning
                log_func(f"🛑 任务被停止: {e.message}")
                return {'status': 'stopped', 'next_task': None}
            except Exception as e:
                logger.error(f"!! 任务 '{task_name}' 执行时发生严重错误: {e}", exc_info=True)
                return {'status': 'error', 'next_task': None}

            if self.next_task_target:
                return {'status': 'success', 'next_task': self.next_task_target}
            current_index += 1

        logger.info(f"======= 任务 '{task_display_name}' 执行结束 =======")
        return {'status': 'success', 'next_task': self.next_task_target}

    async def _execute_step_recursively(self, step_data: Dict[str, Any]):
        await self._check_pause()

        if 'when' in step_data:
            condition = await self.injector._render_value(step_data['when'], self.context._data)
            if not condition:
                logger.info(f"  -> 前置条件 'when: {step_data['when']}' 不满足，跳过。")
                return

        if 'go_step' in step_data: raise JumpSignal('go_step', step_data['go_step'])
        if 'go_task' in step_data: raise JumpSignal('go_task', await self.injector._render_value(step_data['go_task'],
                                                                                                 self.context._data))
        if 'next' in step_data: self.next_task_target = await self.injector._render_value(step_data['next'],
                                                                                          self.context._data)

        if 'if' in step_data:
            await self._execute_if_block(step_data)
        elif 'for' in step_data:
            await self._execute_for_block(step_data)
        elif 'while' in step_data:
            await self._execute_while_block(step_data)
        else:
            step_succeeded = await self._execute_single_action_step(step_data)
            if not step_succeeded and not step_data.get('continue_on_failure', False):
                raise StopTaskException(f"步骤 '{step_data.get('name')}' 失败且未设置 continue_on_failure。",
                                        success=False)

    async def _execute_if_block(self, step_data: dict):
        condition = await self.injector._render_value(step_data['if'], self.context._data)
        target_block = 'then' if condition else 'else'
        if target_block in step_data: await self._execute_steps_block(step_data.get(target_block, []))

    async def _execute_for_block(self, step_data: dict):
        for_config = step_data.get('for', {})
        as_variable = for_config.get('as')
        items = await self.injector._render_value(for_config.get('in'), self.context._data)
        if not as_variable or not isinstance(items, Iterable) or isinstance(items, (str, bytes)): return
        try:
            for item in items:
                await self._check_pause()
                self.context.set(as_variable, item)
                await self._execute_steps_block(step_data.get('do', []))
        finally:
            self.context.delete(as_variable)

    async def _execute_while_block(self, step_data: dict):
        condition_str = step_data.get('while')
        max_loops = int(await self.injector._render_value(step_data.get('max_loops', 1000), self.context._data))
        loop_count = 0
        while await self.injector._render_value(condition_str, self.context._data):
            await self._check_pause()
            if loop_count >= max_loops: break
            loop_count += 1
            await self._execute_steps_block(step_data.get('do', []))

    async def _execute_steps_block(self, steps_to_run: list):
        if not isinstance(steps_to_run, list): return
        for sub_step_data in steps_to_run:
            await self._execute_step_recursively(sub_step_data)

    async def _execute_single_action_step(self, step_data: Dict[str, Any]) -> bool:
        wait_before = step_data.get('wait_before')
        if wait_before:
            wait_seconds = float(await self.injector._render_value(wait_before, self.context._data))
            await asyncio.sleep(wait_seconds)

        retry_config = step_data.get('retry', {})
        max_attempts = int(retry_config.get('count', 1))
        retry_interval = float(retry_config.get('interval', 1.0))

        for attempt in range(max_attempts):
            await self._check_pause()
            if attempt > 0:
                await asyncio.sleep(retry_interval)

            action_name = step_data.get('action')
            if action_name and action_name.lower() == 'run_task':
                result = await self._run_sub_task(step_data)
                if isinstance(result, JumpSignal): raise result
            elif action_name:
                result = await self.injector.execute(action_name, step_data.get('params', {}))
            else:
                result = True

            step_succeeded = not (result is False or (hasattr(result, 'found') and result.found is False))
            if step_succeeded:
                if 'output_to' in step_data: self.context.set(step_data['output_to'], result)
                return True

        if 'output_to' in step_data: self.context.set(step_data['output_to'], False)
        await self._capture_debug_screenshot(step_data.get('name', 'unnamed_step'))
        return False

    async def _run_sub_task(self, step_data: Dict[str, Any]) -> Any:
        if not self.orchestrator: return False
        rendered_params = await self.injector._render_params(step_data.get('params', {}))
        sub_task_id = rendered_params.get('task_name')
        if not sub_task_id: return False

        sub_task_data = self.orchestrator.load_task_data(sub_task_id)
        if not sub_task_data: return False

        sub_context = self.context.fork()
        for key, value in rendered_params.get('pass_params', {}).items():
            sub_context.set(key, value)

        sub_engine = ExecutionEngine(sub_context, self.orchestrator, self.pause_event)
        sub_task_result = await sub_engine.run(sub_task_data, sub_task_id)

        if sub_task_result['status'] == 'go_task': return JumpSignal('go_task', sub_task_result['next_task'])
        if sub_task_result['status'] == 'success' and sub_task_result['next_task']: self.next_task_target = \
        sub_task_result['next_task']

        return_value = {}
        if isinstance(sub_task_data.get('outputs'), dict):
            sub_injector = ActionInjector(sub_context, sub_engine)
            for key, value_expr in sub_task_data['outputs'].items():
                return_value[key] = await sub_injector._render_value(value_expr, sub_context._data)
        return return_value

    async def _capture_debug_screenshot(self, failed_step_name: str):
        # This part remains synchronous as it calls external services that might not be async
        # We run it in an executor to avoid blocking the main loop.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sync_capture_screenshot, failed_step_name)

    def _sync_capture_screenshot(self, failed_step_name: str):
        try:
            app_service = service_registry.get_service_instance('Aura-Project/base/app')
            debug_dir = self.context.get('debug_dir')
            if not app_service or not debug_dir: return

            timestamp = time.strftime("%Y%m%d-%H%M%S")
            safe_step_name = "".join(c for c in failed_step_name if c.isalnum() or c in (' ', '_')).rstrip()
            filename = f"failure_{timestamp}_{safe_step_name}.png"
            filepath = os.path.join(debug_dir, filename)
            capture_result = app_service.capture()
            if capture_result and capture_result.success:
                capture_result.save(filepath)
                logger.error(f"步骤失败，已自动截图至: {filepath}")
        except Exception as e:
            logger.error(f"在执行失败截图时发生意外错误: {e}", exc_info=True)

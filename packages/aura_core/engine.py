# packages/aura_core/engine.py (Final Hybrid Refactor)
import asyncio
import os
import time
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional
from graphlib import TopologicalSorter, CycleError

from packages.aura_core.logger import logger
from .action_injector import ActionInjector
from .api import service_registry
from .context import Context
from .exceptions import StopTaskException


class JumpSignal(Exception):
    # This class remains unchanged.
    def __init__(self, jump_type: str, target: str):
        self.type = jump_type
        self.target = target
        super().__init__(f"JumpSignal: type={self.type}, target={self.target}")


class StepState(Enum):
    # This enum remains unchanged.
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ExecutionEngine:
    """
    【Hybrid Refactor】Aura Async Task Execution Engine.
    Implements a unified DAG-based model where a node can be a single action
    or a multi-step linear script (using the 'do' keyword).
    Provides seamless backward compatibility for legacy list-based tasks.
    """

    def __init__(self, context: Context, orchestrator=None, pause_event: asyncio.Event = None):
        self.context = context
        self.orchestrator = orchestrator
        self.pause_event = pause_event if pause_event else asyncio.Event()
        self.injector = ActionInjector(context, engine=self)
        self.next_task_target: Optional[str] = None

        # State for DAG execution
        self.step_states: Dict[str, StepState] = {}
        self.step_results: Dict[str, Any] = {}

    async def run(self, task_data: Dict[str, Any], task_name: str) -> Dict[str, Any]:
        """
        Main execution entry point. All tasks are processed by the DAG engine.
        """
        task_display_name = task_data.get('meta', {}).get('title', task_name)
        logger.info(f"======= 开始执行任务: {task_display_name} =======")

        steps = task_data.get('steps', {})

        # 【Backward Compatibility】 Convert legacy list format to a compatible DAG format.
        if isinstance(steps, list):
            logger.warning("检测到旧的线性列表 'steps' 格式。将自动转换为兼容的DAG格式。建议更新为新的字典格式。")
            steps = self._convert_linear_list_to_dag(steps)

        if not isinstance(steps, dict) or not steps:
            return {'status': 'success', 'message': '任务中没有可执行的步骤。'}

        try:
            result = await self._run_dag_task(steps)
        except Exception as e:
            logger.error(f"!! 任务 '{task_name}' 执行时发生未捕获的严重错误: {e}", exc_info=True)
            result = {'status': 'error', 'message': str(e)}

        logger.info(f"======= 任务 '{task_display_name}' 执行结束 (状态: {result.get('status')}) =======")
        # Handle legacy 'next' keyword for task chaining
        if self.next_task_target:
            result['next_task'] = self.next_task_target
        return result

    def _convert_linear_list_to_dag(self, linear_steps: List[Dict]) -> Dict[str, Any]:
        """Converts a legacy list of steps into a single-node DAG with a 'do' block."""
        return {
            "__legacy_linear_task": {
                "name": "Legacy Linear Task",
                "do": linear_steps
            }
        }

    async def _run_dag_task(self, steps_dict: Dict[str, Any]) -> Dict[str, Any]:
        """The core DAG execution logic."""
        try:
            sorter = self._build_graph(steps_dict)
        except (KeyError, CycleError) as e:
            logger.error(f"构建任务图失败: {e}")
            return {'status': 'error', 'message': f"Failed to build task graph: {e}"}

        self.step_states = {step_id: StepState.PENDING for step_id in sorter.static_order()}
        self.step_results = {}
        # Make step results available in the context for Jinja2 rendering
        self.context.set('steps', self.step_results)

        while sorter.is_active():
            ready_nodes = sorter.get_ready()
            if not ready_nodes:
                logger.error("DAG execution stalled. No ready nodes found, but graph is still active.")
                return {'status': 'error', 'message': 'DAG execution stalled.'}

            async with asyncio.TaskGroup() as tg:
                for step_id in ready_nodes:
                    tg.create_task(self._execute_dag_node(step_id, steps_dict[step_id], sorter))

        final_status = 'success'
        for state in self.step_states.values():
            if state == StepState.FAILED:
                final_status = 'error'
                break

        return {'status': final_status, 'results': self.step_results}

    def _build_graph(self, steps_dict: Dict[str, Dict]) -> TopologicalSorter:
        sorter = TopologicalSorter()
        for step_id, step_data in steps_dict.items():
            sorter.add(step_id)
            for dependency in step_data.get('depends_on', []):
                if dependency not in steps_dict:
                    raise KeyError(f"步骤 '{step_id}' 存在未知的依赖: '{dependency}'")
                sorter.add(step_id, dependency)
        sorter.prepare()
        return sorter

    async def _execute_dag_node(self, step_id: str, step_data: Dict, sorter: TopologicalSorter):
        """Executes a single node in the DAG, which can be an action or a linear script."""
        self.step_states[step_id] = StepState.RUNNING
        step_name = step_data.get('name', step_id)
        logger.info(f"\n[DAG Node]: Starting '{step_name}' (ID: {step_id})")

        try:
            # Check if dependencies failed or were skipped
            for dep_id in step_data.get('depends_on', []):
                if self.step_states[dep_id] in (StepState.FAILED, StepState.SKIPPED):
                    logger.warning(f"  -> Skipping '{step_name}' because dependency '{dep_id}' was not successful.")
                    self.step_states[step_id] = StepState.SKIPPED
                    self.step_results[step_id] = {'status': 'skipped',
                                                  'reason': f'Dependency {dep_id} failed or was skipped.'}
                    sorter.done(step_id)
                    return

            await self._check_pause()

            if 'when' in step_data:
                condition = await self.injector._render_value(step_data['when'], self.context._data)
                if not condition:
                    logger.info(f"  -> Skipping '{step_name}' because 'when' condition was false.")
                    self.step_states[step_id] = StepState.SKIPPED
                    self.step_results[step_id] = {'status': 'skipped', 'reason': 'when condition was false'}
                    sorter.done(step_id)
                    return

            # 【Hybrid】 Execute based on node type: 'do' or 'action'
            if 'do' in step_data:
                node_result = await self._execute_linear_script_node(step_data['do'])
            elif 'action' in step_data:
                node_result = await self._execute_single_action_step(step_data)
            else:
                raise ValueError(f"DAG node '{step_id}' must contain either an 'action' or a 'do' block.")

            self.step_results[step_id] = {'status': 'success', 'result': node_result}
            self.step_states[step_id] = StepState.SUCCESS
            logger.info(f"[DAG Node]: Finished '{step_name}' successfully.")

        except Exception as e:
            logger.error(f"!! [DAG Node]: Failed '{step_name}': {e}", exc_info=True)
            self.step_states[step_id] = StepState.FAILED
            self.step_results[step_id] = {'status': 'failed', 'error': str(e)}
        finally:
            sorter.done(step_id)

    async def _execute_linear_script_node(self, sub_steps: List[Dict]) -> Any:
        """Executes a list of steps sequentially within an isolated sub-context."""
        # Fork the context to isolate variables within this 'do' block
        sub_context = self.context.fork()
        sub_injector = ActionInjector(sub_context, engine=self)
        last_result = None

        for i, step_data in enumerate(sub_steps):
            step_name = step_data.get('name', f"sub-step {i + 1}")
            logger.info(f"  -> [Linear Sub-Step]: {step_name}")

            # Note: We are re-using the single action executor for simplicity.
            # 'do' blocks do not support nested control flow (if/for/while) for now.
            # This can be extended later if needed.
            try:
                # Check 'when' condition for the sub-step
                if 'when' in step_data:
                    condition = await sub_injector._render_value(step_data['when'], sub_context._data)
                    if not condition:
                        logger.info(f"    -> Skipping sub-step '{step_name}' because 'when' condition was false.")
                        continue

                # Execute the action using the sub-injector and sub-context
                step_result = await self._execute_single_action_step(step_data, injector=sub_injector)

                if 'output_to' in step_data:
                    sub_context.set(step_data['output_to'], step_result)

                last_result = step_result

            except Exception as e:
                logger.error(f"    -> Sub-step '{step_name}' failed. Aborting linear script node.")
                raise e  # Propagate the exception to fail the parent DAG node

        # The result of the 'do' block is the result of its last successful step
        return last_result

    async def _execute_single_action_step(self, step_data: Dict[str, Any],
                                          injector: Optional[ActionInjector] = None) -> Any:
        """Executes a single action with retry logic. Can use a provided injector."""
        active_injector = injector or self.injector

        # Handle legacy keywords that might exist in linear scripts
        if 'next' in step_data: self.next_task_target = await active_injector._render_value(step_data['next'],
                                                                                            active_injector.context._data)
        if 'go_task' in step_data: raise JumpSignal('go_task', await active_injector._render_value(step_data['go_task'],
                                                                                                   active_injector.context._data))
        # 'go_step' is not supported in the new model as it breaks DAG logic.

        wait_before = step_data.get('wait_before')
        if wait_before:
            wait_seconds = float(await active_injector._render_value(wait_before, active_injector.context._data))
            await asyncio.sleep(wait_seconds)

        retry_config = step_data.get('retry', {})
        max_attempts = int(retry_config.get('count', 1))
        retry_interval = float(retry_config.get('interval', 1.0))

        last_exception = None
        for attempt in range(max_attempts):
            await self._check_pause()
            if attempt > 0:
                logger.info(f"    -> Retrying... (Attempt {attempt + 1}/{max_attempts})")
                await asyncio.sleep(retry_interval)

            try:
                action_name = step_data.get('action')
                if action_name and action_name.lower() == 'run_task':
                    result = await self._run_sub_task(step_data, injector=active_injector)
                    if isinstance(result, JumpSignal): raise result
                elif action_name:
                    result = await active_injector.execute(action_name, step_data.get('params', {}))
                else:  # A step with no action (e.g., just for 'when' logic) is a success
                    result = True

                is_logical_failure = (result is False or (hasattr(result, 'found') and result.found is False))
                if not is_logical_failure:
                    # 'output_to' is handled by the calling function (_execute_linear_script_node or direct assignment)
                    return result  # Success
                else:
                    last_exception = StopTaskException(f"Action '{action_name}' returned a failure status.",
                                                       success=False)

            except Exception as e:
                last_exception = e

        step_name = step_data.get('name', step_data.get('action', 'unnamed_step'))
        logger.error(f"  -> Step '{step_name}' failed after {max_attempts} attempts.")
        await self._capture_debug_screenshot(step_name)
        raise last_exception or StopTaskException(f"Step '{step_name}' failed.", success=False)

    # Helper methods (check_pause, capture_screenshot, run_sub_task) remain largely the same,
    # but run_sub_task is adapted to accept an injector.

    async def _check_pause(self):
        if self.pause_event.is_set():
            logger.warning("接收到全局暂停信号，任务执行已暂停。等待恢复信号...")
            await self.pause_event.wait()
            logger.info("接收到恢复信号，任务将继续执行。")

    async def _run_sub_task(self, step_data: Dict[str, Any], injector: ActionInjector) -> Any:
        if not self.orchestrator: return False
        rendered_params = await injector._render_params(step_data.get('params', {}))
        sub_task_id = rendered_params.get('task_name')
        if not sub_task_id: return False

        sub_task_data = self.orchestrator.load_task_data(sub_task_id)
        if not sub_task_data: return False

        sub_context = injector.context.fork()
        for key, value in rendered_params.get('pass_params', {}).items():
            sub_context.set(key, value)

        sub_engine = ExecutionEngine(sub_context, self.orchestrator, self.pause_event)
        sub_task_result = await sub_engine.run(sub_task_data, sub_task_id)

        if sub_task_result.get('status') == 'go_task': return JumpSignal('go_task', sub_task_result['next_task'])
        if sub_task_result.get('status') == 'success' and sub_task_result.get('next_task'): self.next_task_target = \
        sub_task_result['next_task']

        return_value = {}
        if isinstance(sub_task_data.get('outputs'), dict):
            sub_injector = ActionInjector(sub_context, sub_engine)
            for key, value_expr in sub_task_data['outputs'].items():
                return_value[key] = await sub_injector._render_value(value_expr, sub_context._data)
        return return_value

    async def _capture_debug_screenshot(self, failed_step_name: str):
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


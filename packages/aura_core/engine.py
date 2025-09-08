# packages/aura_core/engine.py (Stage 1 Refactor)
import asyncio
import os
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Iterable, Tuple

from packages.aura_core.logger import logger
from .action_injector import ActionInjector
from .api import service_registry
from .context import Context
from .exceptions import StopTaskException


# --- Data Structures and Enums ---

class JumpSignal(Exception):
    """Exception used for non-local control flow, like go_task."""

    def __init__(self, jump_type: str, target: str):
        self.type = jump_type
        self.target = target
        super().__init__(f"JumpSignal: type={self.type}, target={self.target}")


class StepState(Enum):
    """Represents the execution state of a single node in the DAG."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


# --- Main Execution Engine ---

class ExecutionEngine:
    """
    【Advanced Flow Refactor - Stage 1】
    New generation engine with a custom scheduler supporting boolean dependencies
    and advanced node types like 'switch'.
    """

    def __init__(self, context: Context, orchestrator=None, pause_event: asyncio.Event = None,
                 parent_node_id: str = ""):
        self.context = context
        self.orchestrator = orchestrator
        self.pause_event = pause_event if pause_event else asyncio.Event()
        self.injector = ActionInjector(context, engine=self)
        self.next_task_target: Optional[str] = None
        self.engine_id = parent_node_id or str(uuid.uuid4())[:8]

        # --- Graph and State Structures ---
        self.nodes: Dict[str, Dict] = {}
        self.dependencies: Dict[str, Any] = {}
        self.reverse_dependencies: Dict[str, Set[str]] = {}
        self.step_states: Dict[str, StepState] = {}
        self.step_results: Dict[str, Any] = {}

        # --- Scheduler State ---
        self.running_tasks: Set[asyncio.Task] = set()
        self.completion_event: Optional[asyncio.Event] = None

    async def run(self, task_data: Dict[str, Any], task_name: str) -> Dict[str, Any]:
        """Main execution entry point for a task or sub-graph."""
        task_display_name = task_data.get('meta', {}).get('title', task_name)
        if not self.context.is_sub_context():  # Log only for top-level tasks
            logger.info(f"======= 开始执行任务: {task_display_name} =======")

        steps = task_data.get('steps', {})
        if isinstance(steps, list):
            logger.warning("检测到旧的线性列表 'steps' 格式。将自动转换为兼容的DAG格式。")
            steps = self._convert_linear_list_to_dag(steps)

        if not isinstance(steps, dict) or not steps:
            return {'status': 'success', 'message': '任务中没有可执行的步骤。'}

        final_result = {}
        try:
            self._build_graph(steps)
            # Make results available to the top-level context immediately
            if not self.context.is_sub_context():
                self.context.set('steps', self.step_results)
            await self._run_dag_scheduler()
        except JumpSignal as e:
            raise e
        except Exception as e:
            logger.error(f"!! 任务 '{task_name}' 执行时发生未捕获的严重错误: {e}", exc_info=True)
            final_result = {
                'status': 'error',
                'error_details': {'node_id': 'pre-execution', 'message': str(e), 'type': type(e).__name__}
            }

        if not final_result:
            final_status = 'success'
            failing_node_details = None
            for node_id, state in self.step_states.items():
                if state == StepState.FAILED:
                    final_status = 'error'
                    failing_node_details = self.step_results.get(node_id, {}).get('error_details')
                    break
            final_result = {'status': final_status, 'results': self.step_results}
            if failing_node_details:
                final_result['error_details'] = failing_node_details

        if not self.context.is_sub_context():
            logger.info(f"======= 任务 '{task_display_name}' 执行结束 (状态: {final_result.get('status')}) =======")
        if self.next_task_target:
            final_result['next_task'] = self.next_task_target
        return final_result
    # --- Graph Building and Validation ---

    def _build_graph(self, steps_dict: Dict[str, Any]):
        """Builds the internal graph representation, aware of all advanced node types."""
        self.nodes = steps_dict
        all_node_ids = set(self.nodes.keys())

        for node_id, node_data in self.nodes.items():
            self.step_states[node_id] = StepState.PENDING
            self.reverse_dependencies.setdefault(node_id, set())
            deps_struct = node_data.get('depends_on', [])
            self.dependencies[node_id] = deps_struct
            all_deps = self._get_all_deps_from_struct(deps_struct)

            if 'switch' in node_data: all_deps.update(self._get_deps_from_switch(node_data['switch']))
            elif 'for_each' in node_data: all_deps.update(self._get_all_deps_from_struct(node_data['for_each'].get('do', {})))
            elif 'while' in node_data: all_deps.update(self._get_all_deps_from_struct(node_data['while'].get('do', {})))
            elif 'try' in node_data: all_deps.update(self._get_deps_from_try_catch(node_data))

            for dep_id in all_deps:
                if dep_id not in all_node_ids:
                    raise KeyError(f"节点 '{node_id}' 或其子结构引用了未知的依赖: '{dep_id}'")
                self.reverse_dependencies.setdefault(dep_id, set()).add(node_id)

        for node_id in all_node_ids:
            if node_id in self._get_all_deps_from_struct(self.dependencies.get(node_id, [])):
                raise ValueError(f"检测到直接循环依赖于自身的节点: '{node_id}'")

    def _get_deps_from_switch(self, switch_config: Dict) -> Set[str]:
        deps = set()
        for case in switch_config.get('cases', []):
            if 'then' in case: deps.add(case['then'])
        if 'default' in switch_config:
            deps.add(switch_config['default'])
        return deps
    def _get_all_deps_from_struct(self, struct: Any) -> Set[str]:
        """Recursively extracts all node ID strings from a dependency structure."""
        deps = set()
        if isinstance(struct, str):
            deps.add(struct)
        elif isinstance(struct, list):
            for item in struct:
                deps.update(self._get_all_deps_from_struct(item))
        elif isinstance(struct, dict):
            for key, value in struct.items():
                deps.update(self._get_all_deps_from_struct(value))
        return deps

    def _get_deps_from_try_catch(self, node_data: Dict) -> Set[str]:
        deps = set()
        if 'try' in node_data and 'do' in node_data['try']:
            deps.update(self._get_all_deps_from_struct(node_data['try']['do']))
        if 'catch' in node_data and 'do' in node_data['catch']:
            deps.update(self._get_all_deps_from_struct(node_data['catch']['do']))
        if 'finally' in node_data and 'do' in node_data['finally']:
            deps.update(self._get_all_deps_from_struct(node_data['finally']['do']))
        return deps

    # --- Core DAG Scheduler ---

    async def _run_dag_scheduler(self):
        """New event-driven DAG scheduler."""
        self.completion_event = asyncio.Event()
        self._schedule_ready_nodes()

        if not self.running_tasks and self.nodes:
            # Check if any nodes were scheduled. If not, the graph might be invalid.
            if all(state == StepState.PENDING for state in self.step_states.values()):
                raise ValueError("任务图中没有可作为起点的节点（所有节点都有依赖）。")

        if self.running_tasks:
            await self.completion_event.wait()

    def _schedule_ready_nodes(self):
        """Finds and schedules all nodes that are currently ready to run."""
        for node_id in self.nodes:
            if self.step_states[node_id] == StepState.PENDING and self._are_dependencies_met(node_id):
                task = asyncio.create_task(self._execute_dag_node(node_id))
                self.running_tasks.add(task)
                task.add_done_callback(self._on_task_completed)

    def _on_task_completed(self, task: asyncio.Task):
        """Callback function for when a node's asyncio task finishes."""
        self.running_tasks.discard(task)
        # After a task finishes, new nodes might become ready.
        self._schedule_ready_nodes()
        # If no tasks are left running, the entire DAG is done.
        if not self.running_tasks:
            if self.completion_event:
                self.completion_event.set()

    # --- Dependency Evaluation ---

    def _are_dependencies_met(self, node_id: str) -> bool:
        """Evaluates the boolean dependency structure for a node."""
        dep_struct = self.dependencies.get(node_id, [])
        return self._evaluate_dep_struct(dep_struct)

    def _evaluate_dep_struct(self, struct: Any) -> bool:
        """Recursively evaluates a dependency structure to True or False."""
        if isinstance(struct, str):
            return self.step_states.get(struct) == StepState.SUCCESS

        if isinstance(struct, list):
            return all(self._evaluate_dep_struct(item) for item in struct)

        if isinstance(struct, dict):
            if 'and' in struct:
                return self._evaluate_dep_struct(struct['and'])
            if 'or' in struct:
                return any(self._evaluate_dep_struct(item) for item in struct['or'])
            if 'not' in struct:
                sub_deps = self._get_all_deps_from_struct(struct['not'])
                if any(self.step_states.get(dep) in (StepState.PENDING, StepState.RUNNING) for dep in sub_deps):
                    return False
                return not self._evaluate_dep_struct(struct['not'])

        return True  # No dependencies

    # --- Node Execution Logic ---

    async def _execute_dag_node(self, node_id: str):
        """Dispatcher for executing a single DAG node based on its type."""
        if self.step_states.get(node_id) != StepState.PENDING:
            return

        self.step_states[node_id] = StepState.RUNNING
        node_data = self.nodes[node_id]
        node_name = node_data.get('name', node_id)
        logger.info(f"\n[Node]: Starting '{node_name}' (ID: {node_id})")

        try:
            await self._check_pause()

            if 'when' in node_data:
                condition = await self.injector._render_value(node_data['when'], self.context._data)
                if not condition:
                    logger.info(f"  -> Skipping '{node_name}' because 'when' condition was false.")
                    self.step_states[node_id] = StepState.SKIPPED
                    self.step_results[node_id] = {'status': 'skipped', 'reason': 'when condition was false'}
                    return

            if 'try' in node_data:
                node_result = await self._execute_try_catch_finally_node(node_id, node_data)
            elif 'for_each' in node_data:
                node_result = await self._execute_for_each_node(node_id, node_data)
            elif 'while' in node_data:
                node_result = await self._execute_while_node(node_id, node_data)
            elif 'switch' in node_data:
                node_result = await self._execute_switch_node(node_id, node_data)
            elif 'do' in node_data:
                node_result = await self._execute_linear_script_node(node_data['do'])
            elif 'action' in node_data:
                node_result = await self._execute_single_action_step(node_data)
            else:
                raise ValueError(f"Node '{node_id}' must contain a valid execution block.")

            self.step_results[node_id] = {'status': 'success', 'result': node_result}
            self.step_states[node_id] = StepState.SUCCESS
            logger.info(f"[Node]: Finished '{node_name}' successfully.")

        except Exception as e:
            error_details = {'node_id': node_id, 'message': str(e), 'type': type(e).__name__}
            logger.error(f"!! [Node]: Failed '{node_name}': {e}", exc_info=True)

            # --- Node-level on_failure handling ---
            if 'on_failure' in node_data:
                logger.warning(f"  -> Node '{node_name}' failed. Executing 'on_failure' handler...")
                try:
                    await self._run_failure_handler_script(node_data['on_failure'], error_details)
                except Exception as handler_e:
                    logger.critical(
                        f"  -> !! The 'on_failure' handler for node '{node_name}' itself failed: {handler_e}",
                        exc_info=True)

            # The node is always marked as FAILED after an exception, regardless of the handler's success.
            self.step_states[node_id] = StepState.FAILED
            self.step_results[node_id] = {'status': 'failed', 'error_details': error_details}

    async def _execute_try_catch_finally_node(self, node_id: str, node_data: Dict) -> Any:
        """Handles the complex logic for a 'try...catch...finally' block."""
        try_config = node_data.get('try', {})
        catch_config = node_data.get('catch', {})
        finally_config = node_data.get('finally', {})

        try_result, try_error_details = None, None
        final_node_status = StepState.SUCCESS

        # 1. Execute TRY block
        if 'do' in try_config:
            logger.info(f"  -> [Try-Catch] Entering 'try' block for '{node_id}'.")
            sub_engine = ExecutionEngine(self.context.fork(), self.orchestrator, self.pause_event,
                                         f"{self.engine_id}.{node_id}.try")
            result = await sub_engine.run({'steps': try_config['do']}, "try_block")
            if result['status'] != 'success':
                try_error_details = result.get('error_details')
            else:
                try_result = result['results']

        # 2. Execute CATCH block (if TRY failed)
        if try_error_details and 'do' in catch_config:
            logger.warning(f"  -> [Try-Catch] 'try' block failed. Entering 'catch' block for '{node_id}'.")
            catch_context = self.context.fork()
            catch_context.set('error', try_error_details)
            sub_engine = ExecutionEngine(catch_context, self.orchestrator, self.pause_event,
                                         f"{self.engine_id}.{node_id}.catch")
            result = await sub_engine.run({'steps': catch_config['do']}, "catch_block")

            if result['status'] != 'success':
                logger.error(f"  -> [Try-Catch] 'catch' block itself failed. The entire 'try' node will fail.")
                final_node_status = StepState.FAILED
                # Re-raise the catch block's exception to fail the whole node
                raise StopTaskException(f"Catch block failed: {result.get('error_details', 'Unknown')}")

            if catch_config.get('continue_on_success', False):
                logger.info(
                    "  -> [Try-Catch] 'catch' block succeeded and 'continue_on_success' is true. The error is considered handled.")
                final_node_status = StepState.SUCCESS
                try_result = result['results']  # The result is now the catch block's result
            else:
                final_node_status = StepState.FAILED
        elif try_error_details:
            final_node_status = StepState.FAILED

        # 3. Execute FINALLY block (always)
        if 'do' in finally_config:
            logger.info(f"  -> [Try-Catch] Entering 'finally' block for '{node_id}'.")
            finally_context = self.context.fork()
            finally_context.set('status', 'SUCCESS' if not try_error_details else 'FAILED')
            if try_error_details:
                finally_context.set('error', try_error_details)

            sub_engine = ExecutionEngine(finally_context, self.orchestrator, self.pause_event,
                                         f"{self.engine_id}.{node_id}.finally")
            result = await sub_engine.run({'steps': finally_config['do']}, "finally_block")

            if result['status'] != 'success':
                logger.critical(
                    f"  -> [Try-Catch] 'finally' block failed. This is a critical error. The entire 'try' node will fail.")
                final_node_status = StepState.FAILED
                raise StopTaskException(f"Finally block failed: {result.get('error_details', 'Unknown')}")

        if final_node_status == StepState.FAILED:
            raise StopTaskException(f"'try' node '{node_id}' failed. Original error: {try_error_details}")

        return try_result

    async def _run_failure_handler_script(self, failure_data: Dict, error_details: Dict):
        """Executes a simple linear script for an on_failure block."""
        handler_context = self.context.fork()
        handler_context.set('error', error_details)
        # on_failure handlers are always linear scripts
        sub_steps = failure_data.get('do', [])
        if not sub_steps: return

        # We re-use the linear script executor, but with the special handler context
        handler_injector = ActionInjector(handler_context, engine=self)
        for i, step_data in enumerate(sub_steps):
            step_name = step_data.get('name', f"on_failure sub-step {i + 1}")
            logger.info(f"    -> [on_failure]: {step_name}")
            # This is a simplified execution, no complex results or outputs, just run the actions.
            await self._execute_single_action_step(step_data, injector=handler_injector)

    async def _execute_for_each_node(self, node_id: str, node_data: Dict) -> List[Any]:
        """Handles the fan-out/fan-in logic for a 'for_each' node."""
        config = node_data['for_each']
        items_to_iterate = await self.injector._render_value(config['in'], self.context._data)
        item_var_name = config.get('as', 'item')
        sub_graph_template = config['do']

        if not isinstance(items_to_iterate, Iterable):
            raise TypeError(
                f"'for_each' node '{node_id}' 'in' clause did not resolve to an iterable, got {type(items_to_iterate)}.")

        sub_engines: List[Tuple[ExecutionEngine, Dict]] = []
        for i, item in enumerate(items_to_iterate):
            sub_context = self.context.fork()
            sub_context.set(item_var_name, item)
            sub_context.set('index', i)

            # Create a sub-engine for each iteration
            sub_engine_id = f"{self.engine_id}.{node_id}[{i}]"
            sub_engine = ExecutionEngine(sub_context, self.orchestrator, self.pause_event, parent_node_id=sub_engine_id)
            sub_engines.append((sub_engine, sub_graph_template))

        # Run all sub-graphs in parallel
        results = await asyncio.gather(
            *[engine.run(task_data, f"for_each_sub_graph_{i}") for i, (engine, task_data) in enumerate(sub_engines)]
        )

        # Check for failures in any sub-graph
        final_results = []
        for i, result in enumerate(results):
            if result['status'] != 'success':
                raise StopTaskException(
                    f"'for_each' node '{node_id}' failed on iteration {i}. Reason: {result.get('error_details', 'Unknown')}")
            final_results.append(result['results'])

        return final_results

    async def _execute_while_node(self, node_id: str, node_data: Dict) -> Dict:
        """Handles the conditional looping logic for a 'while' node."""
        config = node_data['while']
        condition_template = config['condition']
        limit = int(config.get('limit', 10))
        sub_graph_template = config['do']

        iteration = 0
        last_result = None
        loop_context = self.context.fork()  # Use a dedicated context for the loop

        while iteration < limit:
            # Render condition in the current loop's context
            condition = await self.injector._render_value(condition_template, loop_context._data)
            if not condition:
                logger.info(f"  -> 'while' node '{node_id}' condition is false. Exiting loop.")
                break

            logger.info(f"  -> 'while' node '{node_id}' starting iteration {iteration + 1}/{limit}.")

            # Create and run a sub-engine for this iteration
            sub_engine_id = f"{self.engine_id}.{node_id}({iteration})"
            sub_engine = ExecutionEngine(loop_context, self.orchestrator, self.pause_event,
                                         parent_node_id=sub_engine_id)

            result = await sub_engine.run(sub_graph_template, f"while_sub_graph_{iteration}")

            if result['status'] != 'success':
                raise StopTaskException(
                    f"'while' node '{node_id}' failed in iteration {iteration + 1}. Reason: {result.get('error_details', 'Unknown')}")

            # Update loop context with the results of the sub-graph for the next condition check
            loop_context.set('steps', result['results'])
            last_result = result['results']
            iteration += 1

        if iteration >= limit:
            logger.warning(f"'while' node '{node_id}' reached its iteration limit of {limit}.")

        return {'iterations': iteration, 'last_result': last_result}


    async def _execute_switch_node(self, node_id: str, node_data: Dict) -> str:
        """Handles the logic for a 'switch' node."""
        switch_config = node_data['switch']
        target_node = switch_config.get('default')
        path_found = False

        for case in switch_config.get('cases', []):
            condition = await self.injector._render_value(case['when'], self.context._data)
            if condition:
                target_node = case.get('then')
                path_found = True
                break

        if not path_found and target_node is None:
            logger.warning(f"'switch' node '{node_id}' resolved with no target. No path taken.")
            return "No path taken"

        logger.info(f"  -> 'switch' node '{node_id}' resolved to path '{target_node}'.")

        all_potential_targets = set(c.get('then') for c in switch_config.get('cases', []) if 'then' in c)
        if 'default' in switch_config:
            all_potential_targets.add(switch_config['default'])

        for potential_target in all_potential_targets:
            if potential_target != target_node:
                if self.step_states.get(potential_target) == StepState.PENDING:
                    self.step_states[potential_target] = StepState.SKIPPED
                    self.step_results[potential_target] = {'status': 'skipped',
                                                           'reason': f"Not chosen by switch node '{node_id}'"}

        return f"Path taken: {target_node}"

    # --- Unchanged Helper Methods (Copied from original for completeness) ---

    def _convert_linear_list_to_dag(self, linear_steps: List[Dict]) -> Dict[str, Any]:
        """Converts a legacy list of steps into a single-node DAG with a 'do' block."""
        return {
            "__legacy_linear_task": {
                "name": "Legacy Linear Task",
                "do": linear_steps
            }
        }

    async def _execute_linear_script_node(self, sub_steps: List[Dict]) -> Any:
        """Executes a list of steps sequentially within an isolated sub-context."""
        sub_context = self.context.fork()
        sub_injector = ActionInjector(sub_context, engine=self)
        last_result = None

        for i, step_data in enumerate(sub_steps):
            step_name = step_data.get('name', f"sub-step {i + 1}")
            logger.info(f"  -> [Linear Sub-Step]: {step_name}")
            try:
                if 'when' in step_data:
                    condition = await sub_injector._render_value(step_data['when'], sub_context._data)
                    if not condition:
                        logger.info(f"    -> Skipping sub-step '{step_name}' because 'when' condition was false.")
                        continue

                step_result = await self._execute_single_action_step(step_data, injector=sub_injector)

                if 'output_to' in step_data:
                    sub_context.set(step_data['output_to'], step_result)
                last_result = step_result
            except Exception as e:
                logger.error(f"    -> Sub-step '{step_name}' failed. Aborting linear script node.")
                self.context.merge(sub_context)
                raise e
        self.context.merge(sub_context)
        return last_result

    async def _execute_single_action_step(self, step_data: Dict[str, Any],
                                          injector: Optional[ActionInjector] = None) -> Any:
        """
        【最终确认版 for new ActionInjector】
        执行单个动作，包含重试逻辑。现在完全委托给 ActionInjector 执行。
        """
        active_injector = injector or self.injector

        # --- 预处理部分 (保持不变) ---
        if 'next' in step_data:
            self.next_task_target = await active_injector._render_value(step_data['next'],
                                                                        active_injector.context._data)

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
                if not action_name:
                    return True  # 无操作步骤，直接成功

                # --- 【核心确认】直接调用注入器的 execute 方法 ---
                # 你的新版 injector.execute 已经包含了所有智能调度逻辑
                if action_name.lower() == 'run_task':
                    result = await self._run_sub_task(step_data, injector=active_injector)
                else:
                    result = await active_injector.execute(action_name, step_data.get('params', {}))

                # --- 结果处理部分 (保持不变) ---
                is_logical_failure = (result is False or (hasattr(result, 'found') and result.found is False))
                if not is_logical_failure:
                    return result
                else:
                    last_exception = StopTaskException(f"Action '{action_name}' returned a failure status.",
                                                       success=False)

            except JumpSignal:
                raise
            except Exception as e:
                last_exception = e

        # --- 失败处理部分 (保持不变) ---
        step_name = step_data.get('name', step_data.get('action', 'unnamed_step'))
        logger.error(f"  -> Step '{step_name}' failed after {max_attempts} attempts.")
        await self._capture_debug_screenshot(step_name)
        raise last_exception or StopTaskException(f"Step '{step_name}' failed.", success=False)

    async def _check_pause(self):
        if self.pause_event.is_set():
            logger.warning("接收到全局暂停信号，任务执行已暂停。等待恢复信号...")
            await self.pause_event.wait()
            logger.info("接收到恢复信号，任务将继续执行。")

    async def _run_sub_task(self, step_data: Dict[str, Any], injector: ActionInjector) -> Any:
        """
        【升级版】执行一个子任务，支持通过 'with' 传递参数，并通过子任务的 'returns' 字段接收返回值。
        """
        if not self.orchestrator:
            logger.error("无法执行子任务：Engine 未关联到 Orchestrator。")
            return False

        rendered_params = await injector._render_params(step_data.get('params', {}))
        sub_task_id = rendered_params.get('task_name')
        if not sub_task_id:
            logger.error("run_task 失败：'task_name' 参数缺失。")
            return False

        sub_task_data = self.orchestrator.load_task_data(sub_task_id)
        if not sub_task_data:
            logger.error(f"run_task 失败：找不到子任务定义 '{sub_task_id}'。")
            return False

        # 1. 【升级】创建隔离上下文并传递参数
        #    - 使用 'with' 作为新的标准参数键。
        #    - 为了向后兼容，仍然支持旧的 'pass_params'。
        sub_context = injector.context.fork()
        params_to_pass = rendered_params.get('with', rendered_params.get('pass_params', {}))

        # 【新】将传入的参数也放入子上下文的 'params' 命名空间下，方便子任务引用
        sub_context.set('params', params_to_pass)
        # 也将参数直接注入顶层，方便直接访问
        for key, value in params_to_pass.items():
            sub_context.set(key, value)

        logger.info(f"  -> 调用子任务 '{sub_task_id}' 并传递参数: {list(params_to_pass.keys())}")

        # 2. 创建新的引擎实例并执行子任务
        sub_engine_id = f"{self.engine_id}.{sub_task_id}"
        sub_engine = ExecutionEngine(sub_context, self.orchestrator, self.pause_event, parent_node_id=sub_engine_id)
        # 【关键】直接调用 Orchestrator.execute_task，因为它已经包含了处理 'returns' 的逻辑
        sub_task_result = await self.orchestrator.execute_task(
            task_name_in_plan=sub_task_id.split('/', 1)[1] if '/' in sub_task_id else sub_task_id,
            initial_data=params_to_pass  # 直接将初始数据传递下去
        )

        # 3. 【升级】处理返回值
        #    Orchestrator.execute_task 的返回值就是子任务 `returns` 字段渲染后的结果。
        #    我们不再需要手动处理旧的 'outputs' 字段。
        #    如果子任务执行失败或跳转，Orchestrator 会抛出异常或返回特殊字典，我们需要处理这些情况。

        if isinstance(sub_task_result, dict):
            # 检查是否是跳转信号
            if sub_task_result.get('status') == 'go_task':
                raise JumpSignal('go_task', sub_task_result['next_task'])
            # 检查是否是错误信号
            if sub_task_result.get('status') == 'error':
                logger.error(f"  -> 子任务 '{sub_task_id}' 执行失败。")
                # 让整个 run_task 步骤失败
                return False

                # 如果不是特殊信号字典，那么 sub_task_result 就是子任务的返回值
        logger.info(f"  -> 子任务 '{sub_task_id}' 返回结果: {repr(sub_task_result)}")
        return sub_task_result
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

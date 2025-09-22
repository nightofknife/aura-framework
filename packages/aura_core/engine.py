# packages/aura_core/engine.py (FIXED VERSION)

import asyncio
import os
import time
import traceback
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Iterable, Tuple, Callable

from packages.aura_core.logger import logger
from .action_injector import ActionInjector
from .api import service_registry
from .context import Context
from .exceptions import StopTaskException, JumpSignal


class StepState(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ExecutionEngine:
    def __init__(self, context: Context, orchestrator=None, pause_event: asyncio.Event = None,
                 parent_node_id: str = "", event_callback: Optional[Callable] = None):
        self.context = context
        self.orchestrator = orchestrator
        self.pause_event = pause_event if pause_event else asyncio.Event()
        self.injector = ActionInjector(context, engine=self)
        self.next_task_target: Optional[str] = None
        self.engine_id = parent_node_id or str(uuid.uuid4())[:8]
        self.event_callback = event_callback

        self.nodes: Dict[str, Dict] = {}
        self.dependencies: Dict[str, Any] = {}
        self.reverse_dependencies: Dict[str, Set[str]] = {}
        self.step_states: Dict[str, StepState] = {}
        self.step_results: Dict[str, Any] = {}

        self.running_tasks: Set[asyncio.Task] = set()
        self.completion_event: Optional[asyncio.Event] = None

        # 【新增】debug_mode 从 orchestrator/scheduler 继承，用于控制 traceback 包含
        self.debug_mode = getattr(orchestrator, 'debug_mode', True) if orchestrator else True

    async def run(self, task_data: Dict[str, Any], task_name: str) -> Dict[str, Any]:
        task_display_name = task_data.get('meta', {}).get('title', task_name)
        if not self.context.is_sub_context():
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
            if not self.context.is_sub_context():
                self.context.set('steps', self.step_results)
            await self._run_dag_scheduler()  # 假设调用 _execute_dag_node
        except JumpSignal as e:
            # 【修改】记录栈，不 raise（返回 signal）
            logger.info(f"Jump signal in task '{task_name}': {e.type} to {e.target}", exc_info=True)
            final_result = {'status': e.type, 'jump_target': e.target}
            if self.debug_mode:
                final_result['traceback'] = e.get_full_traceback()
            raise e  # 或不 raise，根据需求返回
        except StopTaskException as e:
            # 【新增】处理 StopTask
            logger.error(f"StopTask in task '{task_name}': {e} (severity: {e.severity})", exc_info=True)
            final_result = {'status': 'stopped', 'severity': e.severity}
            if self.debug_mode:
                final_result['traceback'] = e.get_full_traceback()
            raise  # 传播
        except Exception as e:
            logger.error(f"!! 任务 '{task_name}' 执行时发生未捕获的严重错误: {e}", exc_info=True)  # 【确认】已有
            final_result = {
                'status': 'error',
                'error_details': {'node_id': 'pre-execution', 'message': str(e), 'type': type(e).__name__}
            }
            if self.debug_mode:
                final_result['traceback'] = e.get_full_traceback() if hasattr(e,
                                                                              'get_full_traceback') else traceback.format_exc()

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

    def _build_graph(self, steps_dict: Dict[str, Any]):
        self.nodes = steps_dict
        all_node_ids = set(self.nodes.keys())
        for node_id, node_data in self.nodes.items():
            self.step_states[node_id] = StepState.PENDING
            self.reverse_dependencies.setdefault(node_id, set())

            # 1. Get the explicit 'depends_on' structure for the top-level node.
            deps_struct = node_data.get('depends_on', [])
            self.dependencies[node_id] = deps_struct
            all_deps = self._get_all_deps_from_struct(deps_struct)

            # 2. Handle 'switch' specifically, as it directly affects the main graph's flow by jumping to other top-level nodes.
            if 'switch' in node_data:
                all_deps.update(self._get_deps_from_switch(node_data['switch']))


            # 3. Validate the collected dependencies against top-level node IDs.
            for dep_id in all_deps:
                if dep_id not in all_node_ids:
                    raise KeyError(f"节点 '{node_id}' 引用了未知的顶层依赖: '{dep_id}'")
                self.reverse_dependencies.setdefault(dep_id, set()).add(node_id)

            # 4. Check for self-dependency.
            if node_id in self._get_all_deps_from_struct(self.dependencies.get(node_id, [])):
                raise ValueError(f"检测到直接循环依赖于自身的节点: '{node_id}'")

    # ... (all other methods from _get_deps_from_switch onwards are unchanged) ...
    def _get_deps_from_switch(self, switch_config: Dict) -> Set[str]:
        deps = set()
        for case in switch_config.get('cases', []):
            if 'then' in case: deps.add(case['then'])
        if 'default' in switch_config: deps.add(switch_config['default'])
        return deps

    def _get_all_deps_from_struct(self, struct: Any) -> Set[str]:
        deps = set()
        if isinstance(struct, str):
            deps.add(struct)
        elif isinstance(struct, list):
            for item in struct: deps.update(self._get_all_deps_from_struct(item))
        elif isinstance(struct, dict):
            for key, value in struct.items(): deps.update(self._get_all_deps_from_struct(value))
        return deps

    def _get_deps_from_try_catch(self, node_data: Dict) -> Set[str]:
        deps = set()
        if 'try' in node_data and 'do' in node_data['try']: deps.update(
            self._get_all_deps_from_struct(node_data['try']['do']))
        if 'catch' in node_data and 'do' in node_data['catch']: deps.update(
            self._get_all_deps_from_struct(node_data['catch']['do']))
        if 'finally' in node_data and 'do' in node_data['finally']: deps.update(
            self._get_all_deps_from_struct(node_data['finally']['do']))
        return deps

    async def _run_dag_scheduler(self):
        self.completion_event = asyncio.Event()
        self._schedule_ready_nodes()
        if not self.running_tasks and self.nodes:
            if all(state == StepState.PENDING for state in self.step_states.values()):
                raise ValueError("任务图中没有可作为起点的节点（所有节点都有依赖）。")
        if self.running_tasks: await self.completion_event.wait()

    def _schedule_ready_nodes(self):
        for node_id in self.nodes:
            if self.step_states[node_id] == StepState.PENDING and self._are_dependencies_met(node_id):
                task = asyncio.create_task(self._execute_dag_node(node_id))
                self.running_tasks.add(task)
                task.add_done_callback(self._on_task_completed)

    def _on_task_completed(self, task: asyncio.Task):
        self.running_tasks.discard(task)
        self._schedule_ready_nodes()
        if not self.running_tasks:
            if self.completion_event: self.completion_event.set()

    def _are_dependencies_met(self, node_id: str) -> bool:
        dep_struct = self.dependencies.get(node_id, [])
        return self._evaluate_dep_struct(dep_struct)

    def _evaluate_dep_struct(self, struct: Any) -> bool:
        if isinstance(struct, str): return self.step_states.get(struct) == StepState.SUCCESS
        if isinstance(struct, list): return all(self._evaluate_dep_struct(item) for item in struct)
        if isinstance(struct, dict):
            if 'and' in struct: return self._evaluate_dep_struct(struct['and'])
            if 'or' in struct: return any(self._evaluate_dep_struct(item) for item in struct['or'])
            if 'not' in struct:
                sub_deps = self._get_all_deps_from_struct(struct['not'])
                if any(self.step_states.get(dep) in (StepState.PENDING, StepState.RUNNING) for dep in
                       sub_deps): return False
                return not self._evaluate_dep_struct(struct['not'])
        return True

    async def _execute_dag_node(self, node_id: str, parent_node_id: str = "",
                                result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """【新增/增强】执行单个 DAG 节点，支持异常栈保留。"""
        if result is None:
            result = {'node_id': node_id, 'status': 'success', 'output': {}, 'children': []}  # 【新增】result for traceback
        original_exc = None

        try:
            node_data = self.nodes.get(node_id)
            if not node_data:
                raise ValueError(f"Node data not found for '{node_id}'")

            # 原执行逻辑（调用子方法，不变）
            if self.event_callback:
                await self.event_callback('node.started', {'node_id': node_id})
            await self._check_pause()

            if node_data.get('type') == 'try_catch_finally' or 'try' in node_data:
                child_result = await self._execute_try_catch_finally_node(node_id, node_data)
            elif 'for_each' in node_data:
                child_result = await self._execute_for_each_node(node_id, node_data)
            elif 'while' in node_data:
                child_result = await self._execute_while_node(node_id, node_data)
            elif 'switch' in node_data:
                child_result = await self._execute_switch_node(node_id, node_data)
            elif 'do' in node_data:
                child_result = await self._execute_linear_script_node(node_data['do'])
            elif 'action' in node_data:
                child_result = await self._execute_single_action_step(node_data)
            else:
                raise ValueError(f"Unknown node type for '{node_id}'")

            result['output'] = child_result
            result['status'] = 'success'
            result['children'].append(child_result)  # 递归合并

            if self.event_callback:
                await self.event_callback('node.succeeded', {'node_id': node_id, 'output': child_result})

        except JumpSignal as e:
            # 【新增】捕获并记录完整栈
            logger.info(f"Jump caught in node {node_id}: {e.type} to {e.target}", exc_info=True)
            result['status'] = e.type  # e.g., 'break'
            result['jump_target'] = e.target
            if self.debug_mode:
                result['traceback'] = e.get_full_traceback()  # 【新增】完整栈
            # 不 raise，继续返回 signal status（控制流）

        except StopTaskException as e:
            # 【新增】根据 severity 处理
            logger.error(f"StopTask in node {node_id}: {e} (severity: {e.severity})", exc_info=True)
            result['status'] = 'stopped'
            result['severity'] = e.severity
            if self.debug_mode:
                result['traceback'] = e.get_full_traceback()
            raise  # 传播（上层如 orchestrator 处理 severity）

        except Exception as e:
            original_exc = e  # 【新增】
            logger.error(f"Unexpected error in node {node_id}: {e}", exc_info=True)
            result['status'] = 'error'
            result['error'] = str(e)
            if self.debug_mode:
                result['traceback'] = e.get_full_traceback() if hasattr(e,
                                                                        'get_full_traceback') else traceback.format_exc()  # 【新增】
            raise

        return result
    async def _execute_try_catch_finally_node(self, node_id: str, node_data: Dict) -> Any:
        """【增强】执行 try-catch-finally 节点，支持 finally_on_failure 灵活性。"""
        try_config = node_data.get('try', {})
        catch_config = node_data.get('catch', {})
        finally_config = node_data.get('finally', {})
        try_result, try_error_details = None, None
        final_node_status = StepState.SUCCESS
        original_exc = None  # 【新增】跟踪原始异常

        # 【新增】解析 finally_on_failure（YAML 默认 'raise'，兼容旧）
        on_failure = node_data.get('finally_on_failure', 'raise')  # 'raise' | 'ignore' | 'log'

        # 执行 try
        if 'do' in try_config:
            logger.info(f"  -> [Try-Catch] Entering 'try' block for '{node_id}'.")
            sub_engine = ExecutionEngine(self.context.fork(), self.orchestrator, self.pause_event,
                                         f"{self.engine_id}.{node_id}.try")
            result = await sub_engine.run({'steps': try_config['do']}, "try_block")
            if result['status'] != 'success':
                try_error_details = result.get('error_details')
                original_exc = try_error_details.get('error') or Exception(
                    try_error_details.get('message', 'Try failed'))  # 【新增】提取 exc
            else:
                try_result = result['results']
        else:
            try_result = {'status': 'success'}

        # 执行 catch (if try failed)
        if original_exc and 'do' in catch_config:
            logger.warning(f"  -> [Try-Catch] 'try' block failed. Entering 'catch' block for '{node_id}'.")
            catch_context = self.context.fork()
            catch_context.set('error', try_error_details)
            sub_engine = ExecutionEngine(catch_context, self.orchestrator, self.pause_event,
                                         f"{self.engine_id}.{node_id}.catch")
            result = await sub_engine.run({'steps': catch_config['do']}, "catch_block")
            if result['status'] != 'success':
                logger.error(f"  -> [Try-Catch] 'catch' block itself failed. The entire 'try' node will fail.",
                             exc_info=True)  # 【新增】exc_info=True
                final_node_status = StepState.FAILED
                catch_exc = result.get('error_details', {}).get('error') or Exception(
                    result.get('error_details', {}).get('message', 'Catch failed'))
                raise StopTaskException(f"Catch block failed: {result.get('error_details', 'Unknown')}",
                                        cause=catch_exc,
                                        severity='critical') from original_exc  # 【修改】from cause + severity
            if catch_config.get('continue_on_success', False):
                logger.info(
                    "  -> [Try-Catch] 'catch' block succeeded and 'continue_on_success' is true. The error is considered handled.")
                final_node_status = StepState.SUCCESS
                try_result = result['results']
            else:
                final_node_status = StepState.FAILED
        elif original_exc:
            final_node_status = StepState.FAILED

        # 执行 finally (always)
        if 'do' in finally_config:
            logger.info(f"  -> [Try-Catch] Entering 'finally' block for '{node_id}'.")
            finally_context = self.context.fork()
            finally_context.set('status', 'SUCCESS' if not original_exc else 'FAILED')
            if original_exc:
                finally_context.set('error', try_error_details)
            sub_engine = ExecutionEngine(finally_context, self.orchestrator, self.pause_event,
                                         f"{self.engine_id}.{node_id}.finally")
            try:
                result = await sub_engine.run({'steps': finally_config['do']}, "finally_block")
                if result['status'] != 'success':
                    finally_exc = result.get('error_details', {}).get('error') or Exception(
                        result.get('error_details', {}).get('message', 'Finally failed'))
                    logger.error(f"  -> [Try-Catch] 'finally' block failed: {finally_exc}", exc_info=True)  # 【新增】完整栈日志
                    # 【新增】根据 on_failure 决定行为
                    if on_failure == 'raise':
                        raise StopTaskException(f"Finally critical failure in {node_id}", cause=finally_exc,
                                                severity='critical') from finally_exc
                    elif on_failure == 'ignore':
                        logger.warning(f"Ignoring finally failure per config in {node_id}: {finally_exc}")
                        # 继续，但标记
                        final_node_status = StepState.SUCCESS  # 或保持原 status
                    elif on_failure == 'log':
                        logger.error(f"Logging finally failure in {node_id}: {finally_exc}", exc_info=True)
                        # 继续
                    else:
                        logger.warning(f"Invalid finally_on_failure '{on_failure}' in {node_id}, default to 'log'")
                        logger.error(f"Finally failure: {finally_exc}", exc_info=True)
                    # 【新增】如果 debug_mode，记录到 finally_context 或返回
                    if self.debug_mode:
                        result['traceback'] = finally_exc.get_full_traceback() if hasattr(finally_exc,
                                                                                          'get_full_traceback') else traceback.format_exc()
                else:
                    final_node_status = StepState.SUCCESS if final_node_status == StepState.SUCCESS else final_node_status
            except StopTaskException as e:
                # 【修改】传播，但记录
                logger.error(f"StopTask in finally {node_id}: {e}", exc_info=True)
                raise e from original_exc  # 保留链
            except Exception as e:
                # 【新增】通用 finally 异常处理
                logger.error(f"Unexpected finally error in {node_id}: {e}", exc_info=True)
                if on_failure == 'raise':
                    raise StopTaskException(f"Finally failed critically: {e}", cause=e, severity='critical') from e
                else:
                    logger.warning(f"{on_failure} finally error in {node_id}: {e}")
                    final_node_status = StepState.FAILED

        if final_node_status == StepState.FAILED:
            raise StopTaskException(f"'try' node '{node_id}' failed. Original error: {try_error_details}",
                                    cause=original_exc,
                                    severity='critical') from original_exc  # 【修改】from cause + severity

        # 【新增】如果 debug_mode，返回 traceback
        if self.debug_mode and original_exc:
            return {'status': 'success', 'traceback': original_exc.get_full_traceback() if hasattr(original_exc,
                                                                                                   'get_full_traceback') else traceback.format_exc()}

        return try_result
    async def _run_failure_handler_script(self, failure_data: Dict, error_details: Dict):
        handler_context = self.context.fork()
        handler_context.set('error', error_details)
        sub_steps = failure_data.get('do', [])
        if not sub_steps: return
        handler_injector = ActionInjector(handler_context, engine=self)
        for i, step_data in enumerate(sub_steps):
            step_name = step_data.get('name', f"on_failure sub-step {i + 1}")
            logger.info(f"    -> [on_failure]: {step_name}")
            await self._execute_single_action_step(step_data, injector=handler_injector)

    async def _execute_for_each_node(self, node_id: str, node_data: Dict) -> List[Any]:
        config = node_data['for_each']
        items_to_iterate = await self.injector._render_value(config['in'], self.context._data)
        item_var_name = config.get('as', 'item')
        sub_graph_template = config['do']
        if not isinstance(items_to_iterate, Iterable): raise TypeError(
            f"'for_each' node '{node_id}' 'in' clause did not resolve to an iterable, got {type(items_to_iterate)}.")
        sub_engines: List[Tuple[ExecutionEngine, Dict]] = []
        for i, item in enumerate(items_to_iterate):
            sub_context = self.context.fork()
            sub_context.set(item_var_name, item)
            sub_context.set('index', i)
            sub_engine_id = f"{self.engine_id}.{node_id}[{i}]"
            sub_engine = ExecutionEngine(sub_context, self.orchestrator, self.pause_event, parent_node_id=sub_engine_id)
            sub_engines.append((sub_engine, sub_graph_template))
        results = await asyncio.gather(
            *[engine.run(task_data, f"for_each_sub_graph_{i}") for i, (engine, task_data) in enumerate(sub_engines)])
        final_results = []
        for i, result in enumerate(results):
            if result['status'] != 'success': raise StopTaskException(
                f"'for_each' node '{node_id}' failed on iteration {i}. Reason: {result.get('error_details', 'Unknown')}")
            final_results.append(result['results'])
        return final_results

    async def _execute_while_node(self, node_id: str, node_data: Dict) -> Dict:
        config = node_data['while']
        condition_template = config['condition']
        limit = int(config.get('limit', 10))
        sub_graph_template = config['do']
        iteration = 0
        last_result = None
        loop_context = self.context.fork()
        while iteration < limit:
            condition = await self.injector._render_value(condition_template, loop_context._data)
            if not condition: logger.info(f"  -> 'while' node '{node_id}' condition is false. Exiting loop."); break
            logger.info(f"  -> 'while' node '{node_id}' starting iteration {iteration + 1}/{limit}.")
            sub_engine_id = f"{self.engine_id}.{node_id}({iteration})"
            sub_engine = ExecutionEngine(loop_context, self.orchestrator, self.pause_event,
                                         parent_node_id=sub_engine_id)
            result = await sub_engine.run(sub_graph_template, f"while_sub_graph_{iteration}")
            if result['status'] != 'success': raise StopTaskException(
                f"'while' node '{node_id}' failed in iteration {iteration + 1}. Reason: {result.get('error_details', 'Unknown')}")
            loop_context.set('steps', result['results'])
            last_result = result['results']
            iteration += 1
        if iteration >= limit: logger.warning(f"'while' node '{node_id}' reached its iteration limit of {limit}.")
        return {'iterations': iteration, 'last_result': last_result}

    async def _execute_switch_node(self, node_id: str, node_data: Dict) -> str:
        switch_config = node_data['switch']
        target_node = switch_config.get('default')
        path_found = False
        for case in switch_config.get('cases', []):
            condition = await self.injector._render_value(case['when'], self.context._data)
            if condition: target_node = case.get('then'); path_found = True; break
        if not path_found and target_node is None: logger.warning(
            f"'switch' node '{node_id}' resolved with no target. No path taken."); return "No path taken"
        logger.info(f"  -> 'switch' node '{node_id}' resolved to path '{target_node}'.")
        all_potential_targets = set(c.get('then') for c in switch_config.get('cases', []) if 'then' in c)
        if 'default' in switch_config: all_potential_targets.add(switch_config['default'])
        for potential_target in all_potential_targets:
            if potential_target != target_node:
                if self.step_states.get(potential_target) == StepState.PENDING:
                    self.step_states[potential_target] = StepState.SKIPPED
                    self.step_results[potential_target] = {'status': 'skipped',
                                                           'reason': f"Not chosen by switch node '{node_id}'"}
        return f"Path taken: {target_node}"

    def _convert_linear_list_to_dag(self, linear_steps: List[Dict]) -> Dict[str, Any]:
        return {"__legacy_linear_task": {"name": "Legacy Linear Task", "do": linear_steps}}

    async def _execute_linear_script_node(self, sub_steps: List[Dict]) -> Any:
        sub_context = self.context.fork()
        sub_injector = ActionInjector(sub_context, engine=self)
        last_result = None
        for i, step_data in enumerate(sub_steps):
            step_name = step_data.get('name', f"sub-step {i + 1}")
            logger.info(f"  -> [Linear Sub-Step]: {step_name}")
            try:
                if 'when' in step_data:
                    condition = await sub_injector._render_value(step_data['when'], sub_context._data)
                    if not condition: logger.info(
                        f"    -> Skipping sub-step '{step_name}' because 'when' condition was false."); continue
                step_result = await self._execute_single_action_step(step_data, injector=sub_injector)
                if 'output_to' in step_data: sub_context.set(step_data['output_to'], step_result)
                last_result = step_result
            except Exception as e:
                logger.error(f"    -> Sub-step '{step_name}' failed. Aborting linear script node.")
                self.context.merge(sub_context)
                raise e
        self.context.merge(sub_context)
        return last_result

    async def _execute_single_action_step(self, step_data: Dict[str, Any],
                                          injector: Optional[ActionInjector] = None) -> Any:
        """【增强】执行单动作步骤，支持 JumpSignal/StopTaskException from cause 和 traceback。"""
        active_injector = injector or self.injector
        if 'next' in step_data: self.next_task_target = await active_injector._render_value(step_data['next'],
                                                                                            active_injector.context._data)
        wait_before = step_data.get('wait_before')
        if wait_before: await asyncio.sleep(
            float(await active_injector._render_value(wait_before, active_injector.context._data)))
        retry_config = step_data.get('retry', {})
        max_attempts = int(retry_config.get('count', 1))
        retry_interval = float(retry_config.get('interval', 1.0))
        last_exception = None
        step_result = {'status': 'success', 'output': {}}  # 【新增】step_result for traceback
        original_exc = None  # 【新增】跟踪 cause

        for attempt in range(max_attempts):
            await self._check_pause()
            if attempt > 0: logger.info(
                f"    -> Retrying... (Attempt {attempt + 1}/{max_attempts})"); await asyncio.sleep(retry_interval)
            try:
                action_name = step_data.get('action')
                if not action_name: return True
                if action_name.lower() == 'run_task':
                    result = await self._run_sub_task(step_data, injector=active_injector)
                else:
                    result = await active_injector.execute(action_name, step_data.get('params', {}))
                is_logical_failure = (result is False or (hasattr(result, 'found') and result.found is False))
                if not is_logical_failure:
                    step_result['output'] = result
                    return result
                else:
                    last_exception = StopTaskException(f"Action '{action_name}' returned a failure status.",
                                                       success=False, severity='warning')  # 【修改】添加 severity
                    original_exc = last_exception  # 【新增】
            except JumpSignal as e:
                # 【修改】直接 raise from cause（如果 e 有 cause）
                logger.info(f"Jump signal in step: {e}", exc_info=True)  # 【新增】exc_info=True
                if self.debug_mode:
                    step_result['traceback'] = e.get_full_traceback() if hasattr(e,
                                                                                 'get_full_traceback') else traceback.format_exc()
                raise e from original_exc if original_exc else e  # 【新增】from cause
            except StopTaskException as e:
                # 【修改】传播但记录
                logger.error(f"StopTask in step: {e} (severity: {e.severity})", exc_info=True)
                if self.debug_mode:
                    step_result['traceback'] = e.get_full_traceback()
                raise e from original_exc if original_exc else e
            except Exception as e:
                original_exc = e  # 【新增】捕获 cause
                logger.error(f"Action '{action_name}' failed on attempt {attempt + 1}: {e}",
                             exc_info=True)  # 【确认】已有，但确保
                last_exception = e

        step_name = step_data.get('name', step_data.get('action', 'unnamed_step'))
        logger.error(f"  -> Step '{step_name}' failed after {max_attempts} attempts.")
        await self._capture_debug_screenshot(step_name)
        # 【修改】raise with cause 和 severity
        raise StopTaskException(f"Step '{step_name}' failed after retries.", cause=last_exception or original_exc,
                                severity='critical') from last_exception or original_exc

        # 【新增】如果 debug_mode，step_result['traceback'] 已设置，可在调用方用
    async def _check_pause(self):
        if self.pause_event.is_set():
            logger.warning("接收到全局暂停信号，任务执行已暂停。等待恢复信号...")
            await self.pause_event.wait()
            logger.info("接收到恢复信号，任务将继续执行。")

    async def _run_sub_task(self, step_data: Dict[str, Any], injector: ActionInjector) -> Any:
        if not self.orchestrator: logger.error("无法执行子任务：Engine 未关联到 Orchestrator。"); return False
        rendered_params = await injector._render_params(step_data.get('params', {}))
        sub_task_id = rendered_params.get('task_name')
        if not sub_task_id: logger.error("run_task 失败：'task_name' 参数缺失。"); return False
        sub_task_data = self.orchestrator.load_task_data(sub_task_id)
        if not sub_task_data: logger.error(f"run_task 失败：找不到子任务定义 '{sub_task_id}'。"); return False
        sub_context = injector.context.fork()
        params_to_pass = rendered_params.get('with', rendered_params.get('pass_params', {}))
        sub_context.set('params', params_to_pass)
        for key, value in params_to_pass.items(): sub_context.set(key, value)
        logger.info(f"  -> 调用子任务 '{sub_task_id}' 并传递参数: {list(params_to_pass.keys())}")
        sub_engine_id = f"{self.engine_id}.{sub_task_id}"
        sub_engine = ExecutionEngine(sub_context, self.orchestrator, self.pause_event, parent_node_id=sub_engine_id)
        sub_task_result = await self.orchestrator.execute_task(
            task_name_in_plan=sub_task_id.split('/', 1)[1] if '/' in sub_task_id else sub_task_id,
            initial_data=params_to_pass)
        if isinstance(sub_task_result, dict):
            if sub_task_result.get('status') == 'go_task': raise JumpSignal('go_task', sub_task_result['next_task'])
            if sub_task_result.get('status') == 'error': logger.error(
                f"  -> 子任务 '{sub_task_id}' 执行失败。"); return False
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
            if capture_result and capture_result.success: capture_result.save(filepath); logger.error(
                f"步骤失败，已自动截图至: {filepath}")
        except Exception as e:
            logger.error(f"在执行失败截图时发生意外错误: {e}", exc_info=True)

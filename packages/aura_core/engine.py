# -*- coding: utf-8 -*-
"""Aura 框架的核心执行引擎。

该模块定义了 `ExecutionEngine` 类，它负责管理单个任务（Task）的完整执行
生命周期。引擎将任务的步骤（Steps）解析为一个有向无环图（DAG），并根据
依赖关系、条件逻辑和循环配置来调度和执行图中的每个节点（Node）。

主要职责:
- **图构建**: 将任务定义中的 `steps` 解析成依赖关系图。
- **DAG 调度**: 实现一个异步调度器，根据依赖满足情况来执行准备就绪的节点。
- **上下文管理**: 为每个节点创建和管理其独立的执行上下文（`ExecutionContext`），
  支持并行分支的上下文分叉（fork）和合并（merge）。
- **节点执行**: 调用 `ActionInjector` 来执行每个节点中定义的 `action`。
- **循环处理**: 支持 `for_each`, `times`, `while` 等多种循环模式。
- **状态管理**: 跟踪每个节点（`StepState`）和整个任务的执行状态。
- **事件与回调**: 在节点的生命周期事件（如开始、成功、失败）上触发回调。
- **异常处理**: 捕获和处理执行过程中的各种异常，包括控制流异常。
"""
import asyncio
import time
import traceback
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Callable, Coroutine

from packages.aura_core.logger import logger
from .action_injector import ActionInjector
from .api import service_registry
from .context import ExecutionContext
from .exceptions import StopTaskException, JumpSignal
from .state_store_service import StateStoreService
from .template_renderer import TemplateRenderer

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .orchestrator import Orchestrator


class StepState(Enum):
    """表示任务中一个步骤（节点）的执行状态。"""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ExecutionEngine:
    """负责单个任务的图构建、调度和执行的核心引擎。

    每个任务在运行时都会创建一个独立的 `ExecutionEngine` 实例。
    """

    def __init__(self, orchestrator: 'Orchestrator', pause_event: asyncio.Event,
                 event_callback: Optional[Callable] = None):
        """初始化执行引擎。

        Args:
            orchestrator: 父级 Orchestrator 实例，用于访问共享资源。
            pause_event: 一个全局的 `asyncio.Event`，用于暂停/恢复任务执行。
            event_callback: 一个可选的回调函数，用于在引擎执行过程中发送事件。
        """
        self.orchestrator = orchestrator
        self.pause_event = pause_event
        self.engine_id = str(uuid.uuid4())[:8]
        self.event_callback = event_callback
        self.debug_mode = getattr(orchestrator, 'debug_mode', True)
        self.services = getattr(orchestrator, 'services', {})

        # 核心状态
        self.nodes: Dict[str, Dict] = {}
        self.dependencies: Dict[str, Any] = {}
        self.reverse_dependencies: Dict[str, Set[str]] = {}
        self.step_states: Dict[str, StepState] = {}

        # 上下文管理
        self.root_context: Optional[ExecutionContext] = None
        self.node_contexts: Dict[str, ExecutionContext] = {}

        # 异步任务管理
        self.running_tasks: Set[asyncio.Task] = set()
        self.completion_event: Optional[asyncio.Event] = None

        # 依赖的服务
        self.state_store: StateStoreService = self.services.get('state_store')
        self.VALID_DEPENDENCY_STATUSES = {'success', 'failed', 'running', 'skipped'}

    async def run(self, task_data: Dict[str, Any], task_name: str, root_context: ExecutionContext) -> ExecutionContext:
        """执行一个任务的主入口点。

        此方法会构建依赖图，启动 DAG 调度器，并等待所有节点执行完毕。

        Args:
            task_data: 任务的完整定义字典。
            task_name: 任务的名称。
            root_context: 本次任务运行的根执行上下文。

        Returns:
            执行完毕后，包含了所有节点结果的最终根执行上下文。
        """
        task_display_name = task_data.get('meta', {}).get('title', task_name)
        logger.info(f"======= 开始执行任务: {task_display_name} =======")

        self.root_context = root_context
        steps = task_data.get('steps', {})
        if not isinstance(steps, dict) or not steps:
            logger.info('任务中没有可执行的步骤。')
            return self.root_context

        try:
            self._build_graph(steps)
            await self._run_dag_scheduler()
        except (JumpSignal, StopTaskException):
            pass
        except Exception as e:
            logger.error(f"!! 任务 '{task_name}' 在图构建或调度时发生严重错误: {e}", exc_info=True)
            for node_id, state in self.step_states.items():
                if state == StepState.PENDING:
                    self.step_states[node_id] = StepState.FAILED
                    error_info = {"type": type(e).__name__, "message": str(e)}
                    if self.debug_mode:
                        error_info["traceback"] = traceback.format_exc()
                    run_state = self._create_run_state(StepState.FAILED, time.time(), error=error_info)
                    self.root_context.add_node_result(node_id, {"run_state": run_state})

        final_status = 'success'
        for state in self.step_states.values():
            if state == StepState.FAILED:
                final_status = 'failed'
                break

        logger.info(f"======= 任务 '{task_display_name}' 执行结束 (最终状态: {final_status}) =======")
        return self.root_context

    def _build_graph(self, steps_dict: Dict[str, Any]):
        """(私有) 从任务步骤定义中构建依赖图。"""
        self.nodes = steps_dict
        all_node_ids = set(self.nodes.keys())
        for node_id, node_data in self.nodes.items():
            self.step_states[node_id] = StepState.PENDING
            self.reverse_dependencies.setdefault(node_id, set())

            deps_struct = node_data.get('depends_on', [])
            self.dependencies[node_id] = deps_struct

            all_deps = self._get_all_deps_from_struct(deps_struct)
            for dep_id in all_deps:
                if dep_id not in all_node_ids:
                    raise KeyError(f"节点 '{node_id}' 引用了未定义的依赖: '{dep_id}'")
                self.reverse_dependencies.setdefault(dep_id, set()).add(node_id)

            if node_id in all_deps:
                raise ValueError(f"检测到循环依赖: 节点 '{node_id}' 直接或间接依赖于自身。")

    def _get_all_deps_from_struct(self, struct: Any) -> Set[str]:
        """(私有) 递归地从复杂的依赖结构中提取所有节点 ID。"""
        deps = set()
        if isinstance(struct, str):
            if not struct.startswith("when:"):
                deps.add(struct)
        elif isinstance(struct, list):
            for item in struct:
                deps.update(self._get_all_deps_from_struct(item))
        elif isinstance(struct, dict):
            if 'and' in struct:
                deps.update(self._get_all_deps_from_struct(struct['and']))
            elif 'or' in struct:
                deps.update(self._get_all_deps_from_struct(struct['or']))
            elif 'not' in struct:
                deps.update(self._get_all_deps_from_struct(struct['not']))
            else:
                deps.update(struct.keys())
        return deps

    async def _run_dag_scheduler(self):
        """(私有) 启动并管理 DAG 调度器，直到所有可达节点执行完毕。"""
        self.completion_event = asyncio.Event()
        await self._schedule_ready_nodes()

        if not self.running_tasks and self.nodes:
            if all(state == StepState.PENDING for state in self.step_states.values()):
                raise ValueError("任务图中没有可作为起点的节点（所有节点都有依赖）。")

        if self.running_tasks:
            await self.completion_event.wait()

    async def _schedule_ready_nodes(self):
        """(私有) 检查并调度所有当前满足依赖条件的节点。"""
        ready_nodes = []
        for node_id in self.nodes:
            if self.step_states[node_id] == StepState.PENDING and await self._are_dependencies_met(node_id):
                ready_nodes.append(node_id)

        for node_id in ready_nodes:
            node_context = self._prepare_node_context(node_id)
            self.node_contexts[node_id] = node_context

            task = asyncio.create_task(self._execute_dag_node(node_id, node_context))
            self.running_tasks.add(task)
            task.add_done_callback(self._on_task_completed)

    def _prepare_node_context(self, node_id: str) -> ExecutionContext:
        """(私有) 为即将执行的节点准备其执行上下文（通过分支和合并父上下文）。"""
        parent_ids = self._get_all_deps_from_struct(self.dependencies.get(node_id, []))

        if not parent_ids:
            return self.root_context.fork()

        parent_contexts = [self.node_contexts[pid] for pid in parent_ids if pid in self.node_contexts]

        if not parent_contexts:
            return self.root_context.fork()

        new_context = parent_contexts[0].fork()
        if len(parent_contexts) > 1:
            new_context.merge(parent_contexts[1:])

        return new_context

    def _on_task_completed(self, task: asyncio.Task):
        """(私有) 一个节点执行任务完成后的回调。"""
        self.running_tasks.discard(task)
        try:
            task.result()
        except Exception as e:
            logger.critical(f"DAG调度器捕获到未处理的任务异常: {e}", exc_info=True)

        async def reschedule_and_maybe_finish():
            try:
                await self._schedule_ready_nodes()
            finally:
                if not self.running_tasks and self.completion_event:
                    self.completion_event.set()

        asyncio.create_task(reschedule_and_maybe_finish())

    async def _are_dependencies_met(self, node_id: str) -> bool:
        """(私有) 检查指定节点的所有依赖是否已满足。"""
        dep_struct = self.dependencies.get(node_id)
        return await self._evaluate_dep_struct(dep_struct)

    async def _evaluate_dep_struct(self, struct: Any) -> bool:
        """(私有) 递归地评估一个依赖结构是否为真。"""
        if struct is None:
            return True

        if isinstance(struct, str):
            if struct.startswith("when:"):
                expression = struct.replace("when:", "").strip()
                renderer = TemplateRenderer(self.root_context, self.state_store)
                return bool(await renderer.render(expression))
            else:
                state = self.step_states.get(struct)
                return state == StepState.SUCCESS

        if isinstance(struct, list):
            if not struct: return True
            results = await asyncio.gather(*[self._evaluate_dep_struct(item) for item in struct])
            return all(results)

        if isinstance(struct, dict):
            if not struct: return True

            if 'and' in struct:
                return await self._evaluate_dep_struct(struct['and'])
            if 'or' in struct:
                results = await asyncio.gather(*[self._evaluate_dep_struct(item) for item in struct['or']])
                return any(results)
            if 'not' in struct:
                return not await self._evaluate_dep_struct(struct['not'])

            if len(struct) != 1:
                raise ValueError(f"依赖条件格式错误: {struct}。状态查询必须是单个键值对。")

            node_id, expected_status_str = next(iter(struct.items()))

            raw_statuses = {s.strip().lower() for s in expected_status_str.split('|')}

            invalid_statuses = raw_statuses - self.VALID_DEPENDENCY_STATUSES
            if invalid_statuses:
                raise ValueError(f"发现未知的依赖状态: {invalid_statuses}. "
                                 f"支持的状态: {self.VALID_DEPENDENCY_STATUSES}")

            current_state_enum = self.step_states.get(node_id)
            if not current_state_enum:
                return False

            current_state_str = current_state_enum.name.lower()
            return current_state_str in raw_statuses

        return True

    def _create_run_state(self, status: StepState, start_time: float, error: Optional[Dict] = None) -> Dict:
        """(私有) 创建一个标准的节点运行状态字典。"""
        end_time = time.time()
        return {
            "status": status.name,
            "start_time": time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(start_time)),
            "end_time": time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(end_time)),
            "duration": round(end_time - start_time, 3),
            "error": error
        }

    async def _execute_dag_node(self, node_id: str, node_context: ExecutionContext):
        """(私有) 执行 DAG 中的单个节点。"""
        self.step_states[node_id] = StepState.RUNNING
        start_time = time.time()
        node_result = {}
        error_details = None
        action_result = None

        try:
            node_data = self.nodes[node_id]
            if self.event_callback:
                await self.event_callback('node.started', {'node_id': node_id})
            await self._check_pause()

            loop_config = node_data.get('loop')
            if loop_config:
                action_result = await self._execute_loop(node_id, node_data, node_context, loop_config)
            else:
                action_result = await self._execute_single_action(node_data, node_context)

            outputs_block = node_data.get('outputs', {})
            if outputs_block:
                renderer = TemplateRenderer(node_context, self.state_store)
                output_render_scope = {"result": action_result, **(await renderer.get_render_scope())}
                for name, template in outputs_block.items():
                    node_result[name] = await renderer._render_recursive(template, output_render_scope)
            else:
                node_result['output'] = action_result

            self.step_states[node_id] = StepState.SUCCESS
            if self.event_callback:
                await self.event_callback('node.succeeded', {'node_id': node_id, 'output': node_result})

        except (JumpSignal, StopTaskException) as e:
            logger.error(f"节点'{node_id}'被控制流异常中断: {e}", exc_info=self.debug_mode)
            self.step_states[node_id] = StepState.FAILED
            error_details = {"type": type(e).__name__, "message": str(e), "severity": e.severity}
            if self.debug_mode:
                error_details["traceback"] = e.get_full_traceback()
        except Exception as e:
            logger.error(f"节点'{node_id}'执行时发生意外错误: {e}", exc_info=True)
            self.step_states[node_id] = StepState.FAILED
            error_details = {"type": type(e).__name__, "message": str(e)}
            if self.debug_mode:
                error_details["traceback"] = traceback.format_exc()
            if self.event_callback:
                await self.event_callback('node.failed', {'node_id': node_id, 'error': str(e)})

        finally:
            run_state = self._create_run_state(self.step_states.get(node_id, StepState.FAILED), start_time,
                                               error=error_details)
            final_node_output = {"run_state": run_state, **node_result}
            node_context.add_node_result(node_id, final_node_output)
            self.root_context.add_node_result(node_id, final_node_output)
            if self.event_callback:
                status = 'error' if error_details else 'success'
                await self.event_callback('node.finished', {
                    'node_id': node_id,
                    'end_time': time.time(),
                    'status': status
                })

    async def _execute_single_action(self, node_data: Dict, node_context: ExecutionContext) -> Any:
        """(私有) 执行节点中定义的单个 action。"""
        renderer = TemplateRenderer(node_context, self.state_store)
        injector = ActionInjector(node_context, self, renderer, self.services)

        action_name = node_data.get('action')
        if not action_name:
            raise ValueError("节点定义中缺少'action'。")

        raw_params = node_data.get('params', {})
        return await injector.execute(action_name, raw_params)

    async def _execute_loop(self, node_id: str, node_data: Dict, node_context: ExecutionContext, loop_config: Dict) -> \
            List[Any]:
        """(私有) 执行节点中定义的循环逻辑。"""
        renderer = TemplateRenderer(node_context, self.state_store)
        rendered_config = await renderer.render(loop_config)

        tasks: List[Coroutine] = []

        if 'for_each' in rendered_config:
            items = rendered_config['for_each']
            if not isinstance(items, (list, dict)):
                raise TypeError(f"loop.for_each 的结果必须是列表或字典，但得到的是 {type(items)}")

            item_source = items.items() if isinstance(items, dict) else enumerate(items)
            for index, item in item_source:
                iter_context = node_context.fork()
                iter_context.set_loop_variables({'item': item, 'index': index})
                tasks.append(self._execute_single_action(node_data, iter_context))

        elif 'times' in rendered_config:
            try:
                count = int(rendered_config['times'])
            except (ValueError, TypeError):
                raise TypeError(f"loop.times 的结果必须是整数，但得到的是 {rendered_config['times']}")

            for i in range(count):
                iter_context = node_context.fork()
                iter_context.set_loop_variables({'index': i})
                tasks.append(self._execute_single_action(node_data, iter_context))

        elif 'while' in loop_config:
            results = []
            index = 0
            max_iterations = rendered_config.get('max_iterations', 1000)
            while index < max_iterations:
                iter_context = node_context.fork()
                iter_context.set_loop_variables({'index': index})

                while_renderer = TemplateRenderer(iter_context, self.state_store)
                condition = bool(await while_renderer.render(loop_config['while']))

                if not condition:
                    break

                result = await self._execute_single_action(node_data, iter_context)
                results.append(result)
                index += 1
            return results

        else:
            raise ValueError(f"节点 '{node_id}' 的 loop 配置无效: {loop_config}")

        parallelism = rendered_config.get('parallelism', len(tasks))
        semaphore = asyncio.Semaphore(parallelism)

        async def run_with_semaphore(task: Coroutine) -> Any:
            async with semaphore:
                return await task

        results = await asyncio.gather(*[run_with_semaphore(task) for task in tasks])
        return results

    async def _check_pause(self):
        """(私有) 检查是否需要暂停任务执行。"""
        if self.pause_event.is_set():
            logger.warning("接收到全局暂停信号，任务执行已暂停。等待恢复信号...")
            await self.pause_event.wait()
            logger.info("接收到恢复信号，任务将继续执行。")

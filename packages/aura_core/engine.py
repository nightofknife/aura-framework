# packages/aura_core/engine.py
"""
定义了 `ExecutionEngine`，这是 Aura 框架中负责执行单个任务（Task）的核心组件。

`ExecutionEngine` 的主要职责是作为一个基于依赖关系的调度器（DAG-based scheduler）。
它接收一个结构化的任务定义（包含多个步骤/节点），然后：
1.  **构建依赖图**: 解析 `depends_on` 字段，构建一个有向无环图（DAG）。
2.  **调度执行**: 异步地、并发地执行图中所有没有未满足依赖的节点。
3.  **上下文管理**: 为每个执行的节点创建和管理其 `ExecutionContext`，支持并行分支的上下文分叉（fork）和合并（merge）。
4.  **依赖评估**: 动态地评估复杂的依赖条件，包括逻辑组合（and/or/not）和对其他节点状态的查询。
5.  **循环处理**: 内置对 `loop` 结构（`for_each`, `times`, `while`）的支持，能够并发执行循环体。
6.  **行为调用**: 将每个节点的实际执行委托给 `ActionInjector`，后者负责参数渲染和依赖注入。
7.  **状态跟踪**: 记录每个节点的执行状态（成功、失败、跳过等）和结果。
"""

import asyncio
import time
import traceback
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Callable, Coroutine

from packages.aura_core.logger import logger
from .action_injector import ActionInjector
from .context import ExecutionContext
from .exceptions import StopTaskException, JumpSignal
from .state_store_service import StateStoreService
from .template_renderer import TemplateRenderer

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .orchestrator import Orchestrator

class StepState(Enum):
    """
    表示任务中单个步骤（节点）的执行状态。
    """
    PENDING = "PENDING"  #: 待定：等待其依赖项完成。
    RUNNING = "RUNNING"  #: 运行中：正在执行。
    SUCCESS = "SUCCESS"  #: 成功：已成功完成。
    FAILED = "FAILED"    #: 失败：执行过程中发生错误。
    SKIPPED = "SKIPPED"  #: 跳过：由于依赖项失败或条件不满足，该步骤被跳过。


class ExecutionEngine:
    """
    任务执行引擎，负责管理单个任务内所有步骤的DAG调度和执行。

    对于每个要执行的任务，`Orchestrator` 都会创建一个 `ExecutionEngine` 的实例。
    这个引擎是无状态的，其所有状态都与单次任务执行相关。
    """
    def __init__(self, orchestrator: 'Orchestrator', pause_event: asyncio.Event,
                 event_callback: Optional[Callable[[str, Dict], Coroutine]] = None):
        """
        初始化执行引擎。

        Args:
            orchestrator (Orchestrator): 创建此引擎的父级编排器实例。
            pause_event (asyncio.Event): 一个全局事件，用于控制任务的暂停和恢复。
            event_callback (Optional[Callable]): 一个可选的回调函数，用于在节点状态改变时发送事件。
        """
        self.orchestrator = orchestrator
        self.pause_event = pause_event
        self.engine_id = str(uuid.uuid4())[:8]
        self.event_callback = event_callback
        self.debug_mode = getattr(orchestrator, 'debug_mode', True)

        self.services = getattr(orchestrator, 'services', {})
        """从父级 `Orchestrator` 继承的、已实例化的服务字典。"""

        # 核心状态
        self.nodes: Dict[str, Dict] = {}  #: 任务中所有节点的定义。
        self.dependencies: Dict[str, Any] = {}  #: 节点ID到其依赖结构的映射。
        self.reverse_dependencies: Dict[str, Set[str]] = {}  #: 节点ID到依赖于它的其他节点ID集合的映射。
        self.step_states: Dict[str, StepState] = {}  #: 跟踪每个节点当前状态的字典。

        # 上下文管理
        self.root_context: Optional[ExecutionContext] = None  #: 整个任务的根执行上下文。
        self.node_contexts: Dict[str, ExecutionContext] = {}  #: 每个节点完成执行后的上下文快照。

        # 异步任务管理
        self.running_tasks: Set[asyncio.Task] = set()  #: 当前正在运行的 `asyncio.Task` 集合。
        self.completion_event: Optional[asyncio.Event] = None  #: 当所有节点执行完毕时设置的事件。

        # 依赖的服务
        self.state_store: StateStoreService = self.services.get('state_store')

        self.VALID_DEPENDENCY_STATUSES = {'success', 'failed', 'running', 'skipped'}
        """依赖查询中所有合法的状态关键字。"""

    async def run(self, task_data: Dict[str, Any], task_name: str, root_context: ExecutionContext) -> ExecutionContext:
        """
        执行引擎的主入口点，运行一个完整的任务。

        Args:
            task_data (Dict[str, Any]): 从YAML文件加载的原始任务定义数据。
            task_name (str): 正在执行的任务的名称。
            root_context (ExecutionContext): 由 `Orchestrator` 创建并传入的初始执行上下文。

        Returns:
            ExecutionContext: 任务执行完成后，包含所有节点结果的最终执行上下文。
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
            # 这些异常由 _execute_dag_node 内部处理并标记节点状态，调度器会正常停止
            pass
        except Exception as e:
            logger.error(f"!! 任务 '{task_name}' 在图构建或调度时发生严重错误: {e}", exc_info=True)
            # 标记所有 PENDING 节点为 FAILED
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
        """
        根据任务定义中的 `steps` 构建依赖关系图。

        此方法会填充 `dependencies` 和 `reverse_dependencies` 字典，并进行循环依赖检测。

        Args:
            steps_dict (Dict[str, Any]): 任务定义中的 `steps` 字典。

        Raises:
            KeyError: 如果一个节点引用了不存在的依赖。
            ValueError: 如果检测到循环依赖。
        """
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
        """递归地从复杂的依赖结构中提取所有节点ID。"""
        deps = set()
        if isinstance(struct, str):
            # 简单依赖形式: "my_node"
            # 条件依赖形式: "when: {{...}}" - 这种不包含节点ID，忽略
            if not struct.startswith("when:"):
                deps.add(struct)
        elif isinstance(struct, list):
            for item in struct:
                deps.update(self._get_all_deps_from_struct(item))
        elif isinstance(struct, dict):
            # 逻辑组合器: and, or, not
            if 'and' in struct:
                deps.update(self._get_all_deps_from_struct(struct['and']))
            elif 'or' in struct:
                deps.update(self._get_all_deps_from_struct(struct['or']))
            elif 'not' in struct:
                deps.update(self._get_all_deps_from_struct(struct['not']))
            # 状态查询: {node_id: status}
            else:
                # 假设字典是状态查询，key就是node_id
                deps.update(struct.keys())
        return deps

    async def _run_dag_scheduler(self):
        """
        运行DAG调度器，直到所有节点都执行完毕。

        它首先调度所有就绪的节点，然后等待 `completion_event`。
        """
        self.completion_event = asyncio.Event()
        await self._schedule_ready_nodes()

        if not self.running_tasks and self.nodes:
            if all(state == StepState.PENDING for state in self.step_states.values()):
                raise ValueError("任务图中没有可作为起点的节点（所有节点都有依赖）。")

        if self.running_tasks:
            await self.completion_event.wait()

    async def _schedule_ready_nodes(self):
        """
        扫描所有 PENDING 状态的节点，检查其依赖是否满足，
        如果满足，则创建 `asyncio.Task` 来执行它们。
        """
        ready_nodes = []
        for node_id in self.nodes:
            if self.step_states[node_id] == StepState.PENDING and await self._are_dependencies_met(node_id):
                ready_nodes.append(node_id)

        for node_id in ready_nodes:
            # 准备该节点的上下文
            node_context = self._prepare_node_context(node_id)
            self.node_contexts[node_id] = node_context

            # 创建执行任务
            task = asyncio.create_task(self._execute_dag_node(node_id, node_context))
            self.running_tasks.add(task)
            task.add_done_callback(self._on_task_completed)

    def _prepare_node_context(self, node_id: str) -> ExecutionContext:
        """为即将执行的节点准备其执行上下文（通过分支和合并父上下文）。"""
        parent_ids = self._get_all_deps_from_struct(self.dependencies.get(node_id, []))

        if not parent_ids:
            # 根节点，从任务的root_context派生
            return self.root_context.fork()

        parent_contexts = [self.node_contexts[pid] for pid in parent_ids if pid in self.node_contexts]

        if not parent_contexts:
            # 这种情况理论上不应发生，因为_are_dependencies_met已经通过
            # 但作为保险，从root派生
            return self.root_context.fork()

        # 以第一个父上下文为基础进行fork，然后合并其他父上下文
        new_context = parent_contexts[0].fork()
        if len(parent_contexts) > 1:
            new_context.merge(parent_contexts[1:])

        return new_context

    def _on_task_completed(self, task: asyncio.Task):
        """
        当一个节点执行任务完成时的回调函数。

        它会检查任务是否异常，然后触发新一轮的调度。
        如果所有任务都已完成，则设置 `completion_event`。
        """
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
        """检查一个节点的所有依赖条件是否都已满足。"""
        dep_struct = self.dependencies.get(node_id)
        return await self._evaluate_dep_struct(dep_struct)

    async def _evaluate_dep_struct(self, struct: Any) -> bool:
        """
        递归评估依赖结构。

        支持逻辑组合 (and/or/not)、明确的状态查询以及'|'分隔的多状态。
        """
        # 0. 空依赖
        if struct is None:
            return True

        # 1. 简单依赖 (语法糖 for success) 和 条件依赖
        if isinstance(struct, str):
            if struct.startswith("when:"):
                expression = struct.replace("when:", "").strip()
                # 注意：这里使用root_context，因为它包含了所有已完成节点的数据
                renderer = TemplateRenderer(self.root_context, self.state_store)
                return bool(await renderer.render(expression))
            else:
                state = self.step_states.get(struct)
                return state == StepState.SUCCESS

        # 2. 列表隐含 AND 逻辑
        if isinstance(struct, list):
            if not struct: return True
            results = await asyncio.gather(*[self._evaluate_dep_struct(item) for item in struct])
            return all(results)

        if isinstance(struct, dict):
            if not struct: return True

            # 3. 逻辑组合器 (and, or, not)
            if 'and' in struct:
                return await self._evaluate_dep_struct(struct['and'])
            if 'or' in struct:
                results = await asyncio.gather(*[self._evaluate_dep_struct(item) for item in struct['or']])
                return any(results)
            if 'not' in struct:
                return not await self._evaluate_dep_struct(struct['not'])

            # 4. 状态查询依赖
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

        # 对于其他无法解析的类型，也视为空依赖
        return True

    def _create_run_state(self, status: StepState, start_time: float, error: Optional[Dict] = None) -> Dict:
        """创建一个标准的 `run_state` 字典。"""
        end_time = time.time()
        return {
            "status": status.name,
            "start_time": time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(start_time)),
            "end_time": time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(end_time)),
            "duration": round(end_time - start_time, 3),
            "error": error
        }

    async def _execute_dag_node(self, node_id: str, node_context: ExecutionContext):
        """
        执行DAG中的单个节点。

        这是节点执行的核心逻辑，包括状态更新、事件回调、暂停检查、
        循环处理、行为调用和异常处理。
        """
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

    async def _execute_single_action(self, node_data: Dict, node_context: ExecutionContext) -> Any:
        """执行节点中定义的单个 action。"""
        renderer = TemplateRenderer(node_context, self.state_store)
        injector = ActionInjector(node_context, self, renderer, self.services)

        action_name = node_data.get('action')
        if not action_name:
            raise ValueError("节点定义中缺少'action'。")

        raw_params = node_data.get('params', {})
        return await injector.execute(action_name, raw_params)

    async def _execute_loop(self, node_id: str, node_data: Dict, node_context: ExecutionContext, loop_config: Dict) -> List[Any]:
        """
        执行带有 `loop` 配置的节点。

        根据 `loop` 的类型（`for_each`, `times`, `while`）来创建并执行
        一系列并行的 action 调用。
        """
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

        elif 'while' in loop_config:  # 'while' 条件在每次迭代前渲染
            results = []
            index = 0
            max_iterations = rendered_config.get('max_iterations', 1000)  # 防止死循环
            while index < max_iterations:
                iter_context = node_context.fork()
                iter_context.set_loop_variables({'index': index})

                # 'while' 条件在每次迭代的上下文中渲染
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

        parallelism = rendered_config.get('parallelism', len(tasks))  # 默认为完全并行
        semaphore = asyncio.Semaphore(parallelism)

        async def run_with_semaphore(task: Coroutine) -> Any:
            async with semaphore:
                return await task

        results = await asyncio.gather(*[run_with_semaphore(task) for task in tasks])
        return results

    async def _check_pause(self):
        """检查并响应全局暂停事件。"""
        if self.pause_event.is_set():
            logger.warning("接收到全局暂停信号，任务执行已暂停。等待恢复信号...")
            await self.pause_event.wait()
            logger.info("接收到恢复信号，任务将继续执行。")


# packages/aura_core/engine.py

import asyncio
import time
import traceback
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Callable

from packages.aura_core.logger import logger
from .action_injector import ActionInjector
from .api import service_registry
from .context import ExecutionContext
from .exceptions import StopTaskException, JumpSignal
from .state_store_service import StateStoreService
from .template_renderer import TemplateRenderer


class StepState(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ExecutionEngine:
    def __init__(self, orchestrator=None, pause_event: asyncio.Event = None,
                 event_callback: Optional[Callable] = None):
        self.orchestrator = orchestrator
        self.pause_event = pause_event if pause_event else asyncio.Event()
        self.engine_id = str(uuid.uuid4())[:8]
        self.event_callback = event_callback
        self.debug_mode = getattr(orchestrator, 'debug_mode', True) if orchestrator else True

        # 核心状态
        self.nodes: Dict[str, Dict] = {}
        self.dependencies: Dict[str, Any] = {}
        self.reverse_dependencies: Dict[str, Set[str]] = {}
        self.step_states: Dict[str, StepState] = {}

        # 新的上下文管理
        self.root_context: Optional[ExecutionContext] = None
        self.node_contexts: Dict[str, ExecutionContext] = {}

        # 异步任务管理
        self.running_tasks: Set[asyncio.Task] = set()
        self.completion_event: Optional[asyncio.Event] = None

        # 依赖的服务
        self.state_store: StateStoreService = service_registry.get_service_instance('state_store')

    async def run(self, task_data: Dict[str, Any], task_name: str, root_context: ExecutionContext) -> ExecutionContext:
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
        deps = set()
        if isinstance(struct, str):
            # 简单依赖形式: "my_node"
            # 高级依赖形式: "when: {{...}}"
            if not struct.startswith("when:"):
                deps.add(struct)
        elif isinstance(struct, list):
            for item in struct:
                deps.update(self._get_all_deps_from_struct(item))
        elif isinstance(struct, dict):
            # 兼容旧的 and/or 结构
            for key, value in struct.items():
                deps.update(self._get_all_deps_from_struct(value))
        return deps

    async def _run_dag_scheduler(self):
        self.completion_event = asyncio.Event()
        await self._schedule_ready_nodes()

        if not self.running_tasks and self.nodes:
            if all(state == StepState.PENDING for state in self.step_states.values()):
                raise ValueError("任务图中没有可作为起点的节点（所有节点都有依赖）。")

        if self.running_tasks:
            await self.completion_event.wait()

    async def _schedule_ready_nodes(self):
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
        self.running_tasks.discard(task)
        # 捕获任务中的异常，以防有未处理的严重错误
        try:
            task.result()
        except Exception as e:
            logger.critical(f"DAG调度器捕获到未处理的任务异常: {e}", exc_info=True)

        asyncio.create_task(self._schedule_ready_nodes())

        if not self.running_tasks and self.completion_event:
            self.completion_event.set()

    async def _are_dependencies_met(self, node_id: str) -> bool:
        dep_struct = self.dependencies.get(node_id, [])
        return await self._evaluate_dep_struct(dep_struct)

    async def _evaluate_dep_struct(self, struct: Any) -> bool:
        if isinstance(struct, str):
            if struct.startswith("when:"):
                # 高级依赖
                expression = struct.replace("when:", "").strip()
                # 临时创建一个渲染器来评估条件
                # 注意：这里使用root_context，因为它包含了所有已完成节点的数据
                renderer = TemplateRenderer(self.root_context, self.state_store)
                return bool(await renderer.render(expression))
            else:
                # 简单依赖（语法糖）
                return self.step_states.get(struct) == StepState.SUCCESS

        if isinstance(struct, list):
            results = await asyncio.gather(*[self._evaluate_dep_struct(item) for item in struct])
            return all(results)

        if isinstance(struct, dict):
            # 兼容旧格式
            if 'and' in struct: return await self._evaluate_dep_struct(struct['and'])
            if 'or' in struct:
                results = await asyncio.gather(*[self._evaluate_dep_struct(item) for item in struct['or']])
                return any(results)

        return True  # 空依赖

    def _create_run_state(self, status: StepState, start_time: float, error: Optional[Dict] = None) -> Dict:
        end_time = time.time()
        return {
            "status": status.name,
            "start_time": time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(start_time)),
            "end_time": time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(end_time)),
            "duration": round(end_time - start_time, 3),
            "error": error
        }

    async def _execute_dag_node(self, node_id: str, node_context: ExecutionContext):
        self.step_states[node_id] = StepState.RUNNING
        start_time = time.time()
        node_result = {}
        error_details = None

        try:
            node_data = self.nodes[node_id]
            if self.event_callback:
                await self.event_callback('node.started', {'node_id': node_id})
            await self._check_pause()

            # 创建此节点专用的渲染器和注入器
            renderer = TemplateRenderer(node_context, self.state_store)
            injector = ActionInjector(node_context, self, renderer)

            # 真正执行action
            action_name = node_data.get('action')
            if not action_name:
                raise ValueError("节点定义中缺少'action'。")

            raw_params = node_data.get('params', {})
            action_result = await injector.execute(action_name, raw_params)

            # 处理具名输出
            outputs_block = node_data.get('outputs', {})
            if outputs_block:
                # 为了在outputs块中引用action结果，我们创建一个临时渲染作用域
                output_render_scope = {
                    "result": action_result,
                    **(await renderer._get_render_scope())
                }
                for name, template in outputs_block.items():
                    node_result[name] = await renderer._render_recursive(template, output_render_scope)
            else:
                # 如果没有outputs块，默认将action结果放入名为'output'的块
                node_result['output'] = action_result

            # 成功
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
            # 无论成功失败，都生成run_state并更新到上下文中
            run_state = self._create_run_state(self.step_states[node_id], start_time, error=error_details)
            final_node_output = {"run_state": run_state, **node_result}

            # 将结果写入该节点的上下文以及父级（root）上下文
            node_context.add_node_result(node_id, final_node_output)
            self.root_context.add_node_result(node_id, final_node_output)

    async def _check_pause(self):
        if self.pause_event.is_set():
            logger.warning("接收到全局暂停信号，任务执行已暂停。等待恢复信号...")
            await self.pause_event.wait()
            logger.info("接收到恢复信号，任务将继续执行。")


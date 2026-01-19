# -*- coding: utf-8 -*-
"""DAG调度模块

负责根据依赖关系调度和执行DAG节点，包括：
- 运行DAG调度器
- 调度就绪节点
- 管理就绪队列
- 评估依赖条件

迁移自 engine.py:262-395
"""
import asyncio
from typing import Any, TYPE_CHECKING

from packages.aura_core.observability.logging.core_logger import logger
from packages.aura_core.config.template import TemplateRenderer

if TYPE_CHECKING:
    from .execution_engine import ExecutionEngine, StepState


class DAGScheduler:
    """DAG调度器

    负责根据依赖关系调度节点执行。
    """

    def __init__(self, engine: 'ExecutionEngine'):
        """初始化DAG调度器

        Args:
            engine: 父级ExecutionEngine实例
        """
        self.engine = engine

    async def run_dag_scheduler(self):
        """运行DAG调度器主循环

        迁移自 engine.py:262-273

        初始化调度器，调度所有就绪节点，并等待所有任务完成。

        Raises:
            ValueError: 当没有节点可以调度时（可能存在依赖错误）
        """
        self.engine.completion_event = asyncio.Event()
        await self.schedule_ready_nodes()

        if not self.engine.running_tasks and self.engine.nodes:
            if all(state == self.engine.StepState.PENDING for state in self.engine.step_states.values()):
                raise ValueError("无法调度任何节点，请检查依赖配置是否正确")

        if self.engine.running_tasks:
            await self.engine.completion_event.wait()

    async def schedule_ready_nodes(self):
        """调度所有就绪的节点

        迁移自 engine.py:274-279

        遍历所有节点，将满足依赖条件的节点加入就绪队列。
        """
        for node_id in self.engine.nodes:
            await self.enqueue_ready_node(node_id)
        await self.drain_ready_queue()

    async def enqueue_ready_node(self, node_id: str):
        """将就绪节点加入队列

        迁移自 engine.py:280-288

        Args:
            node_id: 要检查的节点ID
        """
        if node_id in self.engine._ready_set:
            return
        if self.engine.step_states.get(node_id) != self.engine.StepState.PENDING:
            return
        if await self.are_dependencies_met(node_id):
            self.engine.ready_queue.append(node_id)
            self.engine._ready_set.add(node_id)

    async def drain_ready_queue(self):
        """排空就绪队列，启动所有就绪节点的执行

        迁移自 engine.py:289-302

        从就绪队列中取出节点，为其准备上下文并创建执行任务。
        """
        while self.engine.ready_queue:
            node_id = self.engine.ready_queue.popleft()
            self.engine._ready_set.discard(node_id)
            if self.engine.step_states.get(node_id) != self.engine.StepState.PENDING:
                continue

            node_context = self.engine._prepare_node_context(node_id)
            self.engine.node_contexts[node_id] = node_context

            task = asyncio.create_task(
                self.engine.node_executor.execute_dag_node(node_id, node_context)
            )
            self.engine.running_tasks.add(task)
            task.add_done_callback(
                lambda t, nid=node_id: self.engine._on_task_completed(t, nid)
            )

    async def are_dependencies_met(self, node_id: str) -> bool:
        """检查指定节点的所有依赖是否已满足

        迁移自 engine.py:340-344

        Args:
            node_id: 要检查的节点ID

        Returns:
            True表示依赖已满足，可以执行
        """
        dep_struct = self.engine.dependencies.get(node_id)
        return await self.evaluate_dep_struct(dep_struct)

    async def evaluate_dep_struct(self, struct: Any) -> bool:
        """递归地评估一个依赖结构是否为真

        迁移自 engine.py:345-395

        支持的依赖结构：
        - None: 无依赖，返回True
        - 字符串: "node_id" (检查SUCCESS) 或 "when:expression" (评估表达式)
        - 列表: [...] (所有元素都为真，AND逻辑)
        - 字典:
          - {"and": [...]} (所有为真)
          - {"or": [...]} (任一为真)
          - {"not": ...} (取反)
          - {node_id: "status"} (检查节点状态)

        Args:
            struct: 依赖结构

        Returns:
            评估结果（True表示满足）

        Raises:
            ValueError: 当依赖格式错误或状态值无效时
        """
        if struct is None:
            return True

        # 字符串格式
        if isinstance(struct, str):
            # when: 条件表达式
            if struct.startswith("when:"):
                expression = struct.replace("when:", "").strip()
                renderer = TemplateRenderer(self.engine.root_context, self.engine.state_store)
                return bool(await renderer.render(expression))
            # 普通节点依赖（默认要求SUCCESS）
            else:
                state = self.engine.step_states.get(struct)
                return state == self.engine.StepState.SUCCESS

        # 列表格式 (AND逻辑)
        if isinstance(struct, list):
            if not struct:
                return True
            results = await asyncio.gather(*[self.evaluate_dep_struct(item) for item in struct])
            return all(results)

        # 字典格式
        if isinstance(struct, dict):
            if not struct:
                return True

            # and 逻辑
            if 'and' in struct:
                return await self.evaluate_dep_struct(struct['and'])

            # or 逻辑
            if 'or' in struct:
                results = await asyncio.gather(
                    *[self.evaluate_dep_struct(item) for item in struct['or']]
                )
                return any(results)

            # not 逻辑
            if 'not' in struct:
                return not await self.evaluate_dep_struct(struct['not'])

            # 状态查询格式: {node_id: "status|status|..."}
            if len(struct) != 1:
                raise ValueError(
                    f"依赖条件格式错误: {struct}。状态查询必须是单个键值对。"
                )

            node_id, expected_status_str = next(iter(struct.items()))

            # 解析多个状态（用|分隔）
            raw_statuses = {s.strip().lower() for s in expected_status_str.split('|')}

            # 验证状态值有效性
            invalid_statuses = raw_statuses - self.engine.VALID_DEPENDENCY_STATUSES
            if invalid_statuses:
                raise ValueError(
                    f"发现未知的依赖状态: {invalid_statuses}. "
                    f"支持的状态: {self.engine.VALID_DEPENDENCY_STATUSES}"
                )

            # 获取节点当前状态
            current_state_enum = self.engine.step_states.get(node_id)
            if not current_state_enum:
                return False

            current_state_str = current_state_enum.name.lower()
            return current_state_str in raw_statuses

        return True

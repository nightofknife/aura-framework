# -*- coding: utf-8 -*-
"""控制流处理模块

负责处理goto/label机制和其他控制流逻辑，包括：
- 处理goto配置
- 执行goto跳转
- 管理跳转计数和安全限制

迁移自 engine.py:807-911
"""
import time
from typing import Any, Dict, Optional, TYPE_CHECKING

from packages.aura_core.observability.logging.core_logger import logger
from packages.aura_core.config.loader import get_config_value
from packages.aura_core.context.execution import ExecutionContext
from packages.aura_core.config.template import TemplateRenderer

if TYPE_CHECKING:
    from .execution_engine import ExecutionEngine, StepState


class ControlFlowHandler:
    """控制流处理器

    负责处理任务执行中的控制流操作（如goto）。
    """

    def __init__(self, engine: 'ExecutionEngine'):
        """初始化控制流处理器

        Args:
            engine: 父级ExecutionEngine实例
        """
        self.engine = engine

    async def handle_goto(
        self,
        node_id: str,
        node_data: Dict[str, Any],
        node_context: ExecutionContext,
        action_result: Any
    ):
        """处理节点的goto逻辑

        迁移自 engine.py:807-861

        支持以下goto格式：
        1. 简单跳转: goto: "label_name"
        2. 条件跳转: goto: {target: "label", when: "{{ condition }}", max_jumps: 10}
        3. 多路跳转: goto: [{when: "...", target: "..."}, ...]

        Args:
            node_id: 当前节点ID
            node_data: 节点配置数据
            node_context: 节点执行上下文
            action_result: 节点action的执行结果
        """
        goto_config = node_data.get('goto')
        if not goto_config:
            return

        renderer = TemplateRenderer(node_context, self.engine.state_store)
        scope = {"result": action_result, **(await renderer.get_render_scope())}

        # 情况1：简单跳转 goto: "label_name"
        if isinstance(goto_config, str):
            target_label = goto_config
            await self.execute_goto_jump(node_id, target_label, scope)
            return

        # 情况2：单个条件跳转 goto: {target, when, max_jumps}
        if isinstance(goto_config, dict) and 'target' in goto_config:
            goto_list = [goto_config]
        # 情况3：多路跳转 goto: [{...}, {...}]
        elif isinstance(goto_config, list):
            goto_list = goto_config
        else:
            logger.error(f"节点 '{node_id}' 的 goto 配置格式错误: {goto_config}")
            return

        # 处理条件跳转列表
        for goto_item in goto_list:
            if not isinstance(goto_item, dict):
                logger.error(f"节点 '{node_id}' 的 goto 条目格式错误: {goto_item}")
                continue

            target_label = goto_item.get('target')
            if not target_label:
                logger.error(f"节点 '{node_id}' 的 goto 缺少 target 字段")
                continue

            # 评估条件
            when_expr = goto_item.get('when')
            if when_expr:
                should_jump = bool(await renderer._render_recursive(when_expr, scope))
                if not should_jump:
                    continue  # 条件不满足，尝试下一个

            # 执行跳转
            max_jumps = goto_item.get('max_jumps')
            await self.execute_goto_jump(node_id, target_label, scope, max_jumps)
            return  # 成功跳转后退出

    async def execute_goto_jump(
        self,
        from_node: str,
        target_label: str,
        scope: Dict[str, Any],
        max_jumps: Optional[int] = None
    ):
        """执行实际的goto跳转

        迁移自 engine.py:862-911

        Args:
            from_node: 发起跳转的节点ID
            target_label: 目标标签
            scope: 渲染作用域（用于日志）
            max_jumps: 最大跳转次数（可选）

        Raises:
            ValueError: 当目标标签未定义时
            RuntimeError: 当总执行步骤数超过安全上限时
        """
        # 查找目标节点
        target_node_id = self.engine.label_to_node.get(target_label)
        if not target_node_id:
            raise ValueError(
                f"节点 '{from_node}' 的 goto 目标标签 '{target_label}' 未定义"
            )

        # 检查跳转次数限制
        goto_key = f"{from_node}→{target_label}"
        current_jumps = self.engine.node_goto_jumps.get(goto_key, 0)

        if max_jumps is not None and current_jumps >= max_jumps:
            logger.warning(
                f"节点 '{from_node}' 到标签 '{target_label}' 的 goto 已达到最大跳转次数 {max_jumps}，"
                f"跳过此次跳转"
            )
            return

        # 全局安全机制：防止无限循环
        max_total_steps = int(get_config_value("execution.max_total_steps", 1000))
        total_executed = sum(
            meta.get('execution_count', 0)
            for meta in self.engine.node_metadata.values()
        )
        if total_executed >= max_total_steps:
            raise RuntimeError(
                f"任务总执行步骤数已达到安全上限 {max_total_steps}，可能存在无限循环。"
                f"请检查 goto 逻辑或增加配置 'execution.max_total_steps'。"
            )

        # 更新跳转计数
        self.engine.node_goto_jumps[goto_key] = current_jumps + 1

        logger.info(
            f"🔄 执行 goto：从节点 '{from_node}' 跳转到标签 '{target_label}' (节点 '{target_node_id}')，"
            f"跳转次数: {current_jumps + 1}" + (f"/{max_jumps}" if max_jumps else "")
        )

        # 重置目标节点状态，允许重新执行
        self.engine.step_states[target_node_id] = self.engine.StepState.PENDING

        # 将目标节点加入就绪队列
        await self.engine.dag_scheduler.enqueue_ready_node(target_node_id)
        await self.engine.dag_scheduler.drain_ready_queue()

# -*- coding: utf-8 -*-
"""DAG图构建模块

负责将任务步骤定义解析为有向无环图（DAG），包括：
- 构建节点依赖关系
- 检测循环依赖
- 提取依赖结构

迁移自 engine.py:164-261
"""
from typing import Any, Dict, Set, TYPE_CHECKING

from packages.aura_core.observability.logging.core_logger import logger

if TYPE_CHECKING:
    from .execution_engine import ExecutionEngine


class GraphBuilder:
    """DAG图构建器

    负责将任务的步骤定义转换为可调度的依赖图。
    """

    def __init__(self, engine: 'ExecutionEngine'):
        """初始化图构建器

        Args:
            engine: 父级ExecutionEngine实例
        """
        self.engine = engine

    def build_graph(self, steps_dict: Dict[str, Any]):
        """从任务步骤定义中构建依赖图

        迁移自 engine.py:164-201

        Args:
            steps_dict: 任务的steps字典，格式为 {node_id: node_data}

        Raises:
            KeyError: 当依赖的节点不存在时
            ValueError: 当存在循环依赖时
        """
        self.engine.nodes = steps_dict
        all_node_ids = set(self.engine.nodes.keys())

        # 构建依赖图
        for node_id, node_data in self.engine.nodes.items():
            self.engine.step_states[node_id] = self.engine.StepState.PENDING
            self.engine.reverse_dependencies.setdefault(node_id, set())

            # 初始化节点元数据
            self.engine.node_metadata[node_id] = {
                'execution_count': 0,
                'retry_count': 0,
                'first_executed_at': None,
                'last_executed_at': None
            }

            deps_struct = node_data.get('depends_on', [])
            self.engine.dependencies[node_id] = deps_struct

            all_deps = self.get_all_deps_from_struct(deps_struct)
            for dep_id in all_deps:
                if dep_id not in all_node_ids:
                    raise KeyError(f"节点 '{node_id}' 引用了未定义的依赖: '{dep_id}'")
                self.engine.reverse_dependencies.setdefault(dep_id, set()).add(node_id)

        # 完整的循环依赖检测
        self.detect_circular_dependencies(all_node_ids)

    def detect_circular_dependencies(self, all_nodes: Set[str]):
        """使用DFS检测循环依赖

        迁移自 engine.py:202-241

        Args:
            all_nodes: 所有节点ID的集合

        Raises:
            ValueError: 当检测到循环依赖时，包含完整的循环路径
        """
        WHITE = 0  # 未访问
        GRAY = 1   # 正在访问（在当前路径中）
        BLACK = 2  # 已访问完成

        colors = {node: WHITE for node in all_nodes}
        path = []  # 当前路径，用于报告循环

        def dfs(node: str) -> bool:
            """DFS访问节点，返回True表示发现循环"""
            colors[node] = GRAY
            path.append(node)

            # 获取所有依赖
            deps = self.get_all_deps_from_struct(
                self.engine.dependencies.get(node, [])
            )

            for dep in deps:
                if colors[dep] == GRAY:
                    # 发现循环！
                    cycle_start = path.index(dep)
                    cycle = path[cycle_start:] + [dep]
                    raise ValueError(
                        f"检测到循环依赖: {' → '.join(cycle)}\n"
                        f"请检查以下节点的 depends_on 配置"
                    )
                elif colors[dep] == WHITE:
                    if dfs(dep):
                        return True

            path.pop()
            colors[node] = BLACK
            return False

        # 对每个未访问的节点执行DFS
        for node in all_nodes:
            if colors[node] == WHITE:
                path = []
                dfs(node)

    def get_all_deps_from_struct(self, struct: Any) -> Set[str]:
        """递归地从复杂的依赖结构中提取所有节点ID

        迁移自 engine.py:242-261

        支持的依赖结构：
        - 字符串: "node_id" 或 "when:expression"
        - 列表: ["node1", "node2", ...]
        - 字典: {"and": [...]} 或 {"or": [...]} 或 {"not": ...}

        Args:
            struct: 依赖结构（可以是str, list, dict等）

        Returns:
            所有依赖节点ID的集合（不包括when条件）
        """
        deps = set()

        if isinstance(struct, str):
            if not struct.startswith("when:"):
                deps.add(struct)

        elif isinstance(struct, list):
            for item in struct:
                deps.update(self.get_all_deps_from_struct(item))

        elif isinstance(struct, dict):
            if 'and' in struct:
                deps.update(self.get_all_deps_from_struct(struct['and']))
            elif 'or' in struct:
                deps.update(self.get_all_deps_from_struct(struct['or']))
            elif 'not' in struct:
                deps.update(self.get_all_deps_from_struct(struct['not']))
            else:
                # 状态查询格式: {node_id: status}
                deps.update(struct.keys())

        return deps

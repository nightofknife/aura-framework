# packages/aura_core/context.py

from __future__ import annotations
import copy
from typing import Any, Dict, List


class ExecutionContext:
    """
    管理单次任务执行期间的数据流。
    这是一个只增不减的数据结构，支持分支和合并。
    """

    def __init__(self, initial_data: Dict[str, Any] = None):
        """
        初始化一个执行上下文。

        :param initial_data: 任务启动时传入的初始数据。
        """
        self.data: Dict[str, Any] = {
            "initial": initial_data or {},
            "nodes": {}
        }

    def fork(self) -> 'ExecutionContext':
        """
        为并行分支创建一个当前上下文的深度拷贝副本。
        """
        forked_context = ExecutionContext()
        forked_context.data = copy.deepcopy(self.data)
        return forked_context

    def merge(self, other_contexts: List['ExecutionContext']):
        """
        将来自多个父分支的上下文合并到当前上下文中。
        由于节点ID是唯一的，直接更新 'nodes' 字典即可。
        """
        for other in other_contexts:
            self.data["nodes"].update(other.data["nodes"])

    def add_node_result(self, node_id: str, result: Dict[str, Any]):
        """
        将一个节点的完整输出（包括run_state和具名输出）添加到上下文中。
        """
        self.data["nodes"][node_id] = result

    def __repr__(self):
        return f"ExecutionContext(initial_keys={list(self.data['initial'].keys())}, node_keys={list(self.data['nodes'].keys())})"


# packages/aura_core/context.py

from __future__ import annotations
import copy
from typing import Any, Dict, List, Optional


class ExecutionContext:
    """
    管理单次任务执行期间的数据流。
    这是一个只增不减的数据结构，支持分支和合并。
    """

    # [MODIFIED] __init__ 接受新的 'inputs' 参数
    def __init__(self, initial_data: Optional[Dict[str, Any]] = None, inputs: Optional[Dict[str, Any]] = None):
        """
        初始化一个执行上下文。

        :param initial_data: 任务启动时由触发器等传入的初始数据。
        :param inputs: 任务作为可调用实体时传入的参数。
        """
        # [MODIFIED] 扩展 data 结构以包含 inputs 和 loop
        self.data: Dict[str, Any] = {
            "initial": initial_data or {},
            "inputs": inputs or {},
            "nodes": {},
            "loop": {}  # 用于存放循环变量 (item, index)
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
        'initial', 'inputs', 和 'loop' 数据在分支中是继承或隔离的，不需要合并。
        """
        for other in other_contexts:
            self.data["nodes"].update(other.data["nodes"])

    def add_node_result(self, node_id: str, result: Dict[str, Any]):
        """
        将一个节点的完整输出（包括run_state和具名输出）添加到上下文中。
        """
        self.data["nodes"][node_id] = result

    # [NEW] 用于在循环迭代中设置特殊变量的新方法
    def set_loop_variables(self, loop_vars: Dict[str, Any]):
        """为单次迭代的上下文设置循环变量 (e.g., item, index)。"""
        self.data['loop'] = loop_vars

    # [MODIFIED] 更新 __repr__ 以反映新的数据结构
    def __repr__(self):
        return (f"ExecutionContext(initial_keys={list(self.data['initial'].keys())}, "
                f"inputs_keys={list(self.data['inputs'].keys())}, "
                f"node_keys={list(self.data['nodes'].keys())})")


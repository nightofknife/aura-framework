# packages/aura_core/context.py
"""
定义了 `ExecutionContext` 类，用于管理单次任务执行期间的所有数据。

该模块的核心是 `ExecutionContext`，它作为一个可变的、树状的数据容器，
在任务的整个生命周期中传递。它负责收集和组织来自不同来源的数据，
包括初始触发数据、任务输入参数、每个节点的执行结果以及循环中的迭代变量。

它的设计支持了 Aura 框架中的几个关键特性：
- **数据隔离**: 通过结构化的字典（`initial`, `inputs`, `nodes`, `loop`）清晰地分离不同类型的数据。
- **并行执行**: `fork` 和 `merge` 方法允许上下文在并行分支中安全地复制和合并，这是实现 `parallel` 步骤的基础。
- **状态追溯**: 由于所有节点的输出都被记录在 `nodes` 中，因此可以方便地回溯和调试任务的执行过程。
"""

from __future__ import annotations
import copy
from typing import Any, Dict, List, Optional


class ExecutionContext:
    """
    管理单次任务执行期间的数据流。

    这是一个在任务执行期间随身携带的数据“手提箱”。它被设计成一个只增不减的
    数据结构，以支持任务执行过程中的分支和合并操作。

    Attributes:
        data (Dict[str, Any]): 存储所有上下文数据的核心字典。它包含四个顶级键：
            - 'initial': 由触发器（如定时器、事件）传入的初始数据。
            - 'inputs': 当任务作为可调用实体被另一个任务调用时，传入的参数。
            - 'nodes': 一个字典，键是节点ID，值是该节点的完整输出结果。
            - 'loop': 一个临时字典，用于存放当前循环迭代的变量（如 `item` 和 `index`）。
    """

    def __init__(self, initial_data: Optional[Dict[str, Any]] = None, inputs: Optional[Dict[str, Any]] = None):
        """
        初始化一个执行上下文。

        Args:
            initial_data (Optional[Dict[str, Any]]): 任务启动时由触发器等传入的初始数据。
                这部分数据在整个任务执行期间通常是只读的。
            inputs (Optional[Dict[str, Any]]): 当任务作为子任务被调用时，由父任务传入的参数。
        """
        self.data: Dict[str, Any] = {
            "initial": initial_data or {},
            "inputs": inputs or {},
            "nodes": {},
            "loop": {}  # 用于存放循环变量 (item, index)
        }

    def fork(self) -> 'ExecutionContext':
        """
        为并行分支创建一个当前上下文的深度拷贝副本。

        当任务执行遇到 `parallel` 步骤时，会为每个并行分支调用此方法
        创建一个独立的上下文。这可以防止并行分支之间的数据互相干扰。

        Returns:
            ExecutionContext: 一个与当前上下文状态完全相同的新实例。
        """
        forked_context = ExecutionContext()
        forked_context.data = copy.deepcopy(self.data)
        return forked_context

    def merge(self, other_contexts: List['ExecutionContext']):
        """
        将来自多个父分支的上下文合并到当前上下文中。

        在 `parallel` 步骤的所有分支都执行完毕后，调用此方法将所有分支的
        结果合并回主流程的上下文中。合并策略很简单：由于节点ID在整个任务中
        是唯一的，只需将所有分支的 `nodes` 字典合并即可。

        Args:
            other_contexts (List[ExecutionContext]): 一个包含所有已完成分支的
                `ExecutionContext` 对象的列表。
        """
        for other in other_contexts:
            self.data["nodes"].update(other.data["nodes"])

    def add_node_result(self, node_id: str, result: Dict[str, Any]):
        """
        将一个节点的完整输出添加到上下文中。

        每个节点（步骤）执行完毕后，其结果（包括运行状态和具名输出）
        都会通过此方法记录到 `data['nodes']` 中。

        Args:
            node_id (str): 完成执行的节点的唯一ID。
            result (Dict[str, Any]): 该节点的完整输出字典。
        """
        self.data["nodes"][node_id] = result

    def set_loop_variables(self, loop_vars: Dict[str, Any]):
        """
        为单次循环迭代设置特殊的上下文变量。

        在执行 `loop` 步骤的每次迭代之前，会调用此方法将当前迭代的
        特定变量（如 `item` 和 `index`）放入 `data['loop']` 中。
        这使得在循环体内部的步骤可以通过 `{{ loop.item }}` 来访问这些变量。

        Args:
            loop_vars (Dict[str, Any]): 包含循环变量的字典，例如 `{'item': ..., 'index': ...}`。
        """
        self.data['loop'] = loop_vars

    def __repr__(self) -> str:
        """返回一个简洁的、对开发者友好的上下文表示。"""
        return (f"ExecutionContext(initial_keys={list(self.data['initial'].keys())}, "
                f"inputs_keys={list(self.data['inputs'].keys())}, "
                f"node_keys={list(self.data['nodes'].keys())})")


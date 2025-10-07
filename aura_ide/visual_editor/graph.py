"""
定义了可视化编辑器的核心图组件和自定义节点。

该模块基于 `OdenGraphQt` 库，定义了 Aura 任务图的特定节点类型和
主图谱类 `AuraNodeGraph`。

主要组件:
- **AuraBaseNode**: 所有 Aura 节点的基类，提供了一个用于存储自定义属性
  的容器 `_aura_props`，以避免与底层库的属性系统冲突。
- **ActionNode**: 代表一个具体的行为（Action）的节点。
- **LogicGateNode**: 代表逻辑门（如 `and`, `or`）的节点，用于控制依赖关系。
- **CommentNode**: 用于在图上添加注释的节点。
- **AuraNodeGraph**: 主图谱类，继承自 `NodeGraph`。它负责注册自定义节点，
  并实现了从 Aura 的任务定义（YAML格式）加载图和将图序列化回任务定义的
  核心逻辑。
"""
from typing import Dict, Any, List, Optional

from OdenGraphQt import NodeGraph, BaseNode


# ------------------------------
# 自定义节点
# ------------------------------
class AuraBaseNode(BaseNode):
    """
    所有 Aura 节点的抽象基类。

    它提供了一个独立的属性系统 (`_aura_props`)，用于存储特定于 Aura 的数据，
    如 `node_id`，以避免与 `NodeGraphQt` 库的内部属性发生冲突。
    """
    def __init__(self, *args, **kwargs):
        """初始化基类节点。"""
        super().__init__(*args, **kwargs)
        try:
            self.set_color(25, 65, 125)
        except Exception:
            pass
        self._aura_props: Dict[str, Any] = {}

    def get_aura_property(self, name: str) -> Any:
        """
        获取一个存储在节点上的自定义 Aura 属性。

        Args:
            name (str): 属性的名称。

        Returns:
            Any: 属性的值。
        """
        return self._aura_props.get(name)

    def set_aura_property(self, name: str, value: Any):
        """
        在节点上设置一个自定义的 Aura 属性。

        Args:
            name (str): 属性的名称。
            value (Any): 属性的值。
        """
        self._aura_props[name] = value


class ActionNode(AuraBaseNode):
    """
    代表一个具体“行为”（Action）的可视化节点。
    """
    __identifier__ = 'aura'
    NODE_NAME = 'Action'

    def __init__(self):
        """初始化行为节点，创建默认的输入和输出端口。"""
        super().__init__()
        self.add_input('prev', multi_input=True)
        self.add_output('next')
        self.set_aura_property('node_id', self.id)
        self.set_aura_property('action_id', '')
        self.set_aura_property('params', {})


class LogicGateNode(AuraBaseNode):
    """
    代表一个逻辑门（如 AND, OR）的节点，用于组合依赖关系。
    """
    __identifier__ = 'aura'
    NODE_NAME = 'LogicGate'

    def __init__(self):
        """初始化逻辑门节点。"""
        super().__init__()
        self.add_input('in', multi_input=True)
        self.add_output('out')
        self.set_aura_property('node_id', self.id)
        self.set_aura_property('type', 'and')
        try:
            self.set_color(120, 25, 55)
        except Exception:
            pass


class CommentNode(AuraBaseNode):
    """
    一个用于在图谱中添加文本注释的节点。
    """
    __identifier__ = 'aura'
    NODE_NAME = 'Comment'

    def __init__(self):
        """初始化注释节点。"""
        super().__init__()
        self.set_aura_property('text', 'This is a comment.')
        try:
            self.view.width = 200
            self.view.height = 80
            self.set_color(100, 100, 100)
        except Exception:
            pass


# ------------------------------
# 主图谱类
# ------------------------------
class AuraNodeGraph(NodeGraph):
    """
    Aura 任务的可视化图谱编辑器。

    这个类继承自 `NodeGraphQt` 的 `NodeGraph`，并专门为 Aura 的任务
    结构进行了定制。它负责加载、保存和编辑任务的依赖图。
    """

    def __init__(self, *args, **kwargs):
        """初始化图谱，注册所有自定义节点并设置视觉样式。"""
        super().__init__(*args, **kwargs)
        self._readonly = False
        self._exec_flow_visible = True

        try:
            self.set_background_color(35, 35, 35)
            self.set_grid_color(50, 50, 50)
            viewer = self.viewer()
            viewer.setProperty('zoom_min', -5.0)
            viewer.setProperty('zoom_max', 2.0)
        except Exception:
            pass

        self.register_nodes([ActionNode, LogicGateNode, CommentNode])

    # ---------- 基础工具 ----------
    def get_node_by_aura_id(self, node_id: str) -> Optional[AuraBaseNode]:
        """
        通过自定义的 'node_id' 属性查找节点。

        Args:
            node_id (str): 节点的自定义ID。

        Returns:
            Optional[AuraBaseNode]: 找到的节点实例，如果不存在则返回 None。
        """
        for node in self.all_nodes():
            if isinstance(node, AuraBaseNode) and node.get_aura_property('node_id') == node_id:
                return node
        return None

    def set_readonly(self, readonly: bool):
        """
        设置图谱的只读模式。

        在只读模式下，用户不能移动、选择或修改节点和连接。

        Args:
            readonly (bool): True 表示设为只读，False 表示可编辑。
        """
        self._readonly = bool(readonly)
        try:
            v = self.viewer()
            v.setInteractive(not self._readonly)
            v.setProperty('context_menu', not self._readonly)
            v.setProperty('node_selection_rect', not self._readonly)
        except Exception:
            pass

        for n in self.all_nodes():
            try:
                n.set_locked(self._readonly)
                gi = n.view
                gi.setFlag(gi.GraphicsItemFlag.ItemIsMovable, not self._readonly)
                gi.setFlag(gi.GraphicsItemFlag.ItemIsSelectable, not self._readonly)
            except Exception:
                pass

    def set_execution_flow_visible(self, visible: bool):
        """
        设置执行流程连接线的可见性（占位符）。

        Args:
            visible (bool): 是否可见。
        """
        self._exec_flow_visible = bool(visible)
        return

    # ---------- 任务加载 ----------
    def load_task_definition(self, task_key: str, task_def: Dict[str, Any]):
        """
        根据任务定义字典加载或重建整个可视化图谱。

        此方法会先清空当前会话，然后根据 `steps` 字典中的定义
        创建所有节点，并根据 `depends_on` 字段建立它们之间的连接。

        Args:
            task_key (str): 当前任务的键名。
            task_def (Dict[str, Any]): 包含 `steps` 的任务定义字典。
        """
        self.clear_session()

        steps = task_def.get('steps')
        if not steps:
            return

        nodes_map: Dict[str, AuraBaseNode] = {}

        if isinstance(steps, list):
            # 处理旧的线性列表格式
            last_node: Optional[AuraBaseNode] = None
            for i, step_def in enumerate(steps):
                if not isinstance(step_def, dict): continue
                node_id = step_def.get('name') or f"step_{i}"
                action_id = step_def.get('action', 'unspecified')
                node_name = step_def.get('name', action_id)
                node: ActionNode = self.create_node('aura.ActionNode', name=node_name)
                node.set_aura_property('node_id', node_id)
                node.set_aura_property('action_id', action_id)
                node.set_aura_property('params', step_def.get('params', {}) or {})
                nodes_map[node_id] = node
                if last_node:
                    try: node.set_input(0, last_node.output(0))
                    except Exception:
                        try: last_node.outputs()['next'].connect_to(node.inputs()['prev'])
                        except Exception: pass
                last_node = node
        elif isinstance(steps, dict):
            # 处理新的图格式
            for node_id, step_def in steps.items():
                if not isinstance(step_def, dict): continue
                node_name = step_def.get('name', node_id)
                node: Optional[AuraBaseNode] = None
                if 'action' in step_def:
                    node = self.create_node('aura.ActionNode', name=node_name)
                    node.set_aura_property('action_id', step_def.get('action'))
                    node.set_aura_property('params', step_def.get('params', {}) or {})
                else:
                    node_type = step_def.get('type', 'and')
                    node = self.create_node('aura.LogicGateNode', name=node_name)
                    node.set_aura_property('type', node_type)
                if node:
                    node.set_aura_property('node_id', node_id)
                    nodes_map[node_id] = node

            for node_id, step_def in steps.items():
                curr = nodes_map.get(node_id)
                if not curr or not isinstance(step_def, dict): continue
                requires = step_def.get('depends_on', [])
                if isinstance(requires, str): requires = [requires]
                for req_id in requires:
                    prev = nodes_map.get(req_id)
                    if not prev: continue
                    try: curr.set_input(0, prev.output(0))
                    except Exception:
                        try:
                            (prev.outputs().get('next') or prev.outputs().get('out')).connect_to(
                                (curr.inputs().get('prev') or curr.inputs().get('in'))
                            )
                        except Exception: pass
        try:
            self.auto_layout_nodes()
            self.fit_to_selection()
        except Exception:
            pass
        if self._readonly:
            self.set_readonly(True)

    # ---------- 导出 ----------
    def to_dict(self) -> Dict[str, Any]:
        """
        将当前图谱的状态序列化为一个 Aura 任务定义字典。

        此方法会遍历图中的所有节点，推断出它们的依赖关系，并将其
        属性转换回 Aura 的 `steps` 字典格式。

        Returns:
            Dict[str, Any]: 一个包含 `steps` 键的字典，其值为所有节点的定义。
        """
        steps: Dict[str, Any] = {}

        for node in self.all_nodes():
            if not isinstance(node, (ActionNode, LogicGateNode)): continue
            node_id = node.get_aura_property('node_id')
            if not node_id: continue
            step: Dict[str, Any] = {}

            requires: List[str] = []
            input_port = node.inputs().get('prev') or node.inputs().get('in')
            if input_port:
                try:
                    for connected_port in input_port.connected_ports():
                        prev_node = connected_port.node()
                        if isinstance(prev_node, AuraBaseNode):
                            pid = prev_node.get_aura_property('node_id')
                            if pid: requires.append(pid)
                except Exception: pass
            if requires:
                step['depends_on'] = requires[0] if len(requires) == 1 else sorted(requires)

            if isinstance(node, ActionNode):
                step['action'] = node.get_aura_property('action_id')
                params = node.get_aura_property('params') or {}
                if params: step['params'] = params
            elif isinstance(node, LogicGateNode):
                step['type'] = node.get_aura_property('type') or 'and'

            steps[node_id] = step

        return {'steps': steps}

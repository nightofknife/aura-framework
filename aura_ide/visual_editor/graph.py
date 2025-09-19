# aura_ide/visual_editor/graph.py
from typing import Dict, Any, List, Optional

# ⬇️ NodeGraphQt -> OdenGraphQt
from OdenGraphQt import NodeGraph, BaseNode


# ------------------------------
# 自定义节点
# ------------------------------
class AuraBaseNode(BaseNode):
    """所有 Aura 节点的基类。注意：不覆盖库方法，避免 push_undo 等签名冲突。"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.set_color(25, 65, 125)
        except Exception:
            pass
        # 用我们自己的容器保存自定义属性，避免碰库的属性系统
        self._aura_props: Dict[str, Any] = {}

    def get_aura_property(self, name: str) -> Any:
        return self._aura_props.get(name)

    def set_aura_property(self, name: str, value: Any):
        self._aura_props[name] = value


class ActionNode(AuraBaseNode):
    __identifier__ = 'aura'
    NODE_NAME = 'Action'

    def __init__(self):
        super().__init__()
        self.add_input('prev', multi_input=True)
        self.add_output('next')
        self.set_aura_property('node_id', self.id)
        self.set_aura_property('action_id', '')
        self.set_aura_property('params', {})


class LogicGateNode(AuraBaseNode):
    __identifier__ = 'aura'
    NODE_NAME = 'LogicGate'

    def __init__(self):
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
    __identifier__ = 'aura'
    NODE_NAME = 'Comment'

    def __init__(self):
        super().__init__()
        self.set_aura_property('text', 'This is a comment.')
        # 这些属性在不同版本里可能略有差异，做容错
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
    """Aura 任务的可视化图谱，负责加载、保存和编辑。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._readonly = False
        self._exec_flow_visible = True

        # 背景、网格（容错调用）
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
        """通过自定义的 'node_id' 属性查找节点。"""
        for node in self.all_nodes():
            if isinstance(node, AuraBaseNode) and node.get_aura_property('node_id') == node_id:
                return node
        return None

    def set_readonly(self, readonly: bool):
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
        """旧 API 对“仅隐藏特定连线”没有稳定接口。这里做安全空操作，避免 AttributeError。"""
        self._exec_flow_visible = bool(visible)
        # 如需精细隐藏，可以后续用 scene() 遍历做“鸭子识别”，此处先不冒险。
        return

    # ---------- 任务加载 ----------
    def load_task_definition(self, task_key: str, task_def: Dict[str, Any]):
        self.clear_session()

        steps = task_def.get('steps')
        if not steps:
            return

        nodes_map: Dict[str, AuraBaseNode] = {}

        # v5：线性 steps 列表
        if isinstance(steps, list):
            last_node: Optional[AuraBaseNode] = None
            for i, step_def in enumerate(steps):
                if not isinstance(step_def, dict):
                    continue
                node_id = step_def.get('name') or f"step_{i}"
                action_id = step_def.get('action', 'unspecified')
                node_name = step_def.get('name', action_id)

                node: ActionNode = self.create_node('aura.ActionNode', name=node_name)  # type: ignore
                node.set_aura_property('node_id', node_id)
                node.set_aura_property('action_id', action_id)
                node.set_aura_property('params', step_def.get('params', {}) or {})
                nodes_map[node_id] = node

                if last_node:
                    # 推荐：使用 set_input(0, other.output(0))；失败则回退 connect_to
                    try:
                        node.set_input(0, last_node.output(0))
                    except Exception:
                        try:
                            last_node.outputs()['next'].connect_to(node.inputs()['prev'])
                        except Exception:
                            pass
                last_node = node

        # v6：图 steps 字典
        elif isinstance(steps, dict):
            # 先创建所有节点
            for node_id, step_def in steps.items():
                if not isinstance(step_def, dict):
                    continue
                node_name = step_def.get('name', node_id)
                node: Optional[AuraBaseNode] = None

                if 'action' in step_def:
                    node = self.create_node('aura.ActionNode', name=node_name)  # type: ignore
                    node.set_aura_property('action_id', step_def.get('action'))
                    node.set_aura_property('params', step_def.get('params', {}) or {})
                else:
                    node_type = step_def.get('type', 'and')
                    node = self.create_node('aura.LogicGateNode', name=node_name)  # type: ignore
                    node.set_aura_property('type', node_type)

                if node:
                    node.set_aura_property('node_id', node_id)
                    nodes_map[node_id] = node

            # 再按 depends_on 连线
            for node_id, step_def in steps.items():
                curr = nodes_map.get(node_id)
                if not curr or not isinstance(step_def, dict):
                    continue

                requires = step_def.get('depends_on', [])
                if isinstance(requires, str):
                    requires = [requires]

                for req_id in requires:
                    prev = nodes_map.get(req_id)
                    if not prev:
                        continue
                    try:
                        curr.set_input(0, prev.output(0))
                    except Exception:
                        try:
                            (prev.outputs().get('next') or prev.outputs().get('out')).connect_to(
                                (curr.inputs().get('prev') or curr.inputs().get('in'))
                            )
                        except Exception:
                            pass

        # 自动布局 + 视野适配（容错）
        try:
            self.auto_layout_nodes()
        except Exception:
            pass
        try:
            self.fit_to_selection()
        except Exception:
            pass

        if self._readonly:
            self.set_readonly(True)

    # ---------- 导出 ----------
    def to_dict(self) -> Dict[str, Any]:
        steps: Dict[str, Any] = {}

        for node in self.all_nodes():
            if not isinstance(node, (ActionNode, LogicGateNode)):
                continue

            node_id = node.get_aura_property('node_id')
            if not node_id:
                continue

            step: Dict[str, Any] = {}

            # 依赖：通过已连接的输入端口推断
            requires: List[str] = []
            input_port = node.inputs().get('prev') or node.inputs().get('in')
            if input_port:
                try:
                    for connected_port in input_port.connected_ports():
                        prev_node = connected_port.node()
                        if isinstance(prev_node, AuraBaseNode):
                            pid = prev_node.get_aura_property('node_id')
                            if pid:
                                requires.append(pid)
                except Exception:
                    pass
            if requires:
                step['depends_on'] = requires[0] if len(requires) == 1 else sorted(requires)

            # 节点定义
            if isinstance(node, ActionNode):
                step['action'] = node.get_aura_property('action_id')
                params = node.get_aura_property('params') or {}
                if params:
                    step['params'] = params
            elif isinstance(node, LogicGateNode):
                step['type'] = node.get_aura_property('type') or 'and'

            steps[node_id] = step

        return {'steps': steps}

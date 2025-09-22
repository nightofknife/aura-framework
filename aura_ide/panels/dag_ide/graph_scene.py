# graph_scene.py
import yaml
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QPainterPath, QPen, QBrush, QFont, QColor, QDrag, QMimeData, QUndoStack
from PySide6.QtWidgets import QGraphicsItemGroup, QGraphicsRectItem, QGraphicsTextItem, QGraphicsEllipseItem, \
    QGraphicsPathItem, QGraphicsSceneDragDropEvent, QGraphicsScene
from typing import Dict, Any, List, Optional

from packages.aura_core.api import ActionDefinition


class AuraNodeItem(QGraphicsItemGroup):
    """DAG节点：支持拖拽、端口、展开。"""
    NODE_WIDTH, NODE_HEIGHT = 200, 80
    PORT_RADIUS = 6
    GRID_SIZE = 20  # Snap网格

    def __init__(self, node_id: str, action_def: Optional[ActionDefinition] = None, parent=None):
        super().__init__(parent)
        self.node_id = node_id
        self.action_def = action_def
        self.params: Dict[str, Any] = {}  # params dict
        self.depends_on: List[str] = []  # 父节点ID
        self.is_expanded = False
        self.input_ports: List[QGraphicsEllipseItem] = []  # 左端口
        self.output_ports: List[QGraphicsEllipseItem] = []  # 右端口
        self._build_visual()
        self.setFlag(QGraphicsItemGroup.ItemIsMovable, True)
        self.setFlag(QGraphicsItemGroup.ItemIsSelectable, True)
        self.setAcceptDrops(True)  # 子节点拖入

    def _build_visual(self):
        # 背景
        rect = QGraphicsRectItem(0, 0, self.NODE_WIDTH, self.NODE_HEIGHT, self)
        rect.setBrush(QBrush(QColor(240, 240, 255)))  # 浅蓝
        rect.setPen(QPen(QColor(100, 100, 150), 2))

        # 头部文本
        action_name = self.action_def.name if self.action_def else "Unnamed"
        text = QGraphicsTextItem(f"{self.node_id}\n[action: {action_name}]", self)
        text.setPos(10, 10)
        text.setFont(QFont("Arial", 10, QFont.Weight.Bold))

        # 输出端口 (默认1个右)
        out_port = QGraphicsEllipseItem(self.NODE_WIDTH - self.PORT_RADIUS, self.NODE_HEIGHT//2 - self.PORT_RADIUS//2, self.PORT_RADIUS*2, self.PORT_RADIUS*2, self)
        out_port.setBrush(QBrush(QColor(0, 200, 0)))  # 绿
        self.output_ports.append(out_port)

        # 输入端口 (初始1个左，可动态加)
        in_port = QGraphicsEllipseItem(-self.PORT_RADIUS, self.NODE_HEIGHT//2 - self.PORT_RADIUS//2, self.PORT_RADIUS*2, self.PORT_RADIUS*2, self)
        in_port.setBrush(QBrush(QColor(200, 0, 0)))  # 红
        self.input_ports.append(in_port)

        # 展开按钮 (+/-)
        expand_btn = QGraphicsTextItem("+", self)
        expand_btn.setPos(self.NODE_WIDTH - 20, self.NODE_HEIGHT - 20)
        expand_btn.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        expand_btn.mousePressEvent = self._on_expand_click

        self.addToGroup(rect, text, out_port, in_port, expand_btn)

    def _on_expand_click(self, event):
        self.is_expanded = not self.is_expanded
        # TODO: 动态添加子item (params列表 or 子GraphView)
        self.prepareGeometryChange()  # 通知场景大小变
        self.update()

    def add_input_port(self):
        y = len(self.input_ports) * 30 + 20  # 垂直堆叠
        port = QGraphicsEllipseItem(-self.PORT_RADIUS, y, self.PORT_RADIUS*2, self.PORT_RADIUS*2, self)
        port.setBrush(QBrush(QColor(200, 0, 0)))
        self.input_ports.append(port)
        self.addToGroup(port)
        return port

    def mouseMoveEvent(self, event):
        # Snap to grid
        pos = event.scenePos()
        snapped_x = round(pos.x() / self.GRID_SIZE) * self.GRID_SIZE
        snapped_y = round(pos.y() / self.GRID_SIZE) * self.GRID_SIZE
        self.setPos(snapped_x, snapped_y)
        # 更新连线
        for edge in self.scene().edges:  # 假设场景有edges list
            if edge.target == self or edge.source == self:
                edge.update_path()
        super().mouseMoveEvent(event)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.NODE_WIDTH + 20, self.NODE_HEIGHT + (100 if self.is_expanded else 0))  # 动态

    def paint(self, painter: QPainter, option, widget):
        # 自定义绘制 (e.g., 渐变)
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        painter.drawRoundedRect(self.boundingRect(), 5, 5)

class AuraEdge(QGraphicsPathItem):
    """连线：Bezier + 箭头，支持标签。"""
    def __init__(self, source_port, target_port, label: str = "", parent=None):
        super().__init__(parent)
        self.source_port = source_port
        self.target_port = target_port
        self.label = label  # e.g., "and"
        self.setPen(QPen(QColor(0, 0, 0), 2))
        self.setBrush(QBrush(QColor(0, 0, 0)))
        self.update_path()

    def update_path(self):
        if not self.scene():
            return
        s_pos = self.source_port.scenePos()
        t_pos = self.target_port.scenePos()
        path = QPainterPath(s_pos)
        # Bezier弯曲 (防交叉)
        ctrl1 = s_pos + QPointF(50, -30)
        ctrl2 = t_pos + QPointF(-50, 30)
        path.cubicTo(ctrl1, ctrl2, t_pos)
        # 箭头
        arrow = QPainterPath()
        arrow.moveTo(t_pos)
        arrow.lineTo(t_pos + QPointF(-10, -5))
        arrow.lineTo(t_pos + QPointF(-10, 5))
        arrow.closeSubpath()
        self.setPath(path)
        # 标签 (沿中点)
        label_text = QGraphicsTextItem(self.label, self.scene())
        label_text.setPos((s_pos + t_pos) / 2)
        label_text.setFont(QFont("Arial", 8))

    def paint(self, painter: QPainter, option, widget):
        super().paint(painter, option, widget)
        # 箭头填充
        painter.fillPath(self.path(), self.brush())

class AuraGraphController:
    """场景控制器：管理节点/边、布局、to_dict。"""
    def __init__(self, scene: QGraphicsScene):
        self.scene = scene
        self.nodes: Dict[str, AuraNodeItem] = {}
        self.edges: List[AuraEdge] = []
        self.undo_stack = QUndoStack()  # 撤销
        self.action_defs: List[ActionDefinition] = []  # 从bridge加载

    def load_from_yaml(self, yaml_content: str):
        self.clear()
        data = yaml.safe_load(yaml_content) or {}
        task_key = next(iter(data), "default")
        task_def = data.get(task_key, {})
        steps = task_def.get('steps', {})

        # 创建节点
        for node_id, step in steps.items():
            action_name = step.get('action', '')
            action_def = next((d for d in self.action_defs if d.name == action_name), None)
            node = AuraNodeItem(node_id, action_def)
            node.params = step.get('params', {})
            self.scene.addItem(node)
            self.nodes[node_id] = node

        # 创建边 (depends_on)
        for node_id, step in steps.items():
            deps = step.get('depends_on', [])
            node = self.nodes[node_id]
            for dep_id in deps:
                dep_node = self.nodes.get(dep_id)
                if dep_node:
                    # 连线: dep输出 -> node输入
                    out_port = dep_node.output_ports[0]
                    in_port = node.add_input_port() if len(node.input_ports) == 1 else node.input_ports[-1]
                    edge = AuraEdge(out_port, in_port, label="and" if len(deps) > 1 else "")
                    self.scene.addItem(edge)
                    self.edges.append(edge)

        self.auto_layout()

    def to_yaml(self) -> str:
        steps = {}
        for node_id, node in self.nodes.items():
            step = {'action': node.action_def.name if node.action_def else '', 'params': node.params}
            # 推断depends_on
            deps = []
            for edge in self.edges:
                if edge.target_port.parentItem() == node:
                    deps.append(edge.source_port.parentItem().node_id)
            if deps:
                step['depends_on'] = deps[0] if len(deps) == 1 else deps  # 简单OR，多=专用Gate
            steps[node_id] = step
        return yaml.dump({'default': {'steps': steps}}, default_flow_style=False, indent=2)

    def create_node_from_drag(self, action_def: ActionDefinition, pos: QPointF):
        node_id = f"step_{len(self.nodes)}"
        node = AuraNodeItem(node_id, action_def)
        node.setPos(pos)
        self.scene.addItem(node)
        self.nodes[node_id] = node
        self.undo_stack.push(CreateNodeCommand(self, node))  # 撤销命令

    def connect_nodes(self, source_node: AuraNodeItem, target_node: AuraNodeItem):
        out_port = source_node.output_ports[0]
        in_port = target_node.add_input_port()
        edge = AuraEdge(out_port, in_port)
        self.scene.addItem(edge)
        self.edges.append(edge)
        # 更新depends_on
        target_node.depends_on.append(source_node.node_id)
        self.undo_stack.push(CreateEdgeCommand(self, edge))

    def auto_layout(self):
        # 简单拓扑: 列出节点，按输入度排序
        sorted_nodes = sorted(self.nodes.values(), key=lambda n: len(n.depends_on))
        for i, node in enumerate(sorted_nodes):
            node.setPos(i * 250, 0)  # x=层，y=后续优化rank
        # 更新所有边
        for edge in self.edges:
            edge.update_path()
        self.scene.update()  # 重绘

    def clear(self):
        for item in self.scene.items():
            self.scene.removeItem(item)
        self.nodes.clear()
        self.edges.clear()

# 撤销命令 (QUndoCommand子类)
class CreateNodeCommand(QUndoCommand):
    def __init__(self, controller: AuraGraphController, node: AuraNodeItem):
        super().__init__()
        self.controller = controller
        self.node = node
        self.setText("Create Node")

    def undo(self):
        self.controller.scene.removeItem(self.node)
        del self.controller.nodes[self.node.node_id]

    def redo(self):
        self.controller.scene.addItem(self.node)
        self.controller.nodes[self.node.node_id] = self.node
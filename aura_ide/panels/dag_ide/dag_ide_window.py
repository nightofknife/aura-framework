# dag_ide_window.py

import sys
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QLineF
from PySide6.QtGui import QPainter, QPainterPath, QPen, QBrush, QFont, QColor, QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (QMainWindow, QSplitter, QDockWidget, QVBoxLayout, QHBoxLayout, QListWidget,
                               QListWidgetItem, QGraphicsView, QGraphicsScene, QGraphicsItemGroup, QGraphicsRectItem,
                               QGraphicsTextItem, QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsProxyWidget,
                               QToolBar, QAction, QMenu, QInputDialog, QMessageBox, QUndoStack, QUndoView,
                               QLineEdit, QTextEdit, QComboBox, QFormLayout, QGroupBox, QLabel, QPushButton,
                               QTabWidget, QTreeWidget, QTreeWidgetItem, QWidget)
from aura_ide.core_integration.qt_bridge import QtBridge  # 您的桥接
from aura_ide.panels.base_panel import BasePanel
from packages.aura_core.api import ActionDefinition  # 动作定义


class DagIdeWindow(QMainWindow):
    def __init__(self, bridge: QtBridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.setWindowTitle("DAG_IDE - Aura任务可视编辑器")
        self.resize(1400, 900)
        self._current_file: Optional[str] = None  # plan/rel_path

        # 撤销栈
        self.undo_stack = QUndoStack(self)
        self.undo_view = QUndoView(self.undo_stack)
        self.addDockWidget(Qt.RightDockWidgetArea, self.undo_view)

        # 中央Splitter
        central = QSplitter(Qt.Horizontal)
        self.setCentralWidget(central)

        # 左侧Dock: 工作区 + 调色板
        left_dock = QDockWidget("工具", self)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        self.workspace_tree = QTreeWidget()  # 如现有, 双击load
        self.workspace_tree.itemDoubleClicked.connect(self._load_file)
        self.palette = NodePalette(self.bridge.get_all_action_definitions())
        self.palette.node_dragged.connect(self._create_node_from_drag)
        left_layout.addWidget(QLabel("工作区"))
        left_layout.addWidget(self.workspace_tree)
        left_layout.addWidget(QLabel("节点调色板"))
        left_layout.addWidget(self.palette)
        left_dock.setWidget(left_widget)
        self.addDockWidget(Qt.LeftDockWidgetArea, left_dock)

        # 中央: GraphView
        self.graph_view = QGraphicsView()
        self.scene = QGraphicsScene()
        self.graph_view.setScene(self.scene)
        self.graph_view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)  # 选多节点
        self.graph_controller = AuraGraphController(self.scene)
        self.graph_controller.action_defs = self.bridge.get_all_action_definitions()
        central.addWidget(self.graph_view)

        # 右侧Dock: Inspector
        right_dock = QDockWidget("节点编辑", self)
        self.inspector = DagInspector()
        self.inspector.node_changed.connect(self._on_node_changed)
        right_dock.setWidget(self.inspector)
        self.addDockWidget(Qt.RightDockWidgetArea, right_dock)

        # 工具栏
        toolbar = self.addToolBar("DAG工具")
        new_action = QAction("新建DAG", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self.new_dag)
        open_action = QAction("打开", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_file)
        save_action = QAction("保存", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_file)
        layout_action = QAction("自动布局", self)
        layout_action.triggered.connect(self.auto_layout)
        validate_action = QAction("验证DAG", self)
        validate_action.triggered.connect(self.validate_dag)
        toolbar.addAction(new_action)
        toolbar.addAction(open_action)
        toolbar.addAction(save_action)
        toolbar.addSeparator()
        toolbar.addAction(layout_action)
        toolbar.addAction(validate_action)

        # 右键菜单 (画布)
        self.graph_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.graph_view.customContextMenuRequested.connect(self._show_context_menu)

        # 场景事件: 节点选中
        self.scene.selectionChanged.connect(self._on_selection_changed)

        # 状态栏
        self.status_bar = self.statusBar()
        self.status_label = QLabel("就绪 | 节点: 0 | 边: 0")
        self.status_bar.addWidget(self.status_label)

        self._is_dirty = False
        self.update_status()

    def _on_selection_changed(self):
        selected = self.scene.selectedItems()
        if selected and isinstance(selected[0], AuraNodeItem):
            self.inspector.load_node(selected[0])
        else:
            self.inspector.clear()  # 自定义clear方法

    def _create_node_from_drag(self, action_def: ActionDefinition, pos: QPointF):
        scene_pos = self.graph_view.mapToScene(pos)
        snapped_pos = QPointF(round(scene_pos.x() / 20) * 20, round(scene_pos.y() / 20) * 20)
        self.graph_controller.create_node_from_drag(action_def, snapped_pos)

    def new_dag(self):
        if self._is_dirty and not self._confirm_discard():
            return
        self.graph_controller.clear()
        self._current_file = None
        self.setWindowTitle("DAG_IDE - 新DAG")
        self._is_dirty = False

    def open_file(self):
        # TODO: QFileDialog选YAML (或从workspace_tree双击)
        file_path, _ = QFileDialog.getOpenFileName(self, "打开任务YAML", "", "YAML (*.yaml *.yml)")
        if file_path:
            plan_name = "default"  # 从路径推断 or 对话
            rel_path = file_path.split("plans/")[1] if "plans/" in file_path else ""  # 简化
            try:
                content = self.bridge.read_task_file(plan_name, rel_path)
                self.graph_controller.load_from_yaml(content)
                self._current_file = f"{plan_name}/{rel_path}"
                self.setWindowTitle(f"DAG_IDE - {self._current_file}")
                self._is_dirty = False
            except Exception as e:
                QMessageBox.critical(self, "打开失败", str(e))

    def save_file(self):
        if not self._current_file:
            return self.save_as_file()
        try:
            content = self.graph_controller.to_yaml()
            plan, rel_path = self._current_file.split("/", 1)
            self.bridge.save_task_file(plan, rel_path, content)
            self._is_dirty = False
            self.setWindowTitle(f"DAG_IDE - {self._current_file}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def save_as_file(self):
        # QFileDialog选路径
        file_path, _ = QFileDialog.getSaveFileName(self, "保存为YAML", "", "YAML (*.yaml)")
        if file_path:
            # 推断plan/rel_path
            self._current_file = "default/tasks/new.yaml"  # 简化, 实际从对话
            self.save_file()

    def auto_layout(self):
        self.graph_controller.auto_layout()
        self._is_dirty = True
        self.update_status()

    def validate_dag(self):
        content = self.graph_controller.to_yaml()
        plan = self._current_file.split("/")[0] if self._current_file else "default"
        errors = self.bridge.validate_dag(plan, yaml.safe_load(content)['default']['steps'])
        if errors:
            self._show_errors(errors)
        else:
            QMessageBox.information(self, "验证通过", "DAG有效，无循环/缺失依赖")

    def _show_errors(self, errors: List[Dict]):
        dialog = QDialog(self)
        dialog.setWindowTitle("DAG问题")
        tree = QTreeWidget()
        tree.setHeaderLabels(["类型", "消息", "节点"])
        for err in errors:
            item = QTreeWidgetItem([err['type'], err['message'], err.get('node_id', '')])
            tree.addTopLevelItem(item)
        layout = QVBoxLayout(dialog)
        layout.addWidget(tree)
        dialog.setLayout(layout)
        dialog.exec()
        # 点击跳转: tree.itemClicked.connect(lambda item: self.graph_controller.center_on_node(item.text(2)))

    def _load_file(self, item, column):
        # 从workspace_tree双击
        # 类似open_file逻辑
        pass

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        add_action = QAction("添加Action节点", self)
        add_action.triggered.connect(lambda: self._add_node_at_pos(pos))
        menu.addAction(add_action)
        layout_action = QAction("自动布局", self)
        layout_action.triggered.connect(self.auto_layout)
        menu.addAction(layout_action)
        menu.exec(self.graph_view.mapToGlobal(pos))

    def _add_node_at_pos(self, pos):
        # 从调色板选 or 默认
        defn = self.bridge.get_all_action_definitions()[0]  # 示例
        scene_pos = self.graph_view.mapToScene(pos)
        self.graph_controller.create_node_from_drag(defn, scene_pos)

    def _on_node_changed(self, node_id: str, props: Dict):
        node = self.graph_controller.nodes.get(node_id)
        if node:
            node.params.update(props)
        self._is_dirty = True
        self.update_status()

    def update_status(self):
        node_count = len(self.graph_controller.nodes)
        edge_count = len(self.graph_controller.edges)
        dirty = " *" if self._is_dirty else ""
        self.status_label.setText(f"节点: {node_count} | 边: {edge_count}{dirty}")

    def closeEvent(self, event):
        if self._is_dirty and not self._confirm_discard():
            event.ignore()
            return
        self.bridge.stop_core()  # 如果需要
        event.accept()

    def _confirm_discard(self) -> bool:
        reply = QMessageBox.question(self, "未保存", "有未保存更改，是否丢弃？", QMessageBox.Yes | QMessageBox.No)
        return reply == QMessageBox.Yes

# 集成到MainWindow: 新BasePanel
# __init__.py in dag_ide/
class DagIdePanel(BasePanel):
    @property
    def name(self): return "DAG_IDE"

    @property
    def icon(self):
        temp = QWidget()
        return temp.style().standardIcon(QStyle.SP_FileDialogList)  # 或自定义

    def create_widget(self) -> QWidget:
        if not hasattr(self, '_widget'):
            self._widget = DagIdeWindow(self.bridge)  # 独立窗口, 或嵌入QWidget
        return self._widget  # 如果Tab, 需改DagIdeWindow为QWidget

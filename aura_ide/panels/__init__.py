# src/aura_ide/panels/ide_panel/__init__.py

from PySide6.QtWidgets import QMainWindow, QDockWidget, QWidget, QStyle, QToolBar, QStatusBar
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QIcon, QAction, QKeySequence

from .base_panel import BasePanel

# 导入所有IDE内部的组件
from .ide_panel.editor_widget import EditorWidget
from .ide_panel.project_explorer_widget import ProjectExplorerWidget
from .ide_panel.inspector_widget import InspectorWidget
from .ide_panel.node_palette_widget import NodePaletteWidget
from .ide_panel.log_viewer_widget import LogViewerWidget


class IDEPanel(BasePanel):
    @property
    def name(self) -> str:
        return "设计中心"

    @property
    def icon(self) -> QIcon:
        temp_widget = QWidget()
        return temp_widget.style().standardIcon(QStyle.StandardPixmap.SP_DesktopIcon)

    def create_widget(self) -> QWidget:
        if hasattr(self, '_main_window'):
            return self._main_window

        self._main_window = QMainWindow()
        self._main_window.setDockNestingEnabled(True)
        self._main_window.setWindowFlags(Qt.Widget)  # 移除边框

        # 1. 创建所有内部组件
        self.editor = EditorWidget(self.bridge)
        self.project_explorer = ProjectExplorerWidget(self.bridge)
        self.inspector = InspectorWidget(self.bridge)
        self.node_palette = NodePaletteWidget(self.bridge)
        self.log_viewer = LogViewerWidget(self.bridge)

        # 2. 创建工具栏和状态栏
        self._setup_toolbar()
        self._main_window.setStatusBar(QStatusBar())

        # 3. 设置布局
        self._main_window.setCentralWidget(self.editor)
        self._setup_docks()

        # 4. 连接内部组件的信号
        self._connect_signals()

        return self._main_window

    def _setup_toolbar(self):
        toolbar = QToolBar("主工具栏")
        self._main_window.addToolBar(toolbar)

        self.start_action = QAction("▶️ 启动Core", self._main_window)
        self.stop_action = QAction("⏹️ 停止Core", self._main_window)
        self.stop_action.setEnabled(False)

        self.save_action = QAction("💾 保存", self._main_window)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.setEnabled(False)

        toolbar.addAction(self.start_action)
        toolbar.addAction(self.stop_action)
        toolbar.addSeparator()
        toolbar.addAction(self.save_action)

    def _setup_docks(self):
        pe_dock = QDockWidget("项目浏览器", self._main_window)
        pe_dock.setWidget(self.project_explorer)
        self._main_window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, pe_dock)

        pal_dock = QDockWidget("节点面板", self._main_window)
        pal_dock.setWidget(self.node_palette)
        self._main_window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, pal_dock)

        ins_dock = QDockWidget("属性检查器", self._main_window)
        ins_dock.setWidget(self.inspector)
        self._main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, ins_dock)

        log_dock = QDockWidget("日志", self._main_window)
        log_dock.setWidget(self.log_viewer)
        self._main_window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, log_dock)

    def _connect_signals(self):
        # 工具栏 -> Bridge
        self.start_action.triggered.connect(self.bridge.start_core)
        self.stop_action.triggered.connect(self.bridge.stop_core)
        self.save_action.triggered.connect(self.editor.save_current_file)

        # Bridge -> IDE Panel
        self.bridge.core_status_changed.connect(self._on_core_status_changed)

        # 内部组件间通信
        self.project_explorer.file_open_requested.connect(self.editor.open_file)
        self.editor.current_editor_changed.connect(self.inspector.set_editor_context)
        self.editor.current_editor_changed.connect(self.node_palette.set_editor_context)

        # 当编辑器中的节点被选中时，通知检查器
        self.editor.node_selection_changed.connect(self.inspector.set_selected_node)

        # 节点面板请求添加节点 -> 编辑器
        self.node_palette.add_node_requested.connect(self.editor.add_node_at_center)

    @Slot(bool)
    def _on_core_status_changed(self, is_running: bool):
        self.start_action.setEnabled(not is_running)
        self.stop_action.setEnabled(is_running)

        status_text = "Core 运行中" if is_running else "Core 已停止"
        self._main_window.statusBar().showMessage(status_text, 5000)

        if is_running:
            # Core启动后，刷新项目浏览器和节点面板
            self.project_explorer.refresh()
            actions = self.bridge.get_all_action_definitions()
            self.node_palette.populate_actions(actions)
            self.editor.set_available_actions(actions)
        else:
            self.project_explorer.clear()
            self.node_palette.clear_actions()

    def on_activate(self):
        print("IDE Panel Activated")
        # 激活时，可以检查Core状态并刷新UI
        status = self.bridge.get_master_status()
        self._on_core_status_changed(status.get("is_running", False))


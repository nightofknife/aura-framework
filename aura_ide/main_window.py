# src/aura_ide/main_window.py

from PySide6.QtWidgets import QMainWindow, QTabWidget, QApplication
from PySide6.QtGui import QIcon

from .core_integration.qt_bridge import QtBridge

# 动态导入所有顶级面板
from .panels import ide_panel, runner_panel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Aura")
        self.setWindowIcon(QIcon())  # TODO: Add an application icon
        self.resize(1600, 900)

        # 1. 初始化核心服务
        self.bridge = QtBridge()

        # 2. 创建Tab容器作为中央控件
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(False)
        self.tab_widget.setMovable(True)
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.setCentralWidget(self.tab_widget)

        # 3. 加载所有面板
        self.panels = []
        self._load_panels()

        # 4. 连接生命周期信号
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        # 初始激活第一个面板
        if self.panels:
            self.panels[0].on_activate()

    def _load_panels(self):
        """
        发现并加载所有顶级功能面板。
        未来增加新功能，只需在这里添加即可。
        """
        panel_classes = [
            # ide_panel.IDEPanel,
            runner_panel.RunnerPanel,
        ]

        for PanelClass in panel_classes:
            panel = PanelClass(self.bridge)
            widget = panel.create_widget()
            self.tab_widget.addTab(widget, panel.icon, panel.name)
            self.panels.append(panel)

    def _on_tab_changed(self, index: int):
        """
        当Tab切换时，通知所有面板它们的激活状态。
        """
        for i, panel in enumerate(self.panels):
            if i == index:
                panel.on_activate()
            else:
                panel.on_deactivate()

    def closeEvent(self, event):
        # 确保应用退出时，核心服务被正确关闭
        try:
            self.bridge.stop_core()
        except Exception as e:
            print(f"Error stopping core on close: {e}")
        super().closeEvent(event)

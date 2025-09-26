# aura_ide/main_window.py



from PySide6.QtWidgets import QMainWindow, QTabWidget, QApplication, QWidget, QVBoxLayout
from PySide6.QtGui import QIcon, QCloseEvent, QAction, QPainter, QPalette, Qt, QBrush
from .core_integration.qt_bridge import QtBridge
from aura_ide.widgets.texture_generator import TextureManager
# 动态导入所有顶级面板
from .panels import runner_panel

class MainWindow(QMainWindow):
    def __init__(self, texture_manager: TextureManager):
        super().__init__()
        self.setObjectName("AuraMainWindow")
        self.setWindowTitle("Aura")
        self.setGeometry(100, 100, 1600, 900)
        self.texture_manager = texture_manager

        # 1. 【修改】直接创建 QTabWidget 并设为中央控件
        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabWidget")
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.setCentralWidget(self.tabs)  # <-- QTabWidget 现在是核心

        # 2. 初始化核心服务
        self.bridge = QtBridge()
        # 【重要】在这里启动 bridge 的事件泵，确保 RunnerPanel 能收到事件
        self.bridge.attach_runner_event_pump()

        # 3. 加载所有面板
        self.panels = []
        self._load_panels()

        # 4. 连接生命周期信号
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # 5. 初始激活第一个面板
        if self.panels:
            self.panels[0].on_activate()

        # 6. 创建菜单栏
        self._create_menu()

        # 7. 设置默认主题 (这将应用我们的静态纹理)
        self.set_theme("dark")


    def _load_panels(self):
        """
        发现并加载所有顶级功能面板。
        """
        panel_classes = [
            runner_panel.RunnerPanel,
        ]

        for PanelClass in panel_classes:
            panel = PanelClass(self.bridge)
            widget = panel.create_widget()
            # 【修改】确保这里使用的是 self.tabs
            self.tabs.addTab(widget, panel.icon, panel.name)
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

    def closeEvent(self, event: QCloseEvent):
        """
        【修改】重写窗口关闭事件，检查未保存的更改。
        """
        # 获取当前活动的面板 widget
        current_widget = self.tab_widget.currentWidget()

        # 检查 widget 是否实现了 can_close 方法 (我们的 IDEPage 会实现)
        if hasattr(current_widget, 'can_close') and callable(getattr(current_widget, 'can_close')):
            if not current_widget.can_close():
                event.ignore()  # 如果 can_close 返回 False，则取消关闭
                return

        # 如果检查通过，则正常关闭
        try:
            print("Stopping core services...")
            self.bridge.stop_core()
            print("Core services stopped.")
        except Exception as e:
            print(f"Error stopping core on close: {e}")

        event.accept()  # 接受关闭事件

    def _create_menu(self):
        menu_bar = self.menuBar()
        theme_menu = menu_bar.addMenu("主题 (Theme)")

        dark_action = QAction("暗色主题 (Obsidian Flow)", self)
        dark_action.triggered.connect(lambda: self.set_theme("dark"))
        theme_menu.addAction(dark_action)

        light_action = QAction("亮色主题 (Linen Canvas)", self)
        light_action.triggered.connect(lambda: self.set_theme("light"))
        theme_menu.addAction(light_action)

    def set_theme(self, theme_name: str):
        """
                【修改】使用 QPalette 高效设置背景纹理。
                """
        self.setProperty("theme", theme_name)

        # 1. 获取当前窗口的调色板
        palette = self.palette()

        # 2. 根据主题从 TextureManager 获取预先生成好的 QPixmap
        if theme_name == "dark":
            pixmap = self.texture_manager.dark_texture_pixmap
        else:
            pixmap = self.texture_manager.light_texture_pixmap

        # 3. 创建一个使用该 pixmap 平铺的笔刷
        brush = QBrush(pixmap)
        palette.setBrush(QPalette.ColorRole.Window, brush)
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        # 2. 【【【核心修复】】】
        #    强制Qt重新计算并应用整个应用程序的样式表
        #    这会使QSS中所有的 [theme="dark"] 和 [theme="light"] 选择器生效

        # 首先刷新主窗口自身
        self.style().unpolish(self)
        self.style().polish(self)

        # 然后递归刷新所有子控件
        for child in self.findChildren(QWidget):
            child.style().unpolish(child)
            child.style().polish(child)

        # 确保事件循环处理这些更新
        QApplication.instance().processEvents()

        print(f"Theme fully applied: {theme_name}")
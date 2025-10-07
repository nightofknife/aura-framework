"""
定义 Aura IDE 的主窗口。

该模块包含了 `MainWindow` 类，它是整个IDE应用程序的用户界面入口点。
它负责：
- 创建和管理一个主选项卡控件（QTabWidget）。
- 初始化核心服务与UI的桥梁（`QtBridge`）。
- 动态加载所有定义在 `panels` 目录下的功能面板（如运行器面板）。
- 处理面板之间的切换事件。
- 管理窗口的生命周期事件，如关闭窗口时的资源清理。
- 创建菜单栏，并提供主题切换等功能。
"""
from PySide6.QtWidgets import QMainWindow, QTabWidget, QApplication, QWidget
from PySide6.QtGui import QCloseEvent, QAction, QPalette, QBrush
from .core_integration.qt_bridge import QtBridge
from aura_ide.widgets.texture_generator import TextureManager
from .panels import runner_panel

class MainWindow(QMainWindow):
    """
    Aura IDE 的主应用程序窗口。

    这个类作为所有UI组件的容器，管理着一个 `QTabWidget`，其中每个
    选项卡都是一个独立的功能面板（Panel）。
    """
    def __init__(self, texture_manager: TextureManager):
        """
        初始化主窗口。

        Args:
            texture_manager (TextureManager): 用于管理和提供背景纹理的实例。
        """
        super().__init__()
        self.setObjectName("AuraMainWindow")
        self.setWindowTitle("Aura")
        self.setGeometry(100, 100, 1600, 900)
        self.texture_manager = texture_manager

        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabWidget")
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.setCentralWidget(self.tabs)

        self.bridge = QtBridge()
        self.bridge.attach_runner_event_pump()

        self.panels = []
        self._load_panels()

        self.tabs.currentChanged.connect(self._on_tab_changed)

        if self.panels:
            self.panels[0].on_activate()

        self._create_menu()
        self.set_theme("dark")


    def _load_panels(self):
        """
        发现并加载所有顶级功能面板。

        此方法会实例化所有在 `panel_classes` 列表中定义的面板类，
        创建它们的UI控件，并将它们作为新的选项卡添加到主窗口中。
        """
        panel_classes = [
            runner_panel.RunnerPanel,
        ]

        for PanelClass in panel_classes:
            panel = PanelClass(self.bridge)
            widget = panel.create_widget()
            self.tabs.addTab(widget, panel.icon, panel.name)
            self.panels.append(panel)

    def _on_tab_changed(self, index: int):
        """
        当选项卡切换时，通知所有面板它们的激活状态。

        这允许面板在变为活动状态时执行特定操作（如刷新数据），
        或在变为非活动状态时暂停某些操作。

        Args:
            index (int): 新激活的选项卡的索引。
        """
        for i, panel in enumerate(self.panels):
            if i == index:
                panel.on_activate()
            else:
                panel.on_deactivate()

    def closeEvent(self, event: QCloseEvent):
        """
        重写窗口关闭事件处理函数。

        在关闭窗口前，会尝试平滑地停止核心服务。

        Args:
            event (QCloseEvent): 窗口关闭事件对象。
        """
        # (未来的实现可以向面板查询是否有未保存的更改)
        # current_widget = self.tabs.currentWidget()
        # if hasattr(current_widget, 'can_close') and not current_widget.can_close():
        #     event.ignore()
        #     return

        try:
            print("正在停止核心服务...")
            self.bridge.stop_core()
            print("核心服务已停止。")
        except Exception as e:
            print(f"关闭时停止核心服务出错: {e}")

        event.accept()

    def _create_menu(self):
        """创建主窗口的菜单栏和菜单项。"""
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
        设置并应用整个应用程序的主题。

        此方法会：
        1.  使用 `QPalette` 高效地设置窗口背景的平铺纹理。
        2.  设置一个自定义属性 `theme`，以便在 QSS 样式表中使用
            属性选择器（例如 `[theme="dark"]`）来应用不同的样式。
        3.  强制刷新整个应用程序的样式，确保所有控件都应用新主题。

        Args:
            theme_name (str): 要应用的主题名称 ('dark' 或 'light')。
        """
        self.setProperty("theme", theme_name)

        palette = self.palette()

        if theme_name == "dark":
            pixmap = self.texture_manager.dark_texture_pixmap
        else:
            pixmap = self.texture_manager.light_texture_pixmap

        brush = QBrush(pixmap)
        palette.setBrush(QPalette.ColorRole.Window, brush)
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        # 强制Qt重新计算并应用整个应用程序的样式表
        self.style().unpolish(self)
        self.style().polish(self)

        for child in self.findChildren(QWidget):
            child.style().unpolish(child)
            child.style().polish(child)

        QApplication.instance().processEvents()

        print(f"主题已完全应用: {theme_name}")
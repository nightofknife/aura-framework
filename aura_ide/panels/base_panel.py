"""
定义了所有顶级功能面板的抽象基类 `BasePanel`。

该模块提供了一个接口契约，确保所有希望被 `MainWindow` 加载为
顶级选项卡的功能模块都遵循统一的结构。通过继承 `BasePanel`，
每个功能面板都必须实现创建其UI、提供名称和图标等核心功能，
同时也获得了与后端核心服务交互的 `QtBridge` 实例。
"""
from abc import ABC, abstractmethod
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QIcon

from ..core_integration.qt_bridge import QtBridge


class BasePanel(ABC):
    """
    所有顶级功能面板的抽象基类（接口契约）。

    `MainWindow` 通过这个统一的接口来发现、加载和管理所有主要的功能面板，
    而无需关心每个面板的具体实现。这实现了UI组件的解耦和可插拔性。
    """

    def __init__(self, bridge: QtBridge):
        """
        初始化面板的基类。

        每个面板在实例化时都会被注入一个 `QtBridge` 的实例，
        作为其与后端核心服务进行通信的唯一通道。

        Args:
            bridge (QtBridge): 连接前端与后端的核心桥接器实例。
        """
        self.bridge = bridge

    @property
    @abstractmethod
    def name(self) -> str:
        """
        返回面板的显示名称。

        这个名称将用作 `QTabWidget` 中该面板选项卡的标签文本。

        Returns:
            str: 面板的显示名称。
        """
        pass

    @property
    @abstractmethod
    def icon(self) -> QIcon:
        """
        返回面板的图标。

        这个图标将显示在 `QTabWidget` 中该面板选项卡的标签上。

        Returns:
            QIcon: 面板的图标对象。
        """
        pass

    @abstractmethod
    def create_widget(self) -> QWidget:
        """
        创建并返回该面板的主UI控件（Widget）。

        这是面板的核心方法，它负责构建该面板的所有UI元素和内部逻辑，
        并将它们封装在一个 `QWidget` 中返回给主窗口进行显示。

        Returns:
            QWidget: 代表整个面板UI的Qt控件。
        """
        pass

    def on_activate(self):
        """
        当用户切换到此面板时由主窗口调用。

        子类可以重写此方法来执行当面板变为活动状态时所需的操作，
        例如刷新数据、启动定时器等。这是一个可选的生命周期钩子。
        """
        pass

    def on_deactivate(self):
        """
        当用户从此面板切换走时由主窗口调用。

        子类可以重写此方法来执行当面板变为非活动状态时所需的操作，
        例如停止轮询、释放资源等。这是一个可选的生命周期钩子。
        """
        pass

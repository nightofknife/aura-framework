# src/aura_ide/panels/base_panel.py

from abc import ABC, abstractmethod
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QIcon


class BasePanel(ABC):
    """
    所有顶级功能面板的基类（契约）。
    MainWindow只通过这个接口与面板交互。
    """

    def __init__(self, bridge):
        """
        每个面板在实例化时都会被注入核心的QtBridge服务。
        """
        self.bridge = bridge

    @property
    @abstractmethod
    def name(self) -> str:
        """返回面板的显示名称，用于Tab标签。"""
        pass

    @property
    @abstractmethod
    def icon(self) -> QIcon:
        """返回面板的图标，用于Tab标签。"""
        pass

    @abstractmethod
    def create_widget(self) -> QWidget:
        """
        创建并返回该面板的主UI控件。
        这是面板的核心，它包含了该功能的所有UI和逻辑。
        """
        pass

    def on_activate(self):
        """当用户切换到此面板时调用（可选实现）。"""
        pass

    def on_deactivate(self):
        """当用户从此面板切换走时调用（可选实现）。"""
        pass

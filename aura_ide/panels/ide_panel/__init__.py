# src/aura_ide/panels/ide_panel/__init__.py

from PySide6.QtWidgets import QStyle, QWidget
from PySide6.QtGui import QIcon

from aura_ide.panels.base_panel import BasePanel
from .ide_page import IDEPage


class IDEPanel(BasePanel):
    """
    一个集成的开发环境面板，用于查看、编辑和管理Aura任务。
    """
    @property
    def name(self) -> str:
        return "开发中心"

    @property
    def icon(self) -> QIcon:
        # 使用一个适合IDE的标准图标
        temp_widget = QWidget()
        return temp_widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)

    def create_widget(self) -> QWidget:
        # IDE面板的主体就是IDEPage
        if not hasattr(self, '_widget'):
            self._widget = IDEPage(self.bridge)
        return self._widget

    def on_activate(self):
        # 当切换到此面板时，自动刷新工作区文件列表
        if hasattr(self, '_widget') and hasattr(self._widget, 'reload_workspace'):
            print("IDE Panel Activated: Refreshing workspace...")
            self._widget.reload_workspace()

# src/aura_ide/panels/runner_panel/__init__.py

from PySide6.QtWidgets import QStyle, QWidget
from PySide6.QtGui import QIcon

from aura_ide.panels.base_panel import BasePanel
from .runner_page import RunnerPage


class RunnerPanel(BasePanel):
    @property
    def name(self) -> str:
        return "运行中心"

    @property
    def icon(self) -> QIcon:
        # 使用Qt内置的标准图标
        # 需要一个临时的QWidget来获取style
        temp_widget = QWidget()
        return temp_widget.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)

    def create_widget(self) -> QWidget:
        # Runner面板的主体就是RunnerPage
        if not hasattr(self, '_widget'):
            self._widget = RunnerPage(self.bridge)
        return self._widget

    def on_activate(self):
        # 当切换到此面板时，可以自动刷新任务列表
        if hasattr(self, '_widget') and hasattr(self._widget.picker, '_reload_plans'):
            print("Runner Panel Activated: Refreshing plans...")
            self._widget.picker._reload_plans()


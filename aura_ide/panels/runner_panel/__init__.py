# aura_ide/panels/runner_panel/__init__.py (修改版)

from PySide6.QtWidgets import QStyle, QWidget
from PySide6.QtGui import QIcon

from aura_ide.panels.base_panel import BasePanel
from .runner_widget import RunnerWidget # <-- 导入新的主控件

class RunnerPanel(BasePanel):
    @property
    def name(self) -> str:
        return "运行中心"

    @property
    def icon(self) -> QIcon:
        temp_widget = QWidget()
        return temp_widget.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)

    def create_widget(self) -> QWidget:
        # Runner面板的主体现在是 RunnerWidget
        if not hasattr(self, '_widget'):
            self._widget = RunnerWidget(self.bridge) # <-- 实例化新的主控件
        return self._widget

    def on_activate(self):
        # 当切换到此面板时，可以自动刷新任务列表
        if hasattr(self, '_widget'):
             self._widget.refresh_data()

"""
定义并导出“运行中心”面板。

该 `__init__.py` 文件作为 `runner_panel` 包的入口点，
定义了 `RunnerPanel` 类。这个类遵循 `BasePanel` 接口，
负责创建和管理“运行中心”功能模块的主用户界面。
"""
from PySide6.QtWidgets import QStyle, QWidget
from PySide6.QtGui import QIcon

from aura_ide.panels.base_panel import BasePanel
from .runner_widget import RunnerWidget

class RunnerPanel(BasePanel):
    """
    “运行中心”面板的主类。

    它实现了 `BasePanel` 接口，负责创建 `RunnerWidget` 作为其主UI，
    并定义了面板的名称和图标。
    """
    @property
    def name(self) -> str:
        """
        返回面板的显示名称。

        Returns:
            str: 返回“运行中心”。
        """
        return "运行中心"

    @property
    def icon(self) -> QIcon:
        """
        返回面板的图标。

        使用 Qt 的标准“播放”图标。

        Returns:
            QIcon: 播放图标。
        """
        temp_widget = QWidget()
        return temp_widget.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)

    def create_widget(self) -> QWidget:
        """
        创建并返回此面板的主控件。

        此面板的UI和主要逻辑由 `RunnerWidget` 实现。

        Returns:
            QWidget: `RunnerWidget` 的实例。
        """
        if not hasattr(self, '_widget'):
            self._widget = RunnerWidget(self.bridge)
        return self._widget

    def on_activate(self):
        """
        当此面板被激活（即用户切换到此选项卡）时调用的钩子。

        它会触发主控件 `RunnerWidget` 的 `refresh_data` 方法，
        以确保显示的数据是最新的。
        """
        if hasattr(self, '_widget'):
             self._widget.refresh_data()

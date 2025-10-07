"""
定义了“运行中心”中的监控控件 `MonitoringWidget`。

该模块的核心是 `MonitoringWidget`，它是一个包含多个选项卡的控件，
用于实时展示后端服务的运行状态，主要包括：
- **活动任务**: 显示当前正在执行或最近一次执行的任务的详细步骤和状态。
  （当前实现为占位符，未来应集成 `TaskRunDetailPanel`）。
- **实时日志**: 显示从后端 `logger` 服务推送过来的所有日志信息。
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QPlainTextEdit, QLabel
from PySide6.QtCore import Slot
from typing import Dict, Any, Optional

from ....core_integration.qt_bridge import QtBridge


class MonitoringWidget(QWidget):
    """
    一个用于显示任务执行详情和实时日志的UI监控控件。
    """
    def __init__(self, bridge: QtBridge, parent: Optional[QWidget] = None):
        """
        初始化监控控件。

        Args:
            bridge (QtBridge): 连接后端的桥接器实例。
            parent (Optional[QWidget]): 父控件。
        """
        super().__init__(parent)
        self.bridge = bridge

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # 标签页1: 活动任务
        self.active_task_panel = QWidget()
        self.active_task_panel_layout = QVBoxLayout(self.active_task_panel)
        self.active_task_label = QLabel("在中栏选择一个任务以查看详情，或在运行时自动显示。")
        self.active_task_panel_layout.addWidget(self.active_task_label)

        # 标签页2: 实时日志
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("LogView")

        self.tabs.addTab(self.active_task_panel, "活动任务")
        self.tabs.addTab(self.log_view, "实时日志")

        layout.addWidget(self.tabs)

    @Slot(dict)
    def display_task_details(self, task_info: Dict[str, Any]):
        """
        一个Qt槽函数，用于在“活动任务”面板上显示所选任务的基本信息。

        Args:
            task_info (Dict[str, Any]): 包含任务信息的字典。
        """
        # 这是一个简化的实现，实际应该加载任务的详细定义
        title = task_info.get('meta', {}).get('title', task_info['full_task_id'])
        self.active_task_label.setText(f"选中任务: {title}\n\n(此处应显示任务的详细步骤树)")

    @Slot(dict)
    def handle_event(self, event: Dict[str, Any]):
        """
        一个通用的Qt槽函数，用于接收和处理来自后端的各种事件。

        当前实现是将事件信息打印到日志视图中，未来可以扩展以更新
        “活动任务”面板的UI。

        Args:
            event (Dict[str, Any]): 从 `QtBridge` 发射的事件字典。
        """
        event_name = event.get("name", "")
        self.log_view.appendPlainText(f"[EVENT] {event_name}: {event.get('payload', {})}")

    @Slot(dict)
    def handle_raw_log(self, event: Dict[str, Any]):
        """
        一个专门处理日志事件的Qt槽函数。

        它会解析 `log.emitted` 事件的负载，提取日志级别和消息，
        并将其格式化后追加到“实时日志”视图中。

        Args:
            event (Dict[str, Any]): `log.emitted` 事件字典。
        """
        if (event or {}).get("name") != "log.emitted": return
        rec = (event.get("payload") or {}).get("log_record") or {}
        message = rec.get("message", "")
        level = rec.get("levelname", "INFO")
        self.log_view.appendPlainText(f"[{level}] {message}")

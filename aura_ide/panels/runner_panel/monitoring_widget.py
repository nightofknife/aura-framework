# aura_ide/panels/runner_panel/monitoring_widget.py (新建文件)

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QPlainTextEdit, QLabel
from PySide6.QtCore import Slot


class MonitoringWidget(QWidget):
    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # 标签页1: 活动任务
        self.active_task_panel = QWidget()  # 这里应该放一个重构后的 TaskRunDetailPanel
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
    def display_task_details(self, task_info):
        # 这是一个简化的实现，实际应该加载任务的详细定义
        title = task_info.get('meta', {}).get('title', task_info['full_task_id'])
        self.active_task_label.setText(f"选中任务: {title}\n\n(此处应显示任务的详细步骤树)")

    @Slot(dict)
    def handle_event(self, event):
        # 在这里更新 "活动任务" 面板的UI
        event_name = event.get("name", "")
        # ... (之前 TaskRunDetailPanel 中的 update_for_event 逻辑)
        self.log_view.appendPlainText(f"[EVENT] {event_name}: {event.get('payload', {})}")

    @Slot(dict)
    def handle_raw_log(self, event):
        if (event or {}).get("name") != "log.emitted": return
        rec = (event.get("payload") or {}).get("log_record") or {}
        message = rec.get("message", "")
        level = rec.get("levelname", "INFO")
        self.log_view.appendPlainText(f"[{level}] {message}")

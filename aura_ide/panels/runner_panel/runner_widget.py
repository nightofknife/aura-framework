"""
定义了“运行中心”面板的主UI控件 `RunnerWidget`。

该模块的核心是 `RunnerWidget`，它是一个 `QWidget`，负责构建和协调
“运行中心”的经典三栏式布局：
- 左栏：任务库 (`TaskLibraryWidget`)
- 中栏：执行批次 (`ExecutionBatchWidget`)
- 右栏：监控和详情 (`MonitoringWidget`)

它使用 `QSplitter` 来允许用户自由调整各栏的宽度，并通过信号和槽机制
将这三个子控件以及与后端的 `QtBridge` 连接起来，形成一个完整的功能单元。
"""
from typing import List, Any, Dict, Optional

from PySide6.QtWidgets import QWidget, QHBoxLayout, QSplitter
from PySide6.QtCore import Qt

from .task_library_widget import TaskLibraryWidget
from .execution_batch_widget import ExecutionBatchWidget
from .monitoring_widget import MonitoringWidget
from ....core_integration.qt_bridge import QtBridge

class RunnerWidget(QWidget):
    """
    “运行中心”面板的主UI控件。

    它整合了任务库、执行批次和监控面板，构成了运行中心的核心用户界面。
    """
    def __init__(self, bridge: QtBridge, parent: Optional[QWidget] = None):
        """
        初始化 RunnerWidget。

        Args:
            bridge (QtBridge): 用于与后端核心服务通信的桥接器实例。
            parent (Optional[QWidget]): 父控件。
        """
        super().__init__(parent)
        self.bridge = bridge

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        self.task_library = TaskLibraryWidget(self.bridge)
        self.execution_batch = ExecutionBatchWidget(self.bridge)
        self.monitoring_panel = MonitoringWidget(self.bridge)

        splitter.addWidget(self.task_library)
        splitter.addWidget(self.execution_batch)
        splitter.addWidget(self.monitoring_panel)

        splitter.setSizes([300, 450, 650])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 2)

        self.task_library.task_added.connect(self.execution_batch.add_task_to_batch)
        self.execution_batch.batch_run_requested.connect(self._on_batch_run)
        self.execution_batch.item_selected.connect(self.monitoring_panel.display_task_details)
        self.bridge.runner_event_received.connect(self.monitoring_panel.handle_event)
        self.bridge.raw_event_received.connect(self.monitoring_panel.handle_raw_log)

    def _on_batch_run(self, tasks_to_run: List[Dict[str, Any]], mode: str, concurrency: int):
        """
        处理来自 `ExecutionBatchWidget` 的批量运行请求的槽函数。

        Args:
            tasks_to_run (List[Dict[str, Any]]): 要运行的任务信息列表。
            mode (str): 执行模式（例如 "serial"）。
            concurrency (int): 并发数。
        """
        print(
            f"RunnerWidget: 收到批量运行请求。模式: {mode}, 并发数: {concurrency}, 任务数: {len(tasks_to_run)}")
        # 简化示例：串行执行
        for task_item in tasks_to_run:
            print(f"  -> 正在运行任务: {task_item['plan']}/{task_item['task_name']}")
            self.bridge.run_ad_hoc(
                task_item['plan'],
                task_item['task_name'],
                task_item['params_override']
            )

    def refresh_data(self):
        """
        刷新此控件及其子控件的数据。

        当面板被激活时，此方法被调用，以确保任务库显示最新的任务列表。
        """
        self.task_library.refresh_tasks()




# aura_ide/panels/runner_panel/runner_widget.py (新建文件)

from PySide6.QtWidgets import QWidget, QHBoxLayout, QSplitter
from PySide6.QtCore import Qt

# 假设这些新文件你也会创建
from .task_library_widget import TaskLibraryWidget
from .execution_batch_widget import ExecutionBatchWidget
from .monitoring_widget import MonitoringWidget

class RunnerWidget(QWidget):
    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge

        # 1. 创建三栏布局
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        #
        # aura_ide/panels/runner_panel/runner_widget.py (新建文件 - 续)

        # 2. 实例化三栏的控件
        self.task_library = TaskLibraryWidget(self.bridge)
        self.execution_batch = ExecutionBatchWidget(self.bridge)
        self.monitoring_panel = MonitoringWidget(self.bridge)

        # 3. 将控件添加到布局中
        splitter.addWidget(self.task_library)
        splitter.addWidget(self.execution_batch)
        splitter.addWidget(self.monitoring_panel)

        # 4. 设置初始尺寸比例
        splitter.setSizes([300, 450, 650])
        splitter.setStretchFactor(0, 0)  # 左栏固定宽度
        splitter.setStretchFactor(1, 1)  # 中栏可伸缩
        splitter.setStretchFactor(2, 2)  # 右栏伸缩比例更大

        # 5. 连接信号和槽，实现三栏之间的通信
        self.task_library.task_added.connect(self.execution_batch.add_task_to_batch)
        self.execution_batch.batch_run_requested.connect(self._on_batch_run)
        self.execution_batch.item_selected.connect(self.monitoring_panel.display_task_details)

        # 将来自 bridge 的事件转发给监控面板
        self.bridge.runner_event_received.connect(self.monitoring_panel.handle_event)

        # 将来自 bridge 的日志事件也转发给监控面板的日志视图
        self.bridge.raw_event_received.connect(self.monitoring_panel.handle_raw_log)

    def _on_batch_run(self, tasks_to_run, mode, concurrency):
        """处理来自中栏的批量运行请求"""
        print(
            f"RunnerWidget: Received batch run request. Mode: {mode}, Concurrency: {concurrency}, Tasks: {len(tasks_to_run)}")
        # 在这里，你需要实现一个调度器逻辑，类似于之前 RunnerPage 中的 _dispatch_loop
        # 这个调度器会根据 mode 和 concurrency，依次或并发地通过 bridge.run_ad_hoc 调用任务
        # 为了简化，我们这里只做一个简单的串行调用示例
        for task_item in tasks_to_run:
            print(f"  -> Running task: {task_item['plan']}/{task_item['task_name']}")
            self.bridge.run_ad_hoc(
                task_item['plan'],
                task_item['task_name'],
                task_item['params_override']
            )

    def refresh_data(self):
        """当面板被激活时调用，刷新任务库"""
        self.task_library.refresh_tasks()




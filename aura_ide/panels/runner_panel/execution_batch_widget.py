# aura_ide/panels/runner_panel/execution_batch_widget.py (新建文件)

from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QPushButton, QHBoxLayout, QFrame
from PySide6.QtCore import Signal, Qt, Slot


# ... (需要导入 TaskCard 或类似的自定义控件) ...

class ExecutionBatchWidget(QWidget):
    batch_run_requested = Signal(list, str, int)  # tasks, mode, concurrency
    item_selected = Signal(dict)

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge

        layout = QVBoxLayout(self)

        # 控制栏
        control_bar = QFrame()
        control_bar.setObjectName("ControlBar")
        control_layout = QHBoxLayout(control_bar)

        self.run_button = QPushButton("▶️ 运行批次")
        self.run_button.setObjectName("runBatchButton")  # 用于QSS

        self.stop_button = QPushButton("⏹️ 全部停止")
        self.clear_button = QPushButton("🗑️ 清空批次")

        control_layout.addWidget(self.run_button)
        control_layout.addStretch()
        control_layout.addWidget(self.stop_button)
        control_layout.addWidget(self.clear_button)

        self.batch_list = QListWidget()
        self.batch_list.setObjectName("ExecutionBatchList")
        # 启用拖拽排序
        self.batch_list.setDragDropMode(QListWidget.InternalMove)

        layout.addWidget(control_bar)
        layout.addWidget(self.batch_list)

        self.run_button.clicked.connect(self._emit_run_request)
        self.clear_button.clicked.connect(self.batch_list.clear)
        self.batch_list.currentItemChanged.connect(self._on_item_selected)

    @Slot(dict)
    def add_task_to_batch(self, task_info):
        # 简化版：只显示任务标题
        title = task_info.get('meta', {}).get('title', task_info['full_task_id'])
        item = QListWidgetItem(title)
        item.setData(Qt.UserRole, task_info)
        self.batch_list.addItem(item)

    def _emit_run_request(self):
        tasks_to_run = []
        for i in range(self.batch_list.count()):
            item = self.batch_list.item(i)
            task_info = item.data(Qt.UserRole)
            # 实际应用中，这里应该包含参数覆盖等信息
            tasks_to_run.append({
                "plan": task_info['plan_name'],
                "task_name": task_info['task_name_in_plan'],
                "params_override": {}  # 待实现
            })

        # 简化：默认串行，并发为1
        self.batch_run_requested.emit(tasks_to_run, "serial", 1)

    def _on_item_selected(self, current, previous):
        if current:
            task_info = current.data(Qt.UserRole)
            self.item_selected.emit(task_info)

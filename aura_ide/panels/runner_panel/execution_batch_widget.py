"""
定义了“运行中心”中的执行批次控件。

该模块的核心是 `ExecutionBatchWidget`，它提供了一个可拖拽排序的
列表，用户可以将任务库中的任务添加到这个列表中，形成一个执行批次。
用户可以运行、停止或清空整个批次。
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QPushButton, QHBoxLayout, QFrame
from PySide6.QtCore import Signal, Qt, Slot
from typing import Dict, Any, List, Optional

from ....core_integration.qt_bridge import QtBridge

class ExecutionBatchWidget(QWidget):
    """
    一个用于管理和执行任务批次的UI控件。

    它包含一个可排序的任务列表和用于控制批次执行的按钮。
    当用户与此控件交互时，它会发射信号，通知父控件（如 `RunnerWidget`）
    执行相应的操作。

    Signals:
        batch_run_requested (list, str, int): 当用户点击“运行批次”按钮时发射。
            参数为：任务信息列表、执行模式（如 "serial"）、并发数。
        item_selected (dict): 当用户在列表中选择一个任务时发射。
            参数为所选任务的信息字典。
    """
    batch_run_requested = Signal(list, str, int)
    item_selected = Signal(dict)

    def __init__(self, bridge: QtBridge, parent: Optional[QWidget] = None):
        """
        初始化执行批次控件。

        Args:
            bridge (QtBridge): 连接后端的桥接器实例。
            parent (Optional[QWidget]): 父控件。
        """
        super().__init__(parent)
        self.bridge = bridge

        layout = QVBoxLayout(self)

        control_bar = QFrame()
        control_bar.setObjectName("ControlBar")
        control_layout = QHBoxLayout(control_bar)

        self.run_button = QPushButton("▶️ 运行批次")
        self.run_button.setObjectName("runBatchButton")

        self.stop_button = QPushButton("⏹️ 全部停止")
        self.clear_button = QPushButton("🗑️ 清空批次")

        control_layout.addWidget(self.run_button)
        control_layout.addStretch()
        control_layout.addWidget(self.stop_button)
        control_layout.addWidget(self.clear_button)

        self.batch_list = QListWidget()
        self.batch_list.setObjectName("ExecutionBatchList")
        self.batch_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)

        layout.addWidget(control_bar)
        layout.addWidget(self.batch_list)

        self.run_button.clicked.connect(self._emit_run_request)
        self.clear_button.clicked.connect(self.batch_list.clear)
        self.batch_list.currentItemChanged.connect(self._on_item_selected)

    @Slot(dict)
    def add_task_to_batch(self, task_info: Dict[str, Any]):
        """
        向批次列表中添加一个新任务。

        这是一个Qt槽函数，通常由其他控件（如 `TaskLibraryWidget`）的信号触发。

        Args:
            task_info (Dict[str, Any]): 要添加的任务的完整信息字典。
        """
        title = task_info.get('meta', {}).get('title', task_info['full_task_id'])
        item = QListWidgetItem(title)
        item.setData(Qt.ItemDataRole.UserRole, task_info)
        self.batch_list.addItem(item)

    def _emit_run_request(self):
        """
        收集列表中的所有任务并发出 `batch_run_requested` 信号。
        """
        tasks_to_run: List[Dict[str, Any]] = []
        for i in range(self.batch_list.count()):
            item = self.batch_list.item(i)
            task_info = item.data(Qt.ItemDataRole.UserRole)
            tasks_to_run.append({
                "plan": task_info['plan_name'],
                "task_name": task_info['task_name_in_plan'],
                "params_override": {}
            })

        # 简化处理：默认串行执行，并发数为1
        self.batch_run_requested.emit(tasks_to_run, "serial", 1)

    def _on_item_selected(self, current: QListWidgetItem, previous: Optional[QListWidgetItem]):
        """
        当列表中的当前选中项改变时，发出 `item_selected` 信号。

        Args:
            current (QListWidgetItem): 新选中的列表项。
            previous (Optional[QListWidgetItem]): 先前被选中的列表项。
        """
        if current:
            task_info = current.data(Qt.ItemDataRole.UserRole)
            self.item_selected.emit(task_info)

# aura_ide/panels/ide_panel/flow_panel.py

from typing import Dict, Any

from PySide6.QtCore import Signal, Slot, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QPushButton, QListWidgetItem,
    QHBoxLayout, QAbstractItemView
)


class FlowPanel(QWidget):
    node_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 0)

        self.node_list = QListWidget()
        self.node_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        layout.addWidget(self.node_list)

        button_layout = QHBoxLayout()
        self.add_button = QPushButton("(+) 添加步骤")
        self.delete_button = QPushButton("(-) 删除步骤")
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.delete_button)
        layout.addLayout(button_layout)

        # --- Connections ---
        self.node_list.currentItemChanged.connect(self._on_selection_changed)

        # TODO: Connect add/delete button signals

    def load_nodes(self, steps_data: Dict[str, Any]):
        self.node_list.clear()
        for node_id, node_data in steps_data.items():
            # 简单的显示ID，未来可以显示name
            item = QListWidgetItem(node_id)
            item.setData(Qt.ItemDataRole.UserRole, node_id)
            self.node_list.addItem(item)

    def clear_nodes(self):
        self.node_list.clear()

    @Slot(QListWidgetItem, QListWidgetItem)
    def _on_selection_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current:
            node_id = current.data(Qt.ItemDataRole.UserRole)
            self.node_selected.emit(node_id)

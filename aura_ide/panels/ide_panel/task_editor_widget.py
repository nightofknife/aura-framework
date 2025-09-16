# src/aura_ide/panels/ide_panel/task_editor_widget.py

from typing import Dict, Any, List

from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSplitter,
    QToolButton
)

from .flow_panel import FlowPanel
from .inspector_panel import InspectorPanel


class TaskEditorWidget(QWidget):
    task_changed = Signal()
    save_requested = Signal()
    action_selected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._task_data: Dict[str, Any] = {}
        self._is_dirty = False
        self._file_path_text = "未打开文件"

        # --- Actions ---
        self.save_action = QAction("保存", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.setEnabled(False)
        self.save_action.triggered.connect(self.save_requested.emit)
        self.addAction(self.save_action)

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QHBoxLayout()
        save_button = QToolButton()
        save_button.setDefaultAction(self.save_action)
        toolbar.addWidget(save_button)
        self.current_file_label = QLabel(self._file_path_text)
        self.current_file_label.setStyleSheet("color: #888;")
        toolbar.addStretch()
        toolbar.addWidget(self.current_file_label)
        layout.addLayout(toolbar)

        # Main Editor Splitter
        splitter = QSplitter(self)
        self.flow_panel = FlowPanel()
        self.inspector_panel = InspectorPanel()
        splitter.addWidget(self.flow_panel)
        splitter.addWidget(self.inspector_panel)
        splitter.setSizes([250, 450])
        layout.addWidget(splitter)

        # --- Connections ---
        self.flow_panel.node_selected.connect(self._on_node_selected)
        self.inspector_panel.node_data_changed.connect(self._on_node_data_changed)
        self.inspector_panel.action_selected.connect(self.action_selected.emit)

    def load_task(self, task_data: Dict[str, Any]):
        self._task_data = task_data

        # 假设任务文件只有一个顶层任务键
        task_key = next(iter(self._task_data), None)
        if not task_key:
            # Handle empty or invalid file
            self.flow_panel.clear_nodes()
            self.inspector_panel.clear_panel()
            return

        task_definition = self._task_data[task_key]
        steps = task_definition.get('steps', {})

        self.flow_panel.load_nodes(steps)
        self.inspector_panel.clear_panel()
        self.set_dirty(False)

    def set_action_definitions(self, definitions: List[Any]):
        self.inspector_panel.set_action_definitions(definitions)

    def get_task_data(self) -> Dict[str, Any]:
        return self._task_data

    def set_file_path(self, path_text: str):
        self._file_path_text = path_text
        self._update_label()

    def set_dirty(self, is_dirty: bool):
        if self._is_dirty == is_dirty:
            return
        self._is_dirty = is_dirty
        self.save_action.setEnabled(is_dirty)
        self._update_label()
        if is_dirty:
            self.task_changed.emit()

    def _update_label(self):
        label_text = self._file_path_text
        if self._is_dirty and not label_text.endswith(" *"):
            label_text += " *"
        elif not self._is_dirty and label_text.endswith(" *"):
            label_text = label_text[:-2]
        self.current_file_label.setText(label_text)

    @Slot(str)
    def _on_node_selected(self, node_id: str):
        task_key = next(iter(self._task_data), None)
        if not task_key: return

        node_data = self._task_data[task_key].get('steps', {}).get(node_id)
        if node_data:
            all_node_ids = list(self._task_data[task_key].get('steps', {}).keys())
            self.inspector_panel.load_node_data(node_id, node_data, all_node_ids)

    @Slot(str, dict)
    def _on_node_data_changed(self, node_id: str, new_data: Dict[str, Any]):
        task_key = next(iter(self._task_data), None)
        if not task_key: return

        if 'steps' not in self._task_data[task_key]:
            self._task_data[task_key]['steps'] = {}

        self._task_data[task_key]['steps'][node_id] = new_data
        self.set_dirty(True)

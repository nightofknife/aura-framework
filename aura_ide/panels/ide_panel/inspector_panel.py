# aura_ide/panels/ide_panel/inspector_panel.py

from typing import Dict, Any, List

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit, QFormLayout,
    QComboBox, QFrame, QCheckBox, QGroupBox
)


class InspectorPanel(QWidget):
    node_data_changed = Signal(str, dict)
    action_selected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._current_node_id: str = ""
        self._current_node_data: Dict[str, Any] = {}
        self._action_definitions: List[Any] = []
        self._action_map: Dict[str, Any] = {}

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)

        self.placeholder_label = QLabel("在左侧选择一个节点以编辑其属性")
        self.placeholder_label.setStyleSheet("color: #888;")
        self.main_layout.addWidget(self.placeholder_label)

        # The main container for the form, initially hidden
        self.form_container = QWidget()
        self.form_layout = QVBoxLayout(self.form_container)
        self.form_layout.setContentsMargins(0, 0, 0, 0)

        # --- Form Widgets ---
        # We will create these dynamically, but define them here for clarity
        self.id_edit = QLineEdit()
        self.name_edit = QLineEdit()
        self.action_combo = QComboBox()
        self.action_combo.setEditable(True)  # For searching

        # Placeholder for dynamic params
        self.params_group = QGroupBox("参数 (Params)")
        self.params_layout = QFormLayout(self.params_group)

        # Placeholder for depends_on
        self.depends_on_group = QGroupBox("依赖 (Depends On)")
        self.depends_on_layout = QVBoxLayout(self.depends_on_group)

        # Build the static part of the form
        static_form_layout = QFormLayout()
        static_form_layout.addRow("节点 ID:", self.id_edit)
        static_form_layout.addRow("名称 (name):", self.name_edit)
        static_form_layout.addRow("Action:", self.action_combo)

        self.form_layout.addLayout(static_form_layout)
        self.form_layout.addWidget(self.params_group)
        self.form_layout.addWidget(self.depends_on_group)
        self.form_layout.addStretch()

        self.main_layout.addWidget(self.form_container)
        self.form_container.hide()

        # --- Connections ---
        self.action_combo.currentTextChanged.connect(self._on_action_changed)
        self.name_edit.textChanged.connect(self._emit_changes)

    def set_action_definitions(self, definitions: List[Any]):
        self._action_definitions = definitions
        self._action_map = {d.name: d for d in definitions}
        self.action_combo.clear()
        self.action_combo.addItems(sorted(self._action_map.keys()))
        self.action_combo.setCurrentIndex(-1)

    def load_node_data(self, node_id: str, node_data: Dict[str, Any], all_node_ids: List[str]):
        self._current_node_id = node_id
        self._current_node_data = node_data.copy()  # Work on a copy

        # Update UI
        self.id_edit.setText(node_id)
        self.name_edit.setText(node_data.get('name', ''))

        # Block signals while setting data to prevent loops
        self.action_combo.blockSignals(True)
        self.action_combo.setCurrentText(node_data.get('action', ''))
        self.action_combo.blockSignals(False)

        self._update_params_ui(node_data.get('action'), node_data.get('params', {}))
        self._update_depends_on_ui(node_data.get('depends_on', []), all_node_ids)

        self.placeholder_label.hide()
        self.form_container.show()

    def clear_panel(self):
        self.form_container.hide()
        self.placeholder_label.show()
        self._current_node_id = ""
        self._current_node_data = {}

    def _update_params_ui(self, action_name: str, params_data: Dict):
        # Clear old params
        while self.params_layout.count():
            child = self.params_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not action_name or action_name not in self._action_map:
            return

        # TODO: Dynamically create param widgets based on action signature
        # For now, just show existing params as text boxes
        for key, value in params_data.items():
            edit = QLineEdit(str(value))
            self.params_layout.addRow(key, edit)
            # TODO: Connect signal to _emit_changes

    def _update_depends_on_ui(self, depends_on_data: Any, all_node_ids: List[str]):
        # Clear old checkboxes
        while self.depends_on_layout.count():
            child = self.depends_on_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # TODO: Implement AND/OR switch

        current_deps = []
        if isinstance(depends_on_data, list):
            current_deps = depends_on_data
        elif isinstance(depends_on_data, dict) and 'or' in depends_on_data:
            current_deps = depends_on_data['or']

        for other_node_id in all_node_ids:
            if other_node_id == self._current_node_id:
                continue

            checkbox = QCheckBox(other_node_id)
            if other_node_id in current_deps:
                checkbox.setChecked(True)
            self.depends_on_layout.addWidget(checkbox)
            # TODO: Connect signal to _emit_changes

    @Slot(str)
    def _on_action_changed(self, action_name: str):
        self._update_params_ui(action_name, {})  # Clear params on new action
        self._emit_changes()

        action_def = self._action_map.get(action_name)
        if action_def:
            self.action_selected.emit(action_def)

    @Slot()
    def _emit_changes(self):
        if not self._current_node_id:
            return

        # Reconstruct the node data from the UI
        new_data = {
            'name': self.name_edit.text(),
            'action': self.action_combo.currentText(),
            # TODO: Reconstruct params and depends_on
        }

        self.node_data_changed.emit(self._current_node_id, new_data)

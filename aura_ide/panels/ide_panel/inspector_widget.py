# src/aura_ide/panels/ide_panel/inspector_widget.py

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFormLayout, QLineEdit
from PySide6.QtCore import Slot


class InspectorWidget(QWidget):
    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self._current_editor = None
        self._current_node = None

        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(5, 5, 5, 5)

        self._placeholder = QLabel("Select a node to inspect its properties.")
        self.layout().addWidget(self._placeholder)

        self._form_widget = QWidget()
        self._form_layout = QFormLayout(self._form_widget)
        self.layout().addWidget(self._form_widget)
        self._form_widget.hide()

    @Slot(object)
    def set_editor_context(self, editor):
        self._current_editor = editor
        self.set_selected_node(None)  # Clear inspector when editor changes

    @Slot(object)
    def set_selected_node(self, node):
        self._current_node = node
        self._rebuild_ui()

    def _rebuild_ui(self):
        # Clear previous form
        while self._form_layout.rowCount() > 0:
            self._form_layout.removeRow(0)

        if not self._current_node:
            self._placeholder.show()
            self._form_widget.hide()
            return

        self._placeholder.hide()
        self._form_widget.show()

        try:
            # Common properties
            name_edit = QLineEdit(self._current_node.name())
            name_edit.textChanged.connect(lambda txt: self._current_node.set_name(txt))
            self._form_layout.addRow("Name:", name_edit)

            node_id_edit = QLineEdit(self._current_node.get_property('node_id') or "")
            node_id_edit.textChanged.connect(lambda txt: self._current_node.set_property('node_id', txt))
            self._form_layout.addRow("Node ID:", node_id_edit)

            # Type specific properties
            if self._current_node.type_() == 'aura.ActionNode':
                # TODO: Add action-specific properties (e.g., dropdown for action_id)
                pass

        except Exception as e:
            self.layout().addWidget(QLabel(f"Error inspecting node: {e}"))

# src/aura_ide/panels/ide_panel/node_palette_widget.py

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QListWidget, QListWidgetItem
from PySide6.QtCore import Signal, Slot


class NodePaletteWidget(QWidget):
    add_node_requested = Signal(str, dict)  # node_type, properties

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self._current_editor = None

        layout = QVBoxLayout(self)

        # Logic Gates
        self.btn_add_and = QPushButton("Add AND Gate")
        self.btn_add_or = QPushButton("Add OR Gate")
        self.btn_add_not = QPushButton("Add NOT Gate")
        layout.addWidget(self.btn_add_and)
        layout.addWidget(self.btn_add_or)
        layout.addWidget(self.btn_add_not)

        # Actions List
        self.action_list = QListWidget()
        self.action_list.setToolTip("Double-click to add an Action node")
        layout.addWidget(self.action_list)

        # Connections
        self.btn_add_and.clicked.connect(lambda: self.add_node_requested.emit('logic', {'logic_type': 'and'}))
        self.btn_add_or.clicked.connect(lambda: self.add_node_requested.emit('logic', {'logic_type': 'or'}))
        self.btn_add_not.clicked.connect(lambda: self.add_node_requested.emit('logic', {'logic_type': 'not'}))
        self.action_list.itemDoubleClicked.connect(self._on_action_double_clicked)

        self.setEnabled(False)

    @Slot(object)
    def set_editor_context(self, editor):
        self._current_editor = editor
        self.setEnabled(editor is not None)

    def populate_actions(self, actions: list):
        self.action_list.clear()
        for action_def in sorted(actions, key=lambda x: x.get('id', '')):
            item = QListWidgetItem(action_def.get('id', 'N/A'))
            item.setData(1, action_def)  # Store full definition
            self.action_list.addItem(item)

    def clear_actions(self):
        self.action_list.clear()

    def _on_action_double_clicked(self, item):
        action_def = item.data(1)
        if action_def:
            self.add_node_requested.emit('action', {'action_id': action_def.get('id')})

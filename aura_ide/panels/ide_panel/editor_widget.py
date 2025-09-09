# src/aura_ide/panels/ide_panel/editor_widget.py

from PySide6.QtWidgets import QTabWidget, QMessageBox
from PySide6.QtCore import Signal, Slot

# 假设 VisualTaskEditor 在这个路径
from ...visual_editor.editor import VisualTaskEditor


class EditorWidget(QTabWidget):
    current_editor_changed = Signal(object)  # 发送当前激活的editor实例
    node_selection_changed = Signal(object)  # 发送选中的节点

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self.setTabsClosable(True)
        self.setMovable(True)
        self.tabCloseRequested.connect(self.close_tab)
        self.currentChanged.connect(self._emit_current_editor)
        self._opened_files = {}  # (plan, path) -> tab_index
        self._available_actions = []

    def set_available_actions(self, actions: list):
        self._available_actions = actions
        # 更新所有已打开的编辑器
        for i in range(self.count()):
            editor = self.widget(i)
            if isinstance(editor, VisualTaskEditor):
                editor.set_available_actions(actions)

    @Slot(str, str)
    def open_file(self, plan_name, relative_path):
        file_key = (plan_name, relative_path)
        if file_key in self._opened_files:
            self.setCurrentIndex(self._opened_files[file_key])
            return

        try:
            content = self.bridge.read_task_file(plan_name, relative_path)

            # 目前只支持可视化编辑器
            if relative_path.endswith('.yaml'):
                editor = VisualTaskEditor()
                editor.set_available_actions(self._available_actions)
                editor.load_from_text(content)

                # 连接信号，将内部信号转发出去
                editor.graph.node_selection_changed.connect(
                    lambda sel, desel: self.node_selection_changed.emit(sel[0] if sel else None)
                )

                index = self.addTab(editor, f"{plan_name}/{relative_path}")
                self.setCurrentIndex(index)
                self._opened_files[file_key] = index
                self.setTabToolTip(index, f"Plan: {plan_name}\nPath: {relative_path}")
            else:
                # TODO: Add a simple text editor for other file types
                QMessageBox.information(self, "Unsupported File", "Only .yaml task files can be opened visually.")

        except Exception as e:
            QMessageBox.critical(self, "Error Opening File", f"Could not open {relative_path}:\n{e}")

    def close_tab(self, index):
        # TODO: Add "save changes?" dialog
        editor = self.widget(index)
        key_to_remove = None
        for key, val in self._opened_files.items():
            if val == index:
                key_to_remove = key
                break
        if key_to_remove:
            del self._opened_files[key_to_remove]

        self.removeTab(index)
        editor.deleteLater()

    def save_current_file(self):
        # TODO: Implement saving logic
        editor = self.currentWidget()
        if isinstance(editor, VisualTaskEditor):
            # 1. Get file key (plan, path)
            # 2. Get content from editor.save_to_text()
            # 3. Call self.bridge.write_file_content(plan, path, content)
            QMessageBox.information(self, "Save", "Save functionality not yet implemented.")

    def add_node_at_center(self, node_type: str, **kwargs):
        editor = self.currentWidget()
        if isinstance(editor, VisualTaskEditor):
            editor.add_node_at_center(node_type, **kwargs)

    @Slot()
    def _emit_current_editor(self):
        self.current_editor_changed.emit(self.currentWidget())

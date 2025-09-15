# src/aura_ide/panels/ide_panel/ide_page.py [V10 - Auto Params Connection]

import inspect
from pathlib import PurePath
from typing import Any, List, Optional, Tuple

from PySide6.QtCore import Qt, Slot, QPoint, QTimer
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import (
    QWidget, QSplitter, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QTreeWidget, QTreeWidgetItem, QGroupBox, QTabWidget,
    QPushButton, QMessageBox, QMenu, QInputDialog, QStyle, QListWidget, QListWidgetItem
)

from .editor_widget import EditorWidget
from .completion_provider import CompletionProvider
from .linter import Linter, LintingError


class IDEPage(QWidget):
    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self._current_file_path: Optional[Tuple[str, str]] = None
        self._is_dirty = False

        self._load_icons()

        main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        workspace_explorer = self._create_workspace_explorer()
        self.editor_widget = EditorWidget()
        assistant_panel = self._create_assistant_panel()

        main_splitter.addWidget(workspace_explorer)
        main_splitter.addWidget(self.editor_widget)
        main_splitter.addWidget(assistant_panel)

        outer_layout = QVBoxLayout(self)
        outer_layout.addWidget(main_splitter)
        main_splitter.setSizes([250, 600, 350])

        self.completion_provider = CompletionProvider(self.editor_widget, self)
        self.linter = Linter()

        self.lint_timer = QTimer(self)
        self.lint_timer.setSingleShot(True)
        self.lint_timer.setInterval(500)
        self.lint_timer.timeout.connect(self._trigger_linting)

        # --- 连接信号 ---
        self.workspace_tree.itemDoubleClicked.connect(self._on_file_double_clicked)
        self.workspace_tree.currentItemChanged.connect(self._on_workspace_selection_changed)
        self.reload_button.clicked.connect(self.reload_workspace)

        self.editor_widget.saveRequested.connect(self.save_current_file)
        self.editor_widget.textChanged.connect(self._on_editor_text_changed)

        self.editor_widget.cursorPositionChanged.connect(self.completion_provider.on_cursor_moved)
        self.completion_provider.actionContextFound.connect(self._update_action_doc_view)
        self.completion_provider.noContextFound.connect(self.action_doc_view.clear)

        self.problems_list.itemClicked.connect(self._on_problem_clicked)

        # 【新增】将编辑器的Enter信号连接到补全提供者的新槽
        self.editor_widget.editor.enterPressedOnLine.connect(self.completion_provider.on_line_completed)

        self.reload_workspace()

    def _load_icons(self):
        style = self.style()
        self.icons = {"plan": style.standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon),
                      "directory": style.standardIcon(QStyle.StandardPixmap.SP_DirIcon),
                      "file": style.standardIcon(QStyle.StandardPixmap.SP_FileIcon),
                      "yaml": style.standardIcon(QStyle.StandardPixmap.SP_FileIcon),
                      "image": style.standardIcon(QStyle.StandardPixmap.SP_FileIcon),
                      "error": style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical), }

    def _create_workspace_explorer(self) -> QWidget:
        container = QGroupBox("工作区")
        layout = QVBoxLayout(container)
        toolbar = QHBoxLayout()
        self.reload_button = QPushButton("刷新")
        toolbar.addWidget(self.reload_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.workspace_tree = QTreeWidget()
        self.workspace_tree.setHeaderLabels(["方案与文件"])
        self.workspace_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.workspace_tree.customContextMenuRequested.connect(self._show_workspace_context_menu)
        layout.addWidget(self.workspace_tree)
        return container

    def _create_assistant_panel(self) -> QWidget:
        self.assistant_tabs = QTabWidget()
        self.action_doc_view = QPlainTextEdit()
        self.action_doc_view.setReadOnly(True)
        self.assistant_tabs.addTab(self.action_doc_view, "Action文档")
        self.image_preview_label = QLabel("在工作区选择图片以预览")
        self.image_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.assistant_tabs.addTab(self.image_preview_label, "图片预览")
        self.problems_list = QListWidget()
        self.assistant_tabs.addTab(self.problems_list, "问题 (0)")
        return self.assistant_tabs

    def _get_icon_for_path(self, path: str, is_dir: bool) -> QIcon:
        if is_dir: return self.icons["directory"]
        ext = path.split('.')[-1].lower()
        if ext in ['yml', 'yaml']: return self.icons["yaml"]
        if ext in ['png', 'jpg', 'jpeg', 'bmp', 'gif']: return self.icons["image"]
        return self.icons["file"]

    def _populate_workspace_tree(self, parent_item, dir_dict):
        for name, content in sorted(dir_dict.items()):
            is_dir = isinstance(content, dict)
            child_item = QTreeWidgetItem([name])
            parent_path_data = parent_item.data(0, Qt.ItemDataRole.UserRole)
            parent_path = ""
            if isinstance(parent_path_data, str): parent_path = parent_path_data
            relative_path = str(PurePath(parent_path) / name)
            icon = self._get_icon_for_path(relative_path, is_dir)
            child_item.setIcon(0, icon)
            child_item.setData(0, Qt.ItemDataRole.UserRole, relative_path)
            parent_item.addChild(child_item)
            if is_dir: self._populate_workspace_tree(child_item, content)

    @Slot()
    def reload_workspace(self):
        action_definitions = self.bridge.get_all_action_definitions()
        self.completion_provider.update_action_definitions(action_definitions)
        self.linter.update_action_definitions(action_definitions)
        self.workspace_tree.clear()
        try:
            plans = self.bridge.list_plans()
            for plan_name in plans:
                plan_node = QTreeWidgetItem([plan_name])
                plan_node.setIcon(0, self.icons["plan"])
                plan_node.setData(0, Qt.ItemDataRole.UserRole, {"type": "plan", "name": plan_name})
                self.workspace_tree.addTopLevelItem(plan_node)
                file_tree = self.bridge.get_plan_files(plan_name)
                root_item = QTreeWidgetItem()
                root_item.setData(0, Qt.ItemDataRole.UserRole, "")
                self._populate_workspace_tree(root_item, file_tree)
                for i in range(root_item.childCount()): plan_node.addChild(root_item.takeChild(0))
        except Exception as e:
            QMessageBox.critical(self, "加载工作区失败", f"无法加载方案列表：{e}")

    @Slot(object)
    def _update_action_doc_view(self, action_def: Any):
        if not action_def: self.action_doc_view.clear(); return
        doc = action_def.docstring or "无文档。"
        params = action_def.signature.parameters.values()
        param_lines = [f"- {p.name} ({p.annotation.__name__ if p.annotation != inspect.Parameter.empty else 'any'})" for
                       p in params if p.name not in ['self', 'cls', 'context']]
        param_str = "\n\n参数:\n" + "\n".join(param_lines)
        self.action_doc_view.setPlainText(doc + param_str)

    def _get_item_plan_and_path(self, item: QTreeWidgetItem) -> Optional[Tuple[str, str, str]]:
        if not item: return None
        plan_item = item
        while plan_item and plan_item.parent(): plan_item = plan_item.parent()
        plan_data = plan_item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(plan_data, dict) or plan_data.get("type") != "plan": return None
        plan_name = plan_data["name"]
        relative_path_data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(relative_path_data, dict):
            relative_path, item_type = "", "plan"
        elif isinstance(relative_path_data, str):
            relative_path, item_type = relative_path_data, "directory" if item.childCount() > 0 else "file"
        else:
            return None
        return plan_name, relative_path, item_type

    def can_close(self) -> bool:
        if not self._is_dirty: return True
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("未保存的更改")
        msg_box.setText(f"文件 '{self._current_file_path[1]}' 有未保存的更改。")
        msg_box.setInformativeText("您想在关闭前保存更改吗？")
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        msg_box.setDefaultButton(QMessageBox.StandardButton.Save)
        ret = msg_box.exec()
        if ret == QMessageBox.StandardButton.Save: self.save_current_file(); return not self._is_dirty
        return ret == QMessageBox.StandardButton.Discard

    @Slot(QTreeWidgetItem, int)
    def _on_file_double_clicked(self, item: QTreeWidgetItem, column: int):
        info = self._get_item_plan_and_path(item)
        if not info or info[2] != 'file': return
        if not self.can_close(): return
        plan_name, relative_path, _ = info
        try:
            content = self.bridge.read_task_file(plan_name, relative_path)
            self.editor_widget.set_content(content)
            self._current_file_path = (plan_name, relative_path)
            self.editor_widget.set_file_path(f"{plan_name}/{relative_path}")
            self._set_dirty(False)
            self._trigger_linting()
        except Exception as e:
            QMessageBox.critical(self, "打开文件失败", f"无法读取文件 '{relative_path}':\n{e}")

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _on_workspace_selection_changed(self, current: QTreeWidgetItem, previous: QTreeWidgetItem):
        if not current: self.image_preview_label.setText("在工作区选择图片以预览"); self.image_preview_label.setPixmap(
            QPixmap()); return
        info = self._get_item_plan_and_path(current)
        if not info: return
        plan_name, relative_path, item_type = info
        self.image_preview_label.setText("在工作区选择图片以预览")
        self.image_preview_label.setPixmap(QPixmap())
        if item_type == 'file' and relative_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
            try:
                image_bytes = self.bridge.read_file_bytes(plan_name, relative_path)
                pixmap = QPixmap()
                pixmap.loadFromData(image_bytes)
                self.image_preview_label.setPixmap(
                    pixmap.scaled(self.image_preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation))
            except Exception as e:
                self.image_preview_label.setText(f"无法加载图片:\n{e}")

    @Slot()
    def _on_editor_text_changed(self):
        self._set_dirty(True)
        if self._current_file_path: self.lint_timer.start()

    def _set_dirty(self, is_dirty: bool):
        if self._is_dirty == is_dirty: return
        self._is_dirty = is_dirty
        self.editor_widget.set_dirty(is_dirty)

    @Slot()
    def save_current_file(self):
        if not self._current_file_path or not self._is_dirty: return
        plan_name, relative_path = self._current_file_path
        content = self.editor_widget.get_content()
        try:
            self.bridge.save_task_file(plan_name, relative_path, content)
            self._set_dirty(False)
            print(f"File saved: {plan_name}/{relative_path}")
        except Exception as e:
            QMessageBox.critical(self, "保存文件失败", f"无法写入文件 '{relative_path}':\n{e}")

    @Slot()
    def _show_workspace_context_menu(self, position):
        item = self.workspace_tree.itemAt(position)
        if not item: return
        info = self._get_item_plan_and_path(item)
        if not info: return
        plan_name, relative_path, item_type = info
        menu = QMenu()
        if item_type in ["plan", "directory"]: menu.addAction("新建任务文件...",
                                                              lambda: self._handle_new_file(plan_name,
                                                                                            relative_path)); menu.addAction(
            "新建目录...", lambda: self._handle_new_directory(plan_name, relative_path))
        if item_type in ["file", "directory"]: menu.addSeparator(); menu.addAction("重命名...",
                                                                                   lambda: self._handle_rename(
                                                                                       plan_name, relative_path))
        if item_type != "plan": menu.addAction("删除...", lambda: self._handle_delete(plan_name, relative_path))
        if menu.actions(): menu.exec(self.workspace_tree.mapToGlobal(position))

    def _handle_new_file(self, plan_name, dir_path):
        text, ok = QInputDialog.getText(self, "新建任务文件", "文件名 (例如: my_task.yaml):")
        if ok and text:
            if not text.endswith((".yaml", ".yml")): text += ".yaml"
            new_path = str(PurePath(dir_path) / text)
            try:
                self.bridge.create_file(plan_name, new_path,
                                        "# Your task definition here\n\nnew_task:\n  name: New Task\n  steps:\n    - action: core/print\n      params:\n        message: 'Hello from new task!'\n"); self.reload_workspace()
            except Exception as e:
                QMessageBox.critical(self, "创建失败", str(e))

    def _handle_new_directory(self, plan_name, dir_path):
        text, ok = QInputDialog.getText(self, "新建目录", "目录名:")
        if ok and text:
            new_path = str(PurePath(dir_path) / text)
            try:
                self.bridge.create_directory(plan_name, new_path); self.reload_workspace()
            except Exception as e:
                QMessageBox.critical(self, "创建失败", str(e))

    def _handle_rename(self, plan_name, old_path):
        old_name = PurePath(old_path).name
        new_name, ok = QInputDialog.getText(self, "重命名", "新名称:", text=old_name)
        if ok and new_name and new_name != old_name:
            parent_path = str(PurePath(old_path).parent)
            new_path = str(PurePath(parent_path) / new_name)
            try:
                self.bridge.rename_path(plan_name, old_path, new_path); self.reload_workspace()
            except Exception as e:
                QMessageBox.critical(self, "重命名失败", str(e))

    def _handle_delete(self, plan_name, path):
        reply = QMessageBox.question(self, "确认删除", f"确定要永久删除 '{path}' 吗？\n此操作无法撤销。",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.bridge.delete_path(plan_name, path); self.reload_workspace()
            except Exception as e:
                QMessageBox.critical(self, "删除失败", str(e))

    @Slot()
    def _trigger_linting(self):
        if not self._current_file_path: return
        content = self.editor_widget.get_content()
        errors = self.linter.lint(content)
        self.editor_widget.show_linting_errors(errors)
        self._update_problems_panel(errors)

    def _update_problems_panel(self, errors: List[LintingError]):
        self.problems_list.clear()
        for error in errors:
            item = QListWidgetItem(f"[{error.line_number}] {error.message}")
            item.setIcon(self.icons["error"])
            item.setData(Qt.ItemDataRole.UserRole, error)
            self.problems_list.addItem(item)
        self.assistant_tabs.setTabText(2, f"问题 ({len(errors)})")

    @Slot(QListWidgetItem)
    def _on_problem_clicked(self, item: QListWidgetItem):
        error: LintingError = item.data(Qt.ItemDataRole.UserRole)
        if error: self.editor_widget.go_to_line(error.line_number)

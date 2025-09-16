# src/aura_ide/panels/ide_panel/ide_page.py [REFACTORED FOR NODE EDITOR]

import io
from pathlib import PurePath
from typing import Any, List, Optional, Tuple, Dict

from PySide6.QtCore import Qt, Slot, QPoint
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QWidget, QSplitter, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QTreeWidget, QTreeWidgetItem, QGroupBox, QTabWidget,
    QPushButton, QMessageBox, QMenu, QInputDialog, QStyle, QListWidget, QListWidgetItem
)
from ruamel.yaml import YAML

# 【新增】导入新的编辑器组件
from .task_editor_widget import TaskEditorWidget


class IDEPage(QWidget):
    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self._current_file_path: Optional[Tuple[str, str]] = None
        self._is_dirty = False
        self.yaml = YAML()
        self.yaml.preserve_quotes = True

        self._load_icons()

        main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        workspace_explorer = self._create_workspace_explorer()

        # 【修改】用新的 TaskEditorWidget 替换旧的 EditorWidget
        self.task_editor_widget = TaskEditorWidget()

        assistant_panel = self._create_assistant_panel()

        main_splitter.addWidget(workspace_explorer)
        main_splitter.addWidget(self.task_editor_widget)
        main_splitter.addWidget(assistant_panel)

        outer_layout = QVBoxLayout(self)
        outer_layout.addWidget(main_splitter)
        main_splitter.setSizes([250, 700, 250])

        # 【移除】旧的 CompletionProvider 和 Linter

        # --- 连接信号 ---
        self.workspace_tree.itemDoubleClicked.connect(self._on_file_double_clicked)
        self.workspace_tree.currentItemChanged.connect(self._on_workspace_selection_changed)
        self.reload_button.clicked.connect(self.reload_workspace)

        # 【修改】连接新编辑器的信号
        self.task_editor_widget.task_changed.connect(self._on_editor_content_changed)
        self.task_editor_widget.save_requested.connect(self.save_current_file)
        self.task_editor_widget.action_selected.connect(self._update_action_doc_view)

        # 【移除】旧的信号连接

        self.problems_list.itemClicked.connect(self._on_problem_clicked)

        self.reload_workspace()

    def _load_icons(self):
        style = self.style()
        self.icons = {
            "plan": style.standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon),
            "directory": style.standardIcon(QStyle.StandardPixmap.SP_DirIcon),
            "file": style.standardIcon(QStyle.StandardPixmap.SP_FileIcon),
            "yaml": style.standardIcon(QStyle.StandardPixmap.SP_FileIcon),
            "image": style.standardIcon(QStyle.StandardPixmap.SP_FileIcon),
            "error": style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical),
        }

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

        # 问题面板暂时保留，但可能不再需要
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
        # 【修改】加载Action定义并传递给新的编辑器
        action_definitions = self.bridge.get_all_action_definitions()
        self.task_editor_widget.set_action_definitions(action_definitions)

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
                for i in range(root_item.childCount()):
                    plan_node.addChild(root_item.takeChild(0))
        except Exception as e:
            QMessageBox.critical(self, "加载工作区失败", f"无法加载方案列表：{e}")

    @Slot(object)
    def _update_action_doc_view(self, action_def: Any):
        if not action_def:
            self.action_doc_view.clear()
            return

        doc = getattr(action_def, 'docstring', "无文档。") or "无文档。"

        param_lines = []
        if hasattr(action_def, 'signature') and hasattr(action_def.signature, 'parameters'):
            params = action_def.signature.parameters.values()
            param_lines = [
                f"- {p.name} ({p.annotation.__name__ if hasattr(p.annotation, '__name__') else 'any'})"
                for p in params if p.name not in ['self', 'cls', 'context']
            ]

        param_str = "\n\n参数:\n" + "\n".join(param_lines) if param_lines else ""
        self.action_doc_view.setPlainText(doc + param_str)

    def _get_item_plan_and_path(self, item: QTreeWidgetItem) -> Optional[Tuple[str, str, str]]:
        if not item: return None
        plan_item = item
        while plan_item and plan_item.parent():
            plan_item = plan_item.parent()
        plan_data = plan_item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(plan_data, dict) or plan_data.get("type") != "plan":
            return None
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
        if not self._is_dirty:
            return True

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("未保存的更改")
        msg_box.setText(f"文件 '{self._current_file_path[1]}' 有未保存的更改。")
        msg_box.setInformativeText("您想在关闭前保存更改吗？")
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        msg_box.setDefaultButton(QMessageBox.StandardButton.Save)

        ret = msg_box.exec()
        if ret == QMessageBox.StandardButton.Save:
            self.save_current_file()
            return not self._is_dirty
        return ret == QMessageBox.StandardButton.Discard

    @Slot(QTreeWidgetItem, int)
    def _on_file_double_clicked(self, item: QTreeWidgetItem, column: int):
        info = self._get_item_plan_and_path(item)
        if not info or info[2] != 'file' or not info[1].endswith(('.yaml', '.yml')):
            return

        if not self.can_close():
            return

        plan_name, relative_path, _ = info
        try:
            content_str = self.bridge.read_task_file(plan_name, relative_path)

            # 【修改】解析YAML并加载到新编辑器
            task_data = self.yaml.load(content_str)
            if not isinstance(task_data, dict):
                raise ValueError("YAML文件内容不是一个有效的任务（顶层必须是字典）。")

            self.task_editor_widget.load_task(task_data)

            self._current_file_path = (plan_name, relative_path)
            self.task_editor_widget.set_file_path(f"{plan_name}/{relative_path}")
            self._set_dirty(False)

            # 【移除】不再需要Linter
            # self._trigger_linting()
            self.problems_list.clear()
            self.assistant_tabs.setTabText(2, "问题 (0)")

        except Exception as e:
            QMessageBox.critical(self, "打开文件失败", f"无法读取或解析文件 '{relative_path}':\n{e}")

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _on_workspace_selection_changed(self, current: QTreeWidgetItem, previous: QTreeWidgetItem):
        if not current:
            self.image_preview_label.setText("在工作区选择图片以预览")
            self.image_preview_label.setPixmap(QPixmap())
            return

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
    def _on_editor_content_changed(self):
        self._set_dirty(True)

    def _set_dirty(self, is_dirty: bool):
        if self._is_dirty == is_dirty:
            return
        self._is_dirty = is_dirty
        self.task_editor_widget.set_dirty(is_dirty)

    @Slot()
    def save_current_file(self):
        if not self._current_file_path or not self._is_dirty:
            return

        plan_name, relative_path = self._current_file_path

        # 【修改】从新编辑器获取数据模型并序列化
        task_data = self.task_editor_widget.get_task_data()

        string_stream = io.StringIO()
        self.yaml.dump(task_data, string_stream)
        content = string_stream.getvalue()

        try:
            self.bridge.save_task_file(plan_name, relative_path, content)
            self._set_dirty(False)
            print(f"File saved: {plan_name}/{relative_path}")
        except Exception as e:
            QMessageBox.critical(self, "保存文件失败", f"无法写入文件 '{relative_path}':\n{e}")

    @Slot()
    def _show_workspace_context_menu(self, position):
        # ... (此方法无变化) ...
        item = self.workspace_tree.itemAt(position)
        if not item: return
        info = self._get_item_plan_and_path(item)
        if not info: return
        plan_name, relative_path, item_type = info
        menu = QMenu()
        if item_type in ["plan", "directory"]:
            menu.addAction("新建任务文件...", lambda: self._handle_new_file(plan_name, relative_path))
            menu.addAction("新建目录...", lambda: self._handle_new_directory(plan_name, relative_path))
        if item_type in ["file", "directory"]:
            menu.addSeparator()
            menu.addAction("重命名...", lambda: self._handle_rename(plan_name, relative_path))
        if item_type != "plan":
            menu.addAction("删除...", lambda: self._handle_delete(plan_name, relative_path))
        if menu.actions():
            menu.exec(self.workspace_tree.mapToGlobal(position))

    def _handle_new_file(self, plan_name, dir_path):
        # ... (此方法无变化) ...
        text, ok = QInputDialog.getText(self, "新建任务文件", "文件名 (例如: my_task.yaml):")
        if ok and text:
            if not text.endswith((".yaml", ".yml")): text += ".yaml"
            new_path = str(PurePath(dir_path) / text)
            try:
                # 【修改】使用更适合节点编辑器的模板
                content = "new_task:\n  meta:\n    title: New Task\n  steps:\n    step_1:\n      name: 'Initial Step'\n      action: core/print\n      params:\n        message: 'Hello from your new task!'\n"
                self.bridge.create_file(plan_name, new_path, content)
                self.reload_workspace()
            except Exception as e:
                QMessageBox.critical(self, "创建失败", str(e))

    def _handle_new_directory(self, plan_name, dir_path):
        # ... (此方法无变化) ...
        text, ok = QInputDialog.getText(self, "新建目录", "目录名:")
        if ok and text:
            new_path = str(PurePath(dir_path) / text)
            try:
                self.bridge.create_directory(plan_name, new_path)
                self.reload_workspace()
            except Exception as e:
                QMessageBox.critical(self, "创建失败", str(e))

    def _handle_rename(self, plan_name, old_path):
        # ... (此方法无变化) ...
        old_name = PurePath(old_path).name
        new_name, ok = QInputDialog.getText(self, "重命名", "新名称:", text=old_name)
        if ok and new_name and new_name != old_name:
            parent_path = str(PurePath(old_path).parent)
            new_path = str(PurePath(parent_path) / new_name)
            try:
                self.bridge.rename_path(plan_name, old_path, new_path)
                self.reload_workspace()
            except Exception as e:
                QMessageBox.critical(self, "重命名失败", str(e))

    def _handle_delete(self, plan_name, path):
        # ... (此方法无变化) ...
        reply = QMessageBox.question(self, "确认删除", f"确定要永久删除 '{path}' 吗？\n此操作无法撤销。",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.bridge.delete_path(plan_name, path)
                self.reload_workspace()
            except Exception as e:
                QMessageBox.critical(self, "删除失败", str(e))

    @Slot(QListWidgetItem)
    def _on_problem_clicked(self, item: QListWidgetItem):
        # 这个槽函数暂时保留，但由于没有Linter，它不会被触发
        pass

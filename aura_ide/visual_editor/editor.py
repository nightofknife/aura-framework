# src/aura_ide/visual_editor/editor.py

import yaml
from PySide6.QtWidgets import QWidget, QVBoxLayout, QMessageBox
from .graph import AuraNodeGraph


class VisualTaskEditor(QWidget):
    """
    一个封装了AuraNodeGraph的编辑器控件。
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.graph = AuraNodeGraph()
        # 禁用默认的右键菜单，IDEPanel将通过Inspector提供上下文操作
        self.graph.disable_context_menu(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.graph.widget)

        self._current_task_key = "untitled_task"

    def set_available_actions(self, actions: list):
        # 可以在这里更新图谱的上下文，例如用于节点属性的下拉菜单
        # 目前，这个信息主要由NodePalette使用
        pass

    def load_from_text(self, yaml_text: str):
        """从YAML文本内容加载任务。"""
        try:
            data = yaml.safe_load(yaml_text) or {}
            if not isinstance(data, dict):
                raise ValueError("YAML内容不是一个有效的任务集合（字典）。")

            # 假设一个文件只定义一个主任务，取第一个key
            if not data:
                # 文件为空，创建一个默认的start节点
                self.graph.clear_session()
                start_node = self.graph.create_node('aura.ActionNode', name='start')
                start_node.set_property('node_id', 'start')
                self._current_task_key = "new_task"
                return

            self._current_task_key = next(iter(data))
            task_def = data[self._current_task_key]

            if not isinstance(task_def, dict) or 'steps' not in task_def:
                raise ValueError(f"任务 '{self._current_task_key}' 格式不正确，缺少 'steps' 列表。")

            self.graph.load_task_definition(self._current_task_key, task_def)

        except Exception as e:
            QMessageBox.critical(self, "加载错误", f"无法加载任务定义：\n{e}")
            self.graph.clear_session()

    def save_to_text(self) -> str:
        """将当前图谱序列化为YAML文本。"""
        try:
            task_def = self.graph.to_dict()
            full_definition = {
                self._current_task_key: task_def
            }
            # 使用安全的dump，并设置一些可读性选项
            return yaml.dump(
                full_definition,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                indent=2
            )
        except Exception as e:
            QMessageBox.critical(self, "保存错误", f"无法序列化任务图：\n{e}")
            return ""

    def add_node_at_center(self, node_type: str, properties: dict = None):
        """在视图中心添加一个新节点。"""
        properties = properties or {}
        pos = self.graph.viewer().scene_center()

        node = None
        if node_type == 'action':
            node = self.graph.create_node('aura.ActionNode', name="New Action", pos=[pos.x(), pos.y()])
            node.set_property('action_id', properties.get('action_id', ''))
        elif node_type == 'logic':
            logic_type = properties.get('logic_type', 'and')
            node = self.graph.create_node('aura.LogicGateNode', name=logic_type.upper(), pos=[pos.x(), pos.y()])
            node.set_property('type', logic_type)

        if node:
            node.set_property('node_id', node.id)  # 初始ID

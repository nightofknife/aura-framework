"""
定义了 Aura IDE 的可视化任务编辑器主控件。

该模块的核心是 `VisualTaskEditor` 类，它是一个 `QWidget`，封装了
底层的 `AuraNodeGraph` 实例。它为外部提供了一个更高层次的API，
用于将YAML格式的任务定义加载到可视化图形编辑器中，以及将编辑器中的
图形表示序列化回YAML文本，从而实现了可视化编辑的核心功能。
"""
from typing import Dict, Any, List, Optional

import yaml
from PySide6.QtWidgets import QWidget, QVBoxLayout, QMessageBox
from .graph import AuraNodeGraph


class VisualTaskEditor(QWidget):
    """
    一个封装了 `AuraNodeGraph` 的高级编辑器控件。

    它提供了加载和保存任务定义的功能，并作为 `AuraNodeGraph`
    在IDE中的主要容器。
    """

    def __init__(self, parent: Optional[QWidget] = None):
        """
        初始化可视化任务编辑器。

        Args:
            parent (Optional[QWidget]): 父控件。
        """
        super().__init__(parent)

        self.graph = AuraNodeGraph()
        # 禁用默认的右键菜单，因为IDE将通过属性检查器提供上下文相关的操作
        self.graph.disable_context_menu(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.graph.widget)

        self._current_task_key = "untitled_task"

    def set_available_actions(self, actions: List[Dict[str, Any]]):
        """
        设置当前可用的行为列表。

        （占位符）此方法未来可用于向图编辑器提供上下文信息，
        例如在创建新节点时提供可选的行为列表。

        Args:
            actions (List[Dict[str, Any]]): 可用行为的定义列表。
        """
        pass

    def load_from_text(self, yaml_text: str):
        """
        从YAML格式的文本内容加载任务定义到编辑器中。

        此方法会解析YAML文本，提取任务定义，并调用底层的 `AuraNodeGraph`
        来构建对应的节点和连接。如果加载失败，会弹出错误提示框。

        Args:
            yaml_text (str): 包含任务定义的YAML格式字符串。
        """
        try:
            data = yaml.safe_load(yaml_text) or {}
            if not isinstance(data, dict):
                raise ValueError("YAML内容不是一个有效的任务集合（字典）。")

            # 假设一个文件只定义一个主任务，取第一个键
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
                raise ValueError(f"任务 '{self._current_task_key}' 格式不正确，缺少 'steps' 字典。")

            self.graph.load_task_definition(self._current_task_key, task_def)

        except Exception as e:
            QMessageBox.critical(self, "加载错误", f"无法加载任务定义：\n{e}")
            self.graph.clear_session()

    def save_to_text(self) -> str:
        """
        将当前图谱的状态序列化为YAML格式的文本。

        Returns:
            str: 代表当前任务定义的YAML格式字符串。如果序列化失败，则返回空字符串。
        """
        try:
            task_def = self.graph.to_dict()
            full_definition = {
                self._current_task_key: task_def
            }
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

    def add_node_at_center(self, node_type: str, properties: Optional[Dict[str, Any]] = None):
        """
        在视图中心添加一个新节点。

        Args:
            node_type (str): 要添加的节点类型，例如 'action' 或 'logic'。
            properties (Optional[Dict[str, Any]]): 要设置到新节点上的属性字典。
        """
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
            # 使用NodeGraphQt内部ID作为初始的唯一节点ID
            node.set_property('node_id', node.id)

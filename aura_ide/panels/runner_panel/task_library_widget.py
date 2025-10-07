"""
定义了“运行中心”中的任务库控件。

该模块提供了两个类：
- **TaskCard**: 一个用于在列表中美观地显示单个任务信息的自定义 `QWidget`。
- **TaskLibraryWidget**: 任务库的主控件，它包含一个搜索栏和一个
  `QListWidget`。它负责从后端加载所有可用的任务，使用 `TaskCard`
  进行展示，并提供搜索过滤功能。用户可以通过双击任务卡片将其添加到
  执行批次中。
"""
from typing import Dict, Any, List, Optional

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QLabel, QHBoxLayout
from PySide6.QtCore import Signal, Qt, Slot

from ....core_integration.qt_bridge import QtBridge


class TaskCard(QWidget):
    """
    一个自定义控件，用于以卡片形式显示单个任务的摘要信息。
    """

    def __init__(self, title: str, description: str, plan: str, parent: Optional[QWidget] = None):
        """
        初始化任务卡片。

        Args:
            title (str): 任务的标题。
            description (str): 任务的描述。
            plan (str): 任务所属的方案名称。
            parent (Optional[QWidget]): 父控件。
        """
        super().__init__(parent)
        self.setObjectName("TaskCard")
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("TaskCardTitle")

        desc_label = QLabel(description)
        desc_label.setObjectName("TaskCardDescription")
        desc_label.setWordWrap(True)

        plan_label = QLabel(plan)
        plan_label.setObjectName("TaskCardPlanTag")

        layout.addWidget(title_label)
        layout.addWidget(desc_label)
        layout.addStretch()
        layout.addWidget(plan_label, 0, Qt.AlignRight)


class TaskLibraryWidget(QWidget):
    """
    任务库控件，用于展示、搜索和选择所有可用的自动化任务。

    Signals:
        task_added (dict): 当用户双击一个任务卡片时发射，
            参数为该任务的完整信息字典。
    """
    task_added = Signal(dict)

    def __init__(self, bridge: QtBridge, parent: Optional[QWidget] = None):
        """
        初始化任务库控件。

        Args:
            bridge (QtBridge): 连接后端的桥接器实例。
            parent (Optional[QWidget]): 父控件。
        """
        super().__init__(parent)
        self.bridge = bridge
        self.all_tasks: List[Dict[str, Any]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("🔍 搜索任务...")
        self.search_bar.setObjectName("SearchBar")

        self.task_list = QListWidget()
        self.task_list.setObjectName("TaskLibraryList")
        self.task_list.setSpacing(5)

        layout.addWidget(self.search_bar)
        layout.addWidget(self.task_list)

        self.search_bar.textChanged.connect(self._filter_tasks)
        self.task_list.itemDoubleClicked.connect(self._on_item_double_clicked)

    def refresh_tasks(self):
        """
        从后端重新加载所有任务的定义，并刷新列表显示。
        """
        self.all_tasks = []
        try:
            self.all_tasks = self.bridge.scheduler.get_all_task_definitions_with_meta()
        except Exception as e:
            print(f"获取所有任务时出错: {e}")

        self._populate_list(self.all_tasks)

    def _populate_list(self, tasks: List[Dict[str, Any]]):
        """
        使用给定的任务信息列表填充任务列表控件。

        Args:
            tasks (List[Dict[str, Any]]): 要显示的任务信息列表。
        """
        self.task_list.clear()
        for task_info in sorted(tasks, key=lambda x: x['full_task_id']):
            item = QListWidgetItem(self.task_list)
            card = TaskCard(
                task_info.get('meta', {}).get('title', task_info['task_name_in_plan']),
                task_info.get('meta', {}).get('description', '无描述'),
                task_info['plan_name']
            )
            item.setSizeHint(card.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, task_info)
            self.task_list.addItem(item)
            self.task_list.setItemWidget(item, card)

    def _filter_tasks(self, text: str):
        """
        根据搜索框中的文本过滤任务列表的显示。

        Args:
            text (str): 用户输入的搜索文本。
        """
        text = text.lower()
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            task_info = item.data(Qt.ItemDataRole.UserRole)

            search_content = (
                    task_info.get('full_task_id', '') +
                    task_info.get('meta', {}).get('title', '') +
                    task_info.get('meta', {}).get('description', '')
            ).lower()

            item.setHidden(text not in search_content)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        """
        当一个列表项被双击时调用的槽函数。

        它会获取该项关联的任务信息，并发出 `task_added` 信号。

        Args:
            item (QListWidgetItem): 被双击的列表项。
        """
        task_info = item.data(Qt.ItemDataRole.UserRole)
        self.task_added.emit(task_info)

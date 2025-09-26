# aura_ide/panels/runner_panel/task_library_widget.py (新建文件)

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QLabel, QHBoxLayout
from PySide6.QtCore import Signal, QSize, Qt


class TaskCard(QWidget):
    """任务卡片自定义控件"""

    def __init__(self, title, description, plan, parent=None):
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
    task_added = Signal(dict)  # 发射包含 plan, task_name, task_def 的字典

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.all_tasks = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("🔍 搜索任务...")
        self.search_bar.setObjectName("SearchBar")

        self.task_list = QListWidget()
        self.task_list.setObjectName("TaskLibraryList")
        self.task_list.setSpacing(5)  # 卡片间的垂直间距

        layout.addWidget(self.search_bar)
        layout.addWidget(self.task_list)

        self.search_bar.textChanged.connect(self._filter_tasks)
        self.task_list.itemDoubleClicked.connect(self._on_item_double_clicked)

    def refresh_tasks(self):
        self.all_tasks = []
        try:
            # 假设 bridge 有一个方法可以获取所有任务的详细信息
            # 如果没有，你需要根据 list_plans 和 list_tasks 来构建
            self.all_tasks = self.bridge.scheduler.get_all_task_definitions_with_meta()
        except Exception as e:
            print(f"Error fetching all tasks: {e}")

        self._populate_list(self.all_tasks)

    def _populate_list(self, tasks):
        self.task_list.clear()
        for task_info in sorted(tasks, key=lambda x: x['full_task_id']):
            item = QListWidgetItem(self.task_list)
            card = TaskCard(
                task_info.get('meta', {}).get('title', task_info['task_name_in_plan']),
                task_info.get('meta', {}).get('description', '无描述'),
                task_info['plan_name']
            )
            item.setSizeHint(card.sizeHint())
            # 将任务的完整信息存储在 item 中
            item.setData(Qt.UserRole, task_info)
            self.task_list.addItem(item)
            self.task_list.setItemWidget(item, card)

    def _filter_tasks(self, text):
        text = text.lower()
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            task_info = item.data(Qt.UserRole)

            search_content = (
                    task_info.get('full_task_id', '') +
                    task_info.get('meta', {}).get('title', '') +
                    task_info.get('meta', {}).get('description', '')
            ).lower()

            item.setHidden(text not in search_content)

    def _on_item_double_clicked(self, item):
        task_info = item.data(Qt.UserRole)
        self.task_added.emit(task_info)

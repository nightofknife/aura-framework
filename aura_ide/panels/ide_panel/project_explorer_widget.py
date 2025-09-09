# src/aura_ide/panels/ide_panel/project_explorer_widget.py

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
from PySide6.QtCore import Signal, Qt, Slot


class ProjectExplorerWidget(QTreeWidget):
    file_open_requested = Signal(str, str)  # plan_name, relative_path

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self.setHeaderLabels(["项目"])
        self.itemDoubleClicked.connect(self._on_item_double_clicked)

    def refresh(self):
        self.clear()
        try:
            all_plans = self.bridge.list_plans()
            for plan_name in all_plans:
                plan_item = QTreeWidgetItem([plan_name])
                self.addTopLevelItem(plan_item)

                # 简单实现，只列出tasks
                try:
                    tasks = self.bridge.list_tasks(plan_name)
                    if tasks:
                        tasks_root = QTreeWidgetItem(["tasks"])
                        plan_item.addChild(tasks_root)
                        for task_full_name in tasks:
                            # 假设 task_full_name 是 'folder/task_key'
                            task_item = QTreeWidgetItem([task_full_name])
                            task_item.setData(0, Qt.ItemDataRole.UserRole, {
                                "type": "task_file",
                                "plan": plan_name,
                                "task_name": task_full_name
                            })
                            tasks_root.addChild(task_item)
                except Exception as e:
                    print(f"Error listing tasks for plan {plan_name}: {e}")

            self.expandToDepth(1)
        except Exception as e:
            print(f"Error refreshing project explorer: {e}")

    @Slot(QTreeWidgetItem, int)
    def _on_item_double_clicked(self, item, column):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, dict) and data.get("type") == "task_file":
            plan = data["plan"]
            task_name = data["task_name"]

            # 从 task_name (e.g., 'sub/task_key') 推断文件路径
            file_path = f"tasks/{'/'.join(task_name.split('/')[:-1])}.yaml"
            if task_name.count('/') == 0:  # 根目录下的task
                file_path = f"tasks/{task_name}.yaml"  # 假设文件名和task key同名

            # 简化：假设一个task_key在一个文件里
            # 在更复杂的场景中，需要更精确的文件定位逻辑
            try:
                # 假设task_name的第一部分是文件名
                filename = task_name.split('/')[0]
                file_path_to_open = f"tasks/{filename}.yaml"
                self.file_open_requested.emit(plan, file_path_to_open)
            except Exception as e:
                print(f"Could not determine file path for task {task_name}: {e}")


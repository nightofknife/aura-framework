# src/ui/main_window.py

import tkinter as tk
from tkinter import ttk
import queue

from packages.aura_core.scheduler import Scheduler
from packages.aura_shared_utils.utils.logger import logger
from packages.aura_ui.scheduler_panel import SchedulerPanel, TaskRunnerPanel
from packages.aura_ui.plan_editor_panel import PlanEditorPanel
from packages.aura_ui.context_editor import ContextEditorWindow
from packages.aura_ui.interrupt_manager import InterruptManagerWindow
from packages.aura_ui.service_manager_panel import ServiceManagerPanel
from packages.aura_ui.schedule_editor import ScheduleEditorWindow

class AuraIDE:
    def __init__(self, root):
        self.root = root
        self.root.title("Aura - 自动化框架控制台")
        self.root.geometry("1200x800")

        # 初始化核心组件
        self.scheduler = Scheduler()
        self.log_queue = queue.Queue()

        # 设置日志系统，连接UI队列
        logger.setup(log_dir='logs', task_name='ui_session', ui_log_queue=self.log_queue)

        # 创建UI
        self._create_menu()
        self._create_tabs()


    def _create_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="退出", command=self.root.quit)
        menubar.add_cascade(label="文件", menu=file_menu)

        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="调度管理器...", command=self._open_schedule_editor)
        tools_menu.add_separator()  # 添加一条分割线
        tools_menu.add_command(label="编辑长期上下文...", command=self._open_context_editor)
        tools_menu.add_command(label="中断管理器...", command=self._open_interrupt_manager)
        menubar.add_cascade(label="工具", menu=tools_menu)

    def _create_tabs(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(expand=True, fill='both', padx=5, pady=5)

        # 创建各个标签页的父框架
        scheduler_tab = ttk.Frame(notebook, padding=10)
        # 【新增】为服务管理器创建一个新的标签页框架
        service_manager_tab = ttk.Frame(notebook, padding=5)
        task_runner_tab = ttk.Frame(notebook, padding=10)
        plan_editor_tab = ttk.Frame(notebook, padding=0)

        notebook.add(scheduler_tab, text='调度器监控')
        # 【新增】将新标签页添加到Notebook中
        notebook.add(service_manager_tab, text='服务管理器')
        notebook.add(task_runner_tab, text='任务浏览器')
        notebook.add(plan_editor_tab, text='方案编辑器')

        # 实例化并填充每个标签页
        SchedulerPanel(scheduler_tab, self.scheduler, self.log_queue).pack(expand=True, fill='both')
        # 【新增】实例化并填充服务管理器面板
        ServiceManagerPanel(service_manager_tab, self.scheduler).pack(expand=True, fill='both')
        TaskRunnerPanel(task_runner_tab, self.scheduler).pack(expand=True, fill='both')
        PlanEditorPanel(plan_editor_tab, self.scheduler).pack(expand=True, fill='both')

    def _open_context_editor(self):
        ContextEditorWindow(self.root, self.scheduler)

    def _open_interrupt_manager(self):
        InterruptManagerWindow(self.root, self.scheduler)

    def _open_schedule_editor(self):
        """【新增】打开可视化调度编辑器窗口。"""
        ScheduleEditorWindow(self.root, self.scheduler)

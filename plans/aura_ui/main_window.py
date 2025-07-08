# packages/aura_ui/main_window.py (最终修正版)

import tkinter as tk
from tkinter import ttk
import queue

# 【修正】不再需要从这里导入 Scheduler
# from packages.aura_core.scheduler import Scheduler
from packages.aura_shared_utils.utils.logger import logger
from plans.aura_ui.scheduler_panel import SchedulerPanel, TaskRunnerPanel
from plans.aura_ui.plan_editor_panel import PlanEditorPanel
from plans.aura_ui.context_editor import ContextEditorWindow
from plans.aura_ui.interrupt_manager import InterruptManagerWindow
from plans.aura_ui.service_manager_panel import ServiceManagerPanel
from plans.aura_ui.schedule_editor import ScheduleEditorWindow


class AuraIDE:
    # 【核心修正 #1】修改构造函数，接收一个 scheduler 实例
    def __init__(self, root, scheduler):
        self.root = root
        # 【核心修正 #2】持有传入的 scheduler 实例，而不是自己创建
        self.scheduler = scheduler

        self.root.title("Aura - 自动化框架控制台")
        self.root.geometry("1200x800")

        # 【核心修正 #3】日志队列和设置现在也由UI负责
        self.log_queue = queue.Queue()
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
        tools_menu.add_separator()
        tools_menu.add_command(label="编辑长期上下文...", command=self._open_context_editor)
        tools_menu.add_command(label="中断管理器...", command=self._open_interrupt_manager)
        menubar.add_cascade(label="工具", menu=tools_menu)

    def _create_tabs(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(expand=True, fill='both', padx=5, pady=5)

        scheduler_tab = ttk.Frame(notebook, padding=10)
        service_manager_tab = ttk.Frame(notebook, padding=5)
        task_runner_tab = ttk.Frame(notebook, padding=10)
        plan_editor_tab = ttk.Frame(notebook, padding=0)

        notebook.add(scheduler_tab, text='调度器监控')
        notebook.add(service_manager_tab, text='服务管理器')
        notebook.add(task_runner_tab, text='任务浏览器')
        notebook.add(plan_editor_tab, text='方案编辑器')

        # 实例化并填充每个标签页
        # 注意：这里的代码完全不需要改变，因为它们已经是通过 self.scheduler 接收实例的
        SchedulerPanel(scheduler_tab, self.scheduler, self.log_queue).pack(expand=True, fill='both')
        ServiceManagerPanel(service_manager_tab, self.scheduler).pack(expand=True, fill='both')
        TaskRunnerPanel(task_runner_tab, self.scheduler).pack(expand=True, fill='both')
        PlanEditorPanel(plan_editor_tab, self.scheduler).pack(expand=True, fill='both')

    def _open_context_editor(self):
        ContextEditorWindow(self.root, self.scheduler)

    def _open_interrupt_manager(self):
        InterruptManagerWindow(self.root, self.scheduler)

    def _open_schedule_editor(self):
        ScheduleEditorWindow(self.root, self.scheduler)

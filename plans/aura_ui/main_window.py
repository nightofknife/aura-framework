# plans/aura_ui/main_window.py (Workspace集成版)

import tkinter as tk
from tkinter import ttk
import queue

from packages.aura_shared_utils.utils.logger import logger
from plans.aura_ui.scheduler_panel import SchedulerPanel, TaskRunnerPanel
# 【修改】不再直接导入 PlanEditorPanel，而是导入新的 WorkspacePanel
from plans.aura_ui.workspace_panel import WorkspacePanel
from plans.aura_ui.context_editor import ContextEditorWindow
from plans.aura_ui.interrupt_manager import InterruptManagerWindow
from plans.aura_ui.service_manager_panel import ServiceManagerPanel
from plans.aura_ui.planner_debugger_panel import PlannerDebuggerPanel
from plans.aura_ui.event_bus_monitor_panel import EventBusMonitorPanel
from plans.aura_ui.schedule_editor import ScheduleEditorWindow


class AuraIDE:
    def __init__(self, root, scheduler):
        self.root = root
        self.scheduler = scheduler
        self.root.title("Aura - 自动化框架控制台")
        self.root.geometry("1200x800")
        self.log_queue = queue.Queue()
        logger.setup(log_dir='logs', task_name='ui_session', ui_log_queue=self.log_queue)
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
        planner_tab = ttk.Frame(notebook, padding=5)
        event_bus_tab = ttk.Frame(notebook, padding=5)
        service_manager_tab = ttk.Frame(notebook, padding=5)
        task_runner_tab = ttk.Frame(notebook, padding=10)
        # 【修改】为新的 WorkspacePanel 创建一个 Frame
        workspace_tab = ttk.Frame(notebook, padding=0)

        notebook.add(scheduler_tab, text='调度器监控')
        # 【修改】添加新的工作区Tab，并修改名称
        notebook.add(workspace_tab, text='工作区')
        notebook.add(planner_tab, text='规划器调试')
        notebook.add(event_bus_tab, text='事件总线')
        notebook.add(service_manager_tab, text='服务管理器')
        notebook.add(task_runner_tab, text='任务浏览器')

        # 实例化并填充每个标签页
        SchedulerPanel(scheduler_tab, self.scheduler, self.log_queue).pack(expand=True, fill='both')
        # 【修改】实例化新的 WorkspacePanel
        WorkspacePanel(workspace_tab, self.scheduler).pack(expand=True, fill='both')
        PlannerDebuggerPanel(planner_tab, self.scheduler).pack(expand=True, fill='both')
        EventBusMonitorPanel(event_bus_tab, self.scheduler).pack(expand=True, fill='both')
        ServiceManagerPanel(service_manager_tab, self.scheduler).pack(expand=True, fill='both')
        TaskRunnerPanel(task_runner_tab, self.scheduler).pack(expand=True, fill='both')

    def _open_context_editor(self):
        ContextEditorWindow(self.root, self.scheduler)

    def _open_interrupt_manager(self):
        InterruptManagerWindow(self.root, self.scheduler)

    def _open_schedule_editor(self):
        ScheduleEditorWindow(self.root, self.scheduler)

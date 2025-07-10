# plans/aura_ui/main_window.py (最终修正版)

import tkinter as tk
from tkinter import ttk
import queue
from typing import Dict, Type, Tuple, Any

# 导入所有需要的模块
from packages.aura_core.scheduler import Scheduler
from packages.aura_shared_utils.utils.logger import logger
from .base_panel import BasePanel  # 导入新的基类
from .scheduler_panel import SchedulerPanel, TaskRunnerPanel
from .workspace_panel import WorkspacePanel
from .service_manager_panel import ServiceManagerPanel
from .planner_debugger_panel import PlannerDebuggerPanel
from .event_bus_monitor_panel import EventBusMonitorPanel
from .context_editor import ContextEditorWindow
from .interrupt_manager import InterruptManagerWindow
from .schedule_editor import ScheduleEditorWindow


class AuraIDE:
    """
    Aura IDE 的主窗口类。
    负责聚合所有UI面板，并管理它们的生命周期。
    """
    # 【核心修正】TAB_DEFINITIONS 现在只定义面板类和padding，依赖注入将完全自动化
    TAB_DEFINITIONS: Dict[str, Tuple[Type[BasePanel], int]] = {
        "调度器监控": (SchedulerPanel, 10),
        "工作区": (WorkspacePanel, 0),
        "任务浏览器": (TaskRunnerPanel, 10),
        "规划器调试": (PlannerDebuggerPanel, 5),
        "事件总线": (EventBusMonitorPanel, 5),
        "服务管理器": (ServiceManagerPanel, 5),
    }

    def __init__(self, root: tk.Tk, scheduler: Scheduler):
        self.root = root
        self.scheduler = scheduler
        self.panels: Dict[str, BasePanel] = {}
        self.log_queue: queue.Queue = queue.Queue()

        # 【核心修正】一个统一的依赖注入容器
        self.dependencies = {
            'scheduler': self.scheduler,
            'ide': self,
            'log_queue': self.log_queue
        }

        self._configure_root_window()
        self._setup_logging()
        self._create_main_widgets()
        self._create_menu()
        self._create_and_populate_tabs()
        self.root.bind("<Destroy>", self._on_destroy)

    def _configure_root_window(self):
        self.root.title("Aura - 自动化框架控制台")
        self.root.geometry("1400x900")
        self.root.minsize(1000, 700)

    def _setup_logging(self):
        logger.setup(log_dir='logs', task_name='ui_session', ui_log_queue=self.log_queue)

    def _create_main_widgets(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill='both', padx=5, pady=5)

    def _create_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="退出", command=self.root.destroy)
        menubar.add_cascade(label="文件", menu=file_menu)
        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="调度管理器...", command=self._open_schedule_editor)
        tools_menu.add_separator()
        tools_menu.add_command(label="编辑长期上下文...", command=self._open_context_editor)
        tools_menu.add_command(label="中断管理器...", command=self._open_interrupt_manager)
        menubar.add_cascade(label="工具", menu=tools_menu)

    def _create_and_populate_tabs(self):
        """
        【最终修正】使用正确的依赖注入方式创建所有面板。
        """
        for tab_name, (PanelClass, padding) in self.TAB_DEFINITIONS.items():
            tab_frame = ttk.Frame(self.notebook, padding=padding)
            self.notebook.add(tab_frame, text=tab_name)

            try:
                # 【核心修正】将依赖作为关键字参数(kwargs)传递
                panel_instance = PanelClass(parent=tab_frame, **self.dependencies)
                panel_instance.pack(expand=True, fill='both')
                self.panels[tab_name] = panel_instance
            except Exception as e:
                print(f"ERROR: 实例化面板 '{tab_name}' ({PanelClass.__name__}) 时出错: {e}")
                error_label = ttk.Label(tab_frame, text=f"加载失败:\n{e}", foreground="red")
                error_label.pack(pady=20)

    def _open_context_editor(self):
        ContextEditorWindow(self.root, self.scheduler)

    def _open_interrupt_manager(self):
        InterruptManagerWindow(self.root, self.scheduler)

    def _open_schedule_editor(self):
        ScheduleEditorWindow(self.root, self.scheduler)

    def _on_destroy(self, event):
        if event.widget == self.root:
            print("AuraIDE is being destroyed. Cleaning up panels...")
            for panel_name, panel_instance in self.panels.items():
                if hasattr(panel_instance, 'destroy') and callable(panel_instance.destroy):
                    print(f"Destroying panel: {panel_name}")
                    panel_instance.destroy()
            print("All panels cleaned up.")

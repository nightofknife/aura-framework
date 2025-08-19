# plans/aura_ui/main_window.py (最终修正版)

import queue
import tkinter as tk
from tkinter import ttk
from typing import Dict, Type, Tuple, Any

# 导入所有需要的模块
from packages.aura_core.scheduler import Scheduler
from packages.aura_shared_utils.utils.logger import logger
from .base_panel import BasePanel  # 导入新的基类
from .context_editor import ContextEditorWindow
from .event_bus_monitor_panel import EventBusMonitorPanel
from .interrupt_manager import InterruptManagerWindow
from .planner_debugger_panel import PlannerDebuggerPanel
from .schedule_editor import ScheduleEditorWindow
from .scheduler_panel import SchedulerPanel, TaskRunnerPanel
from .service_manager_panel import ServiceManagerPanel
from .workspace_panel import WorkspacePanel


class AuraIDE:
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
        self.ui_update_queue: queue.Queue = queue.Queue()  # 【新增】

        # 【修改】将 ui_update_queue 注入到 Scheduler 和依赖项中
        self.scheduler.set_ui_update_queue(self.ui_update_queue)
        self.dependencies = {
            'scheduler': self.scheduler,
            'ide': self,
            'log_queue': self.log_queue,
            'ui_update_queue': self.ui_update_queue
        }

        self._configure_root_window()
        self._setup_logging()
        self._create_main_widgets()
        self._create_menu()
        self._create_and_populate_tabs()
        self.root.bind("<Destroy>", self._on_destroy)

        # 【新增】启动UI主更新循环
        self.root.after(100, self._process_ui_updates)

    # ... (_configure_root_window, _setup_logging, _create_main_widgets, _create_menu, _create_and_populate_tabs 不变) ...
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
        for tab_name, (PanelClass, padding) in self.TAB_DEFINITIONS.items():
            tab_frame = ttk.Frame(self.notebook, padding=padding)
            self.notebook.add(tab_frame, text=tab_name)
            try:
                panel_instance = PanelClass(parent=tab_frame, **self.dependencies)
                panel_instance.pack(expand=True, fill='both')
                self.panels[tab_name] = panel_instance
            except Exception as e:
                print(f"ERROR: 实例化面板 '{tab_name}' ({PanelClass.__name__}) 时出错: {e}")
                error_label = ttk.Label(tab_frame, text=f"加载失败:\n{e}", foreground="red")
                error_label.pack(pady=20)

    def _process_ui_updates(self):
        """【新增】UI主心跳循环，处理所有来自后端的更新。"""
        # 1. 处理日志队列 (移动自 SchedulerPanel)
        if '调度器监控' in self.panels:
            log_panel = self.panels['调度器监控']
            if hasattr(log_panel, 'process_log_queue_once'):
                log_panel.process_log_queue_once()

        # 2. 处理事件总线队列 (移动自 EventBusMonitorPanel)
        if '事件总线' in self.panels:
            event_panel = self.panels['事件总线']
            if hasattr(event_panel, 'process_event_queue_once'):
                event_panel.process_event_queue_once()

        # 3. 处理核心状态更新队列
        try:
            while not self.ui_update_queue.empty():
                msg = self.ui_update_queue.get_nowait()
                msg_type = msg.get('type')
                data = msg.get('data')
                self._dispatch_ui_update(msg_type, data)
        except queue.Empty:
            pass
        finally:
            # 安排下一次检查
            self.root.after(100, self._process_ui_updates)

    def _dispatch_ui_update(self, msg_type: str, data: Any):
        """【新增】根据消息类型将数据分发给对应的面板。"""
        if msg_type == 'master_status_update':
            if '调度器监控' in self.panels:
                self.panels['调度器监控'].update_master_status(data)

        elif msg_type == 'run_status_single_update':
            if '调度器监控' in self.panels:
                self.panels['调度器监控'].update_single_task_status(data)

        elif msg_type == 'full_status_update':
            if '调度器监控' in self.panels:
                self.panels['调度器监控'].update_schedule_status(data['schedule'])
            if '服务管理器' in self.panels:
                self.panels['服务管理器'].update_service_list(data['services'])
            if '工作区' in self.panels or '任务浏览器' in self.panels:
                self.panels['工作区'].populate_plans(data['workspace']['plans'])
                self.panels['任务浏览器'].populate_all(data['workspace'])

    # ... ( _open_* 方法不变) ...
    def _open_context_editor(self):
        ContextEditorWindow(self.root, self.scheduler)

    def _open_interrupt_manager(self):
        InterruptManagerWindow(self.root, self.scheduler)

    def _open_schedule_editor(self):
        ScheduleEditorWindow(self.root, self.scheduler)

    def _on_destroy(self, event):
        if event.widget == self.root:
            logger.info("AuraIDE is being destroyed. Stopping scheduler...")
            # 【修改】确保在关闭UI时，后端也被停止
            if self.scheduler and self.scheduler.is_running.is_set():
                self.scheduler.stop_scheduler()

            for panel_name, panel_instance in self.panels.items():
                if hasattr(panel_instance, 'destroy') and callable(panel_instance.destroy):
                    panel_instance.destroy()
            logger.info("All panels and scheduler cleaned up.")

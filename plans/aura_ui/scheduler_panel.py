# plans/aura_ui/scheduler_panel.py (异步桥接版)

import queue
import tkinter as tk
from collections import defaultdict
from tkinter import ttk, scrolledtext, messagebox

from packages.aura_shared_utils.utils.logger import logger
from .base_panel import BasePanel


class SchedulerPanel(BasePanel):
    def _create_widgets(self):
        # ... (UI创建代码不变) ...
        paned_window = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned_window.pack(fill=tk.BOTH, expand=True)
        top_frame = ttk.Frame(paned_window)
        paned_window.add(top_frame, weight=3)
        status_panel = ttk.LabelFrame(top_frame, text="当前状态", padding="10")
        status_panel.pack(fill=tk.X, pady=(0, 10), padx=5)
        self.current_task_label = ttk.Label(status_panel, text="当前运行: 无", font=("", 10, "bold"))
        self.current_task_label.pack(anchor="w")
        self.queue_status_label = ttk.Label(status_panel, text="排队任务: 0", foreground="gray")
        self.queue_status_label.pack(anchor="w")
        master_control_frame = ttk.LabelFrame(top_frame, text="调度器控制", padding="10")
        master_control_frame.pack(fill=tk.X, pady=(0, 10), padx=5)
        self.master_status_label = ttk.Label(master_control_frame, text="状态: 未知", font=("", 10, "bold"))
        self.master_status_label.pack(side=tk.LEFT, padx=5)
        self.master_control_button = ttk.Button(master_control_frame, text="启动调度器")
        self.master_control_button.pack(side=tk.RIGHT, padx=5)
        self.schedule_panel = ttk.LabelFrame(top_frame, text="调度任务列表", padding="10")
        self.schedule_panel.pack(fill=tk.BOTH, expand=True, padx=5)
        canvas = tk.Canvas(self.schedule_panel, borderwidth=0, background="#ffffff")
        scrollbar = ttk.Scrollbar(self.schedule_panel, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        log_frame = ttk.Frame(paned_window)
        paned_window.add(log_frame, weight=1)
        ttk.Label(log_frame, text="实时日志").pack(anchor="w", padx=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state='disabled', height=10, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=(5, 0), padx=5)
        for tag, color in [('INFO', 'black'), ('WARNING', 'orange'), ('ERROR', 'red'), ('DEBUG', 'gray')]:
            self.log_text.tag_config(tag, foreground=color)
        self.log_text.tag_config('CRITICAL', foreground='red', font=("", 9, "bold"))
        self.task_widgets = {}
        self.all_statuses = []  # 【新增】本地缓存状态

    def _initial_load(self):
        """初始加载时，请求一次全量数据。"""
        self.update_master_status(self.scheduler.get_master_status())
        self.update_schedule_status(self.scheduler.get_schedule_status())

    def update_master_status(self, master_status: dict):
        """【新增】被动更新调度器主状态。"""
        if master_status["is_running"]:
            self.master_status_label.config(text="状态: 运行中", foreground="green")
            self.master_control_button.config(text="停止调度器", command=self.scheduler.stop_scheduler)
        else:
            self.master_status_label.config(text="状态: 已停止", foreground="red")
            self.master_control_button.config(text="启动调度器", command=self.scheduler.start_scheduler)

    def update_schedule_status(self, all_statuses: list):
        """【新增】被动更新整个任务列表。"""
        self.all_statuses = all_statuses
        existing_ids = set(self.task_widgets.keys())
        current_ids = {s.get('id') for s in all_statuses if s.get('id')}

        for task_id in existing_ids - current_ids:
            widget_info = self.task_widgets.pop(task_id, None)
            if widget_info and widget_info['frame'].winfo_exists():
                widget_info['frame'].destroy()

        for status in all_statuses:
            self._update_or_create_task_row(status)

        self._update_summary_labels()

    def update_single_task_status(self, status_update: dict):
        """【新增】被动更新单个任务的状态，更高效。"""
        task_id = status_update.get('id')
        if not task_id: return

        # 更新本地缓存
        found = False
        for i, status in enumerate(self.all_statuses):
            if status.get('id') == task_id:
                self.all_statuses[i].update(status_update)
                found = True
                break
        if not found:
            # 如果任务是新来的（不太可能，但做个保护）
            self.all_statuses.append(status_update)

        self._update_or_create_task_row(status_update)
        self._update_summary_labels()

    def _update_summary_labels(self):
        """【新增】根据本地缓存更新摘要信息。"""
        running_task = next((t for t in self.all_statuses if t.get('status') == 'running'), None)
        queued_count = sum(1 for t in self.all_statuses if t.get('status') == 'queued')
        self.current_task_label.config(
            text=f"当前运行: {running_task.get('name', 'N/A') if running_task else '无'}",
            foreground="blue" if running_task else "black")
        self.queue_status_label.config(text=f"排队任务: {queued_count}")

    def _update_or_create_task_row(self, task_data: dict):
        """【新增】一个统一的方法来创建或更新UI行。"""
        task_id = task_data.get('id')
        if not task_id: return
        if task_id not in self.task_widgets:
            self._create_task_row(task_data)
        self._update_task_row_ui(task_data)

    def _create_task_row(self, task_data):
        # ... (创建UI组件的逻辑不变) ...
        task_id = task_data['id']
        frame = ttk.Frame(self.scrollable_frame, padding=5)
        frame.pack(fill=tk.X, pady=2)
        enabled_var = tk.BooleanVar(value=task_data.get('enabled', False))
        display_text = f"{task_data.get('name', '未命名')} ({task_data.get('plan_name')})"
        ttk.Checkbutton(frame, text=display_text, variable=enabled_var,
                        command=lambda: self.scheduler.toggle_task_enabled(task_id, enabled_var.get())).pack(
            side=tk.LEFT, padx=5)
        status_label = ttk.Label(frame, text="", width=20, anchor="w")
        status_label.pack(side=tk.LEFT, padx=10)
        ttk.Button(frame, text="立即运行", command=lambda: self.scheduler.run_manual_task(task_id)).pack(side=tk.RIGHT,
                                                                                                         padx=5)
        self.task_widgets[task_id] = {'frame': frame, 'enabled_var': enabled_var, 'status_label': status_label}

    def _update_task_row_ui(self, task_data):
        # ... (更新UI组件的逻辑不变) ...
        widgets = self.task_widgets.get(task_data['id'])
        if not widgets: return
        status = task_data.get('status', 'unknown')
        color = {'running': 'blue', 'queued': 'orange', 'idle': 'green', 'failure': 'red'}.get(status, 'black')
        if status == 'idle' and task_data.get('result') == 'failure': color = 'red'
        widgets['status_label'].config(text=f"状态: {status}", foreground=color)
        widgets['enabled_var'].set(task_data.get('enabled', False))

    def process_log_queue_once(self):
        """【修改】由AuraIDE主循环调用，处理所有当前日志。"""
        try:
            while not self.log_queue.empty():
                record = self.log_queue.get_nowait()
                tag = next((t for t in ['CRITICAL', 'ERROR', 'WARNING', 'DEBUG', 'INFO'] if t in record), 'INFO')
                self.log_text.config(state='normal')
                self.log_text.insert(tk.END, record + '\n', (tag,))
                self.log_text.config(state='disabled')
                self.log_text.see(tk.END)
        except queue.Empty:
            pass


# ... (TaskRunnerPanel 的修改与 SchedulerPanel 类似，移除轮询，改为被动更新) ...
class TaskRunnerPanel(BasePanel):
    def _create_widgets(self):
        # ... (UI创建代码不变) ...
        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True)
        left_frame = ttk.Frame(main_pane, padding=5)
        main_pane.add(left_frame, weight=1)
        ttk.Label(left_frame, text="方案包 / 任务").pack(anchor='w')
        self.task_tree = ttk.Treeview(left_frame, show="tree")
        self.task_tree.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        self.task_tree.bind('<Double-1>', self.on_item_double_click)
        right_frame = ttk.Frame(main_pane, padding=5)
        main_pane.add(right_frame, weight=1)
        ttk.Label(right_frame, text="可用行为 (Actions)").pack(anchor='w')
        self.action_tree = ttk.Treeview(right_frame, columns=("Action Name",), show="headings")
        self.action_tree.heading("Action Name", text="行为名称")
        self.action_tree.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        bottom_bar = ttk.Frame(self)
        bottom_bar.pack(fill=tk.X, pady=5, padx=5)
        ttk.Button(bottom_bar, text="重新加载所有资源", command=self.reload_all_resources).pack()

    def _initial_load(self):
        """初始加载时，请求一次全量数据。"""
        self.reload_all_resources()

    def populate_all(self, workspace_data: dict):
        """【修改】被动接收工作区数据。"""
        self.populate_tasks(workspace_data['plans'])
        self.populate_actions(workspace_data['actions'])

    def populate_tasks(self, plans: list):
        # ... (逻辑不变, 参数从 scheduler.get_all_plans() 变为 plans) ...
        self.task_tree.delete(*self.task_tree.get_children())
        for plan_name in plans:
            plan_node = self.task_tree.insert('', 'end', text=plan_name, open=False, tags=('plan',))
            tasks = self.scheduler.get_tasks_for_plan(plan_name)  # 仍然可以调用scheduler获取细节
            for task_name in tasks:
                self.task_tree.insert(plan_node, 'end', text=task_name, tags=('task',))

    def populate_actions(self, action_defs: list):
        # ... (逻辑不变, 参数从 scheduler.actions... 变为 action_defs) ...
        self.action_tree.delete(*self.action_tree.get_children())
        grouped_actions = defaultdict(list)
        for action_def in action_defs:
            namespace = action_def.plugin.canonical_id
            grouped_actions[namespace].append(action_def)
        for namespace, actions in sorted(grouped_actions.items()):
            ns_node = self.action_tree.insert('', 'end', values=(namespace,), open=True, tags=('namespace',))
            for action_def in sorted(actions, key=lambda a: a.name):
                self.action_tree.insert(ns_node, 'end', values=(action_def.name,))
        self.action_tree.tag_configure('namespace', background='#f0f0f0', font=("", 9, "bold"))

    def reload_all_resources(self):
        try:
            logger.info("UI请求重新加载所有后端资源...")
            self.scheduler.reload_plans()  # 这个调用会自动触发UI更新
            logger.info("UI资源列表已刷新。")
        except Exception as e:
            messagebox.showerror("重载失败", f"重新加载资源时发生错误: {e}")

    # ... (on_item_double_click 不变) ...
    def on_item_double_click(self, event):
        item_id = self.task_tree.focus()
        item_tags = self.task_tree.item(item_id, "tags")
        if 'task' in item_tags:
            task_name = self.task_tree.item(item_id, "text")
            parent_id = self.task_tree.parent(item_id)
            plan_name = self.task_tree.item(parent_id, "text")
            if messagebox.askyesno("确认运行", f"确定要立即运行任务 '{task_name}' 吗？\n(来自方案包: {plan_name})"):
                logger.info(f"用户从UI请求运行临时任务: {plan_name}/{task_name}")
                self.scheduler.run_ad_hoc_task(plan_name, task_name)
                if self.ide and hasattr(self.ide, 'notebook'):
                    self.ide.notebook.select(0)

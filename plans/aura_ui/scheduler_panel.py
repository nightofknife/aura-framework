# plans/aura_ui/scheduler_panel.py (优化版)
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from collections import defaultdict
import queue
from packages.aura_shared_utils.utils.logger import logger
from .base_panel import BasePanel # 【修改】导入BasePanel

class SchedulerPanel(BasePanel): # 【修改】继承自BasePanel
    def __init__(self, parent, scheduler, ide, **kwargs):
        super().__init__(parent, scheduler, ide, **kwargs)

    def _create_widgets(self):
        # ... (这部分UI创建代码完全不变) ...
        paned_window = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned_window.pack(fill=tk.BOTH, expand=True)
        top_frame = ttk.Frame(paned_window)
        paned_window.add(top_frame, weight=3)
        status_panel = ttk.LabelFrame(top_frame, text="当前状态", padding="10");
        status_panel.pack(fill=tk.X, pady=(0, 10), padx=5)
        self.current_task_label = ttk.Label(status_panel, text="当前运行: 无", font=("", 10, "bold"));
        self.current_task_label.pack(anchor="w")
        self.queue_status_label = ttk.Label(status_panel, text="排队任务: 0", foreground="gray");
        self.queue_status_label.pack(anchor="w")
        master_control_frame = ttk.LabelFrame(top_frame, text="调度器控制", padding="10")
        master_control_frame.pack(fill=tk.X, pady=(0, 10), padx=5)
        self.master_status_label = ttk.Label(master_control_frame, text="状态: 未知", font=("", 10, "bold"))
        self.master_status_label.pack(side=tk.LEFT, padx=5)
        self.master_control_button = ttk.Button(master_control_frame, text="启动调度器")
        self.master_control_button.pack(side=tk.RIGHT, padx=5)
        self.schedule_panel = ttk.LabelFrame(top_frame, text="调度任务列表", padding="10");
        self.schedule_panel.pack(fill=tk.BOTH, expand=True, padx=5)
        canvas = tk.Canvas(self.schedule_panel, borderwidth=0, background="#ffffff")
        scrollbar = ttk.Scrollbar(self.schedule_panel, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True);
        scrollbar.pack(side="right", fill="y")
        log_frame = ttk.Frame(paned_window);
        paned_window.add(log_frame, weight=1)
        ttk.Label(log_frame, text="实时日志").pack(anchor="w", padx=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state='disabled', height=10, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=(5, 0), padx=5)
        for tag, color in [('INFO', 'black'), ('WARNING', 'orange'), ('ERROR', 'red'), ('DEBUG', 'gray')]:
            self.log_text.tag_config(tag, foreground=color)
        self.log_text.tag_config('CRITICAL', foreground='red', font=("", 9, "bold"))
        self.task_widgets = {}

    def _initial_load(self):
        """【新增】使用_initial_load钩子来启动循环任务。"""
        self._refresh_ui_status()
        self._process_log_queue()

    def _refresh_ui_status(self):
        try:
            # ... (这部分逻辑完全不变) ...
            master_status = self.scheduler.get_master_status()
            if master_status["is_running"]:
                self.master_status_label.config(text="状态: 运行中", foreground="green")
                self.master_control_button.config(text="停止调度器", command=self.scheduler.stop_scheduler)
                self.schedule_panel.config(text="调度任务列表 (运行中)")
            else:
                self.master_status_label.config(text="状态: 已停止", foreground="red")
                self.master_control_button.config(text="启动调度器", command=self.scheduler.start_scheduler)
                self.schedule_panel.config(text="调度任务列表 (已停止)")
            all_statuses = self.scheduler.get_schedule_status()
            running_task = next((t for t in all_statuses if t.get('status') == 'running'), None)
            queued_count = sum(1 for t in all_statuses if t.get('status') == 'queued')
            self.current_task_label.config(
                text=f"当前运行: {running_task.get('name', 'N/A') if running_task else '无'}",
                foreground="blue" if running_task else "black")
            self.queue_status_label.config(text=f"排队任务: {queued_count}")
            existing_ids = set(self.task_widgets.keys())
            current_ids = {s.get('id') for s in all_statuses if s.get('id')}
            for task_id in existing_ids - current_ids:
                widget_info = self.task_widgets.pop(task_id, None)
                if widget_info and widget_info['frame'].winfo_exists():
                    widget_info['frame'].destroy()
            for status in all_statuses:
                task_id = status.get('id')
                if not task_id: continue
                if task_id not in self.task_widgets:
                    self._create_task_row(status)
                self._update_task_row(status)
        except Exception as e:
            logger.error(f"刷新调度器UI时出错: {e}", exc_info=True)
        finally:
            # 【修改】使用安全的 schedule_update 方法
            self.schedule_update(1000, self._refresh_ui_status, "refresh_status")

    def _create_task_row(self, task_data):
        # ... (这部分逻辑完全不变) ...
        task_id = task_data['id']
        frame = ttk.Frame(self.scrollable_frame, padding=5);
        frame.pack(fill=tk.X, pady=2)
        enabled_var = tk.BooleanVar(value=task_data.get('enabled', False))
        display_text = f"{task_data.get('name', '未命名')} ({task_data.get('plan_name')})"
        ttk.Checkbutton(frame, text=display_text, variable=enabled_var,
                        command=lambda: self.scheduler.toggle_task_enabled(task_id, enabled_var.get())).pack(
            side=tk.LEFT, padx=5)
        status_label = ttk.Label(frame, text="", width=20, anchor="w");
        status_label.pack(side=tk.LEFT, padx=10)
        ttk.Button(frame, text="立即运行", command=lambda: self.scheduler.run_manual_task(task_id)).pack(side=tk.RIGHT,
                                                                                                         padx=5)
        self.task_widgets[task_id] = {'frame': frame, 'enabled_var': enabled_var, 'status_label': status_label}

    def _update_task_row(self, task_data):
        # ... (这部分逻辑完全不变) ...
        widgets = self.task_widgets.get(task_data['id'])
        if not widgets: return
        status = task_data.get('status', 'unknown')
        color = {'running': 'blue', 'queued': 'orange', 'idle': 'green', 'failure': 'red'}.get(status, 'black')
        if status == 'idle' and task_data.get('result') == 'failure': color = 'red'
        widgets['status_label'].config(text=f"状态: {status}", foreground=color)
        widgets['enabled_var'].set(task_data.get('enabled', False))

    def _process_log_queue(self):
        try:
            # 【修改】确保 self.log_queue 存在
            if not self.log_queue: return
            while not self.log_queue.empty():
                record = self.log_queue.get_nowait()
                tag = next((t for t in ['CRITICAL', 'ERROR', 'WARNING', 'DEBUG', 'INFO'] if t in record), 'INFO')
                self.log_text.config(state='normal')
                self.log_text.insert(tk.END, record + '\n', (tag,))
                self.log_text.config(state='disabled')
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        finally:
            # 【修改】使用安全的 schedule_update 方法
            self.schedule_update(100, self._process_log_queue, "process_log")

class TaskRunnerPanel(BasePanel): # 【修改】继承自BasePanel
    def __init__(self, parent, **kwargs):
        # 【修改】使用super().__init__调用基类构造函数
        super().__init__(parent, **kwargs)

    def _create_widgets(self):
        # ... (这部分UI创建代码完全不变) ...
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
        """【新增】使用_initial_load钩子来加载初始数据。"""
        self.reload_all_resources()

    def populate_all(self):
        # ... (这部分逻辑完全不变) ...
        self.populate_tasks()
        self.populate_actions()

    def populate_tasks(self):
        # ... (这部分逻辑完全不变) ...
        self.task_tree.delete(*self.task_tree.get_children())
        try:
            plans = self.scheduler.get_all_plans()
            for plan_name in plans:
                plan_node = self.task_tree.insert('', 'end', text=plan_name, open=False, tags=('plan',))
                tasks = self.scheduler.get_tasks_for_plan(plan_name)
                for task_name in tasks:
                    self.task_tree.insert(plan_node, 'end', text=task_name, tags=('task',))
        except Exception as e:
            messagebox.showerror("错误", f"无法加载方案包列表: {e}")

    def populate_actions(self):
        # ... (这部分逻辑完全不变) ...
        self.action_tree.delete(*self.action_tree.get_children())
        action_defs = self.scheduler.actions.get_all_action_definitions()
        grouped_actions = defaultdict(list)
        for action_def in action_defs:
            namespace = action_def.plugin.canonical_id
            grouped_actions[namespace].append(action_def)
        for namespace, actions in sorted(grouped_actions.items()):
            ns_node = self.action_tree.insert('', 'end', values=(namespace,), open=True, tags=('namespace',))
            for action_def in sorted(actions, key=lambda a: a.name):
                self.action_tree.insert(ns_node, 'end', values=(action_def.name,))
        self.action_tree.tag_configure('namespace', background='#f0f0f0', font=("", 9, "bold"))

    def on_item_double_click(self, event):
        # ... (这部分逻辑完全不变) ...
        item_id = self.task_tree.focus()
        item_tags = self.task_tree.item(item_id, "tags")
        if 'task' in item_tags:
            task_name = self.task_tree.item(item_id, "text")
            parent_id = self.task_tree.parent(item_id)
            plan_name = self.task_tree.item(parent_id, "text")
            if messagebox.askyesno("确认运行", f"确定要立即运行任务 '{task_name}' 吗？\n(来自方案包: {plan_name})"):
                logger.info(f"用户从UI请求运行临时任务: {plan_name}/{task_name}")
                self.scheduler.run_ad_hoc_task(plan_name, task_name)
                try:
                    # 【修改】使用 self.ide 进行更安全的跨面板操作
                    if self.ide and hasattr(self.ide, 'notebook'):
                        self.ide.notebook.select(0)
                except Exception:
                    pass

    def reload_all_resources(self):
        # ... (这部分逻辑完全不变) ...
        try:
            logger.info("UI请求重新加载所有后端资源...")
            self.scheduler.reload_plans()
            self.populate_all()
            logger.info("UI资源列表已刷新。")
        except Exception as e:
            messagebox.showerror("重载失败", f"重新加载资源时发生错误: {e}")
            logger.error(f"UI重载失败: {e}", exc_info=True)


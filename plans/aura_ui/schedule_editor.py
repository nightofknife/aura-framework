# src/ui/schedule_editor.py

import tkinter as tk
from tkinter import ttk, messagebox


class ScheduleEditorWindow(tk.Toplevel):
    """一个用于可视化增删改查 schedule.yaml 内容的窗口。"""

    def __init__(self, parent, scheduler):
        super().__init__(parent)
        self.scheduler = scheduler
        self.title("调度管理器")
        self.geometry("1000x600")

        self.current_item_id = None
        self.plan_tasks_cache = {}

        self._create_widgets()
        self.populate_schedule_list()

        # 窗口关闭时，确保保存未保存的更改
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _create_widgets(self):
        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- 左侧：任务列表 ---
        left_frame = ttk.Frame(main_pane)
        main_pane.add(left_frame, weight=1)

        list_toolbar = ttk.Frame(left_frame)
        list_toolbar.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(list_toolbar, text="＋ 添加任务", command=self.add_new_item).pack(side=tk.LEFT)
        ttk.Button(list_toolbar, text="－ 删除任务", command=self.delete_selected_item).pack(side=tk.LEFT, padx=5)

        columns = ("enabled", "name", "plan_name", "trigger")
        self.tree = ttk.Treeview(left_frame, columns=columns, show="headings")
        self.tree.heading("enabled", text="启用")
        self.tree.heading("name", text="任务名称")
        self.tree.heading("plan_name", text="所属方案")
        self.tree.heading("trigger", text="触发器")
        self.tree.column("enabled", width=50, anchor='center')
        self.tree.column("name", width=150)
        self.tree.column("plan_name", width=100)
        self.tree.column("trigger", width=150)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_item_select)

        # --- 右侧：属性编辑器 ---
        right_frame = ttk.Frame(main_pane)
        main_pane.add(right_frame, weight=2)

        self.editor_notebook = ttk.Notebook(right_frame)
        self.editor_notebook.pack(fill=tk.BOTH, expand=True)

        # 创建各个属性的 StringVar 等
        self.vars = {
            'name': tk.StringVar(), 'description': tk.StringVar(), 'enabled': tk.BooleanVar(),
            'plan_name': tk.StringVar(), 'task': tk.StringVar(),
            'trigger_type': tk.StringVar(value='manual'), 'trigger_schedule': tk.StringVar(),
            'cooldown': tk.StringVar(value='0')
        }

        # Tab 1: 基本设置
        basic_tab = ttk.Frame(self.editor_notebook, padding=10)
        self.editor_notebook.add(basic_tab, text="基本设置")
        self.create_basic_editor(basic_tab)

        # Tab 2: 触发器
        trigger_tab = ttk.Frame(self.editor_notebook, padding=10)
        self.editor_notebook.add(trigger_tab, text="触发器")
        self.create_trigger_editor(trigger_tab)

        # 保存按钮
        ttk.Button(right_frame, text="应用更改", command=self.save_current_item).pack(pady=10)

    def create_basic_editor(self, parent):
        # ... (UI元素创建)
        ttk.Label(parent, text="任务名称:").grid(row=0, column=0, sticky='w', pady=2)
        ttk.Entry(parent, textvariable=self.vars['name']).grid(row=0, column=1, sticky='ew', pady=2)

        ttk.Checkbutton(parent, text="启用此调度任务", variable=self.vars['enabled']).grid(row=1, column=0,
                                                                                           columnspan=2, sticky='w',
                                                                                           pady=5)

        ttk.Label(parent, text="所属方案:").grid(row=2, column=0, sticky='w', pady=2)
        self.plan_combo = ttk.Combobox(parent, textvariable=self.vars['plan_name'], state='readonly')
        self.plan_combo['values'] = self.scheduler.get_all_plans()
        self.plan_combo.grid(row=2, column=1, sticky='ew', pady=2)
        self.plan_combo.bind("<<ComboboxSelected>>", self.on_plan_change)

        ttk.Label(parent, text="执行任务:").grid(row=3, column=0, sticky='w', pady=2)
        self.task_combo = ttk.Combobox(parent, textvariable=self.vars['task'], state='readonly')
        self.task_combo.grid(row=3, column=1, sticky='ew', pady=2)

        ttk.Label(parent, text="描述:").grid(row=4, column=0, sticky='nw', pady=2)
        ttk.Entry(parent, textvariable=self.vars['description']).grid(row=4, column=1, sticky='ew', pady=2)

        ttk.Label(parent, text="冷却时间 (秒):").grid(row=5, column=0, sticky='w', pady=2)
        ttk.Entry(parent, textvariable=self.vars['cooldown']).grid(row=5, column=1, sticky='ew', pady=2)

        parent.columnconfigure(1, weight=1)

    def create_trigger_editor(self, parent):
        ttk.Label(parent, text="触发器类型:").grid(row=0, column=0, sticky='w', pady=2)
        trigger_combo = ttk.Combobox(parent, textvariable=self.vars['trigger_type'], values=['manual', 'time_based'],
                                     state='readonly')
        trigger_combo.grid(row=0, column=1, sticky='ew', pady=2)
        trigger_combo.bind("<<ComboboxSelected>>", self.on_trigger_type_change)

        self.schedule_label = ttk.Label(parent, text="Cron 表达式:")
        self.schedule_entry = ttk.Entry(parent, textvariable=self.vars['trigger_schedule'])

        self.on_trigger_type_change()  # 初始化显示

    def on_trigger_type_change(self, event=None):
        if self.vars['trigger_type'].get() == 'time_based':
            self.schedule_label.grid(row=1, column=0, sticky='w', pady=5)
            self.schedule_entry.grid(row=1, column=1, sticky='ew', pady=5)
        else:
            self.schedule_label.grid_remove()
            self.schedule_entry.grid_remove()

    def populate_schedule_list(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

        items = self.scheduler.get_schedule_status()
        for item in items:
            enabled_char = "✔" if item.get('enabled', False) else "✖"
            trigger = item.get('trigger', {})
            trigger_desc = trigger.get('type', 'manual')
            if trigger_desc == 'time_based':
                trigger_desc = f"cron: {trigger.get('schedule', 'N/A')}"

            self.tree.insert('', 'end', iid=item['id'],
                             values=(enabled_char, item['name'], item['plan_name'], trigger_desc))

    def on_item_select(self, event=None):
        selected_items = self.tree.selection()
        if not selected_items:
            self.current_item_id = None
            self.clear_editor()
            return

        self.current_item_id = selected_items[0]
        item_data = next((item for item in self.scheduler.get_schedule_status() if item['id'] == self.current_item_id),
                         None)

        if item_data:
            self.load_data_to_editor(item_data)

    def on_plan_change(self, event=None):
        plan_name = self.vars['plan_name'].get()
        if not plan_name:
            self.task_combo['values'] = []
            return

        if plan_name not in self.plan_tasks_cache:
            self.plan_tasks_cache[plan_name] = self.scheduler.get_tasks_for_plan(plan_name)

        self.task_combo['values'] = self.plan_tasks_cache[plan_name]
        # 如果当前任务不在新方案的任务列表里，则清空
        if self.vars['task'].get() not in self.task_combo['values']:
            self.vars['task'].set('')

    def load_data_to_editor(self, data):
        self.vars['name'].set(data.get('name', ''))
        self.vars['description'].set(data.get('description', ''))
        self.vars['enabled'].set(data.get('enabled', False))
        self.vars['plan_name'].set(data.get('plan_name', ''))
        self.on_plan_change()  # 触发任务列表更新
        self.vars['task'].set(data.get('task', ''))

        trigger = data.get('trigger', {})
        self.vars['trigger_type'].set(trigger.get('type', 'manual'))
        self.vars['trigger_schedule'].set(trigger.get('schedule', ''))
        self.on_trigger_type_change()

        run_options = data.get('run_options', {})
        self.vars['cooldown'].set(str(run_options.get('cooldown', 0)))

    def clear_editor(self):
        for var in self.vars.values():
            if isinstance(var, tk.BooleanVar):
                var.set(False)
            else:
                var.set('')
        self.vars['trigger_type'].set('manual')
        self.on_trigger_type_change()

    def add_new_item(self):
        # 需要用户先选择一个方案
        all_plans = self.scheduler.get_all_plans()
        if not all_plans:
            messagebox.showerror("错误", "没有可用的方案包，无法添加新任务。")
            return

        # 默认使用第一个方案
        default_plan = all_plans[0]
        new_item_data = {
            'name': '新调度任务',
            'plan_name': default_plan,
            'enabled': True,
            'trigger': {'type': 'manual'}
        }

        try:
            result = self.scheduler.add_schedule_item(new_item_data)
            if result.get('status') == 'success':
                new_item = result['new_item']
                self.populate_schedule_list()
                self.tree.selection_set(new_item['id'])  # 自动选中新创建的项
        except Exception as e:
            messagebox.showerror("错误", f"添加任务失败: {e}")

    def delete_selected_item(self):
        if not self.current_item_id:
            messagebox.showwarning("警告", "请先选择一个要删除的任务。")
            return

        if messagebox.askyesno("确认删除", f"确定要删除任务 '{self.vars['name'].get()}' 吗？此操作不可撤销。"):
            try:
                self.scheduler.delete_schedule_item(self.current_item_id)
                self.populate_schedule_list()
                self.clear_editor()
            except Exception as e:
                messagebox.showerror("错误", f"删除任务失败: {e}")

    def save_current_item(self):
        if not self.current_item_id:
            messagebox.showwarning("警告", "没有选中的任务可供保存。")
            return

        # 从UI控件收集数据
        data_to_save = {
            'name': self.vars['name'].get(),
            'description': self.vars['description'].get(),
            'enabled': self.vars['enabled'].get(),
            'plan_name': self.vars['plan_name'].get(),
            'task': self.vars['task'].get(),
            'trigger': {
                'type': self.vars['trigger_type'].get(),
                'schedule': self.vars['trigger_schedule'].get() if self.vars[
                                                                       'trigger_type'].get() == 'time_based' else None
            },
            'run_options': {
                'cooldown': int(self.vars['cooldown'].get() or 0)
            }
        }

        try:
            self.scheduler.update_schedule_item(self.current_item_id, data_to_save)
            messagebox.showinfo("成功", "任务已成功保存！")
            self.populate_schedule_list()  # 刷新列表以显示更改
        except Exception as e:
            messagebox.showerror("错误", f"保存任务失败: {e}")

    def on_close(self):
        # 这里可以添加逻辑，检查是否有未保存的更改
        self.destroy()

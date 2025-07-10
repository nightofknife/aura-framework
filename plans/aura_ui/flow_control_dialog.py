# plans/aura_ui/flow_control_dialog.py
import tkinter as tk
from tkinter import ttk


class FlowControlDialog(tk.Toplevel):
    """
    一个统一的对话框，用于设置步骤的流程控制指令 (go_step, go_task, next)。
    """

    def __init__(self, parent, step_data, all_steps_in_task, all_task_names):
        super().__init__(parent)
        self.transient(parent)
        self.title(f"编辑流程控制")
        self.geometry("450x250")
        self.resizable(False, False)

        self.step_data = step_data
        self.all_steps_in_task = all_steps_in_task
        self.all_task_names = all_task_names
        self.result = None

        self.vars = {
            'go_step': tk.StringVar(value=self.step_data.get('go_step', '')),
            'go_task': tk.StringVar(value=self.step_data.get('go_task', '')),
            'next': tk.StringVar(value=self.step_data.get('next', ''))
        }

        self._create_widgets()
        self.grab_set()
        self.wait_window(self)

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- go_step ---
        ttk.Label(main_frame, text="任务内跳转 (go_step):", font=('Segoe UI', 10, 'bold')).grid(row=0, column=0,
                                                                                                sticky='w', pady=(0, 5))
        step_options = ["-- 无跳转 --"] + [f"{s.get('name', '未命名')} ({s['id']})" for s in self.all_steps_in_task if
                                           s.get('id') != self.step_data.get('id')]
        self.go_step_combo = ttk.Combobox(main_frame, textvariable=self.vars['go_step'], values=step_options,
                                          state='readonly')
        self.go_step_combo.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(0, 15))
        # 设置初始显示值
        self._set_initial_combobox_text(self.go_step_combo, self.vars['go_step'].get(), self.all_steps_in_task)

        # --- go_task ---
        ttk.Label(main_frame, text="跨任务跳转 (go_task):", font=('Segoe UI', 10, 'bold')).grid(row=2, column=0,
                                                                                                sticky='w', pady=(0, 5))
        task_options = ["-- 无跳转 --"] + self.all_task_names
        self.go_task_combo = ttk.Combobox(main_frame, textvariable=self.vars['go_task'], values=task_options,
                                          state='readonly')
        self.go_task_combo.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(0, 15))

        # --- next ---
        ttk.Label(main_frame, text="计划性衔接 (next):", font=('Segoe UI', 10, 'bold')).grid(row=4, column=0,
                                                                                             sticky='w', pady=(0, 5))
        self.next_combo = ttk.Combobox(main_frame, textvariable=self.vars['next'], values=task_options,
                                       state='readonly')
        self.next_combo.grid(row=5, column=0, columnspan=2, sticky='ew')

        main_frame.columnconfigure(0, weight=1)

        # --- Buttons ---
        btn_frame = ttk.Frame(self, padding=(10, 0, 10, 10))
        btn_frame.pack(fill='x')
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side='right', padx=5)
        ttk.Button(btn_frame, text="确定", command=self.on_ok, style="Accent.TButton").pack(side='right')

    def _set_initial_combobox_text(self, combobox, value_id, item_list):
        """为go_step设置初始显示的文本"""
        if not value_id:
            combobox.set("-- 无跳转 --")
            return
        for item in item_list:
            if item.get('id') == value_id:
                combobox.set(f"{item.get('name', '未命名')} ({item['id']})")
                return
        combobox.set("-- 无跳转 --")  # 如果找不到ID，也设为无

    def on_ok(self):
        self.result = {}

        # 处理 go_step
        go_step_val = self.vars['go_step'].get()
        if go_step_val and go_step_val != "-- 无跳转 --":
            # 从 "Name (id)" 中提取 id
            self.result['go_step'] = go_step_val.split('(')[-1].strip(')')

        # 处理 go_task
        go_task_val = self.vars['go_task'].get()
        if go_task_val and go_task_val != "-- 无跳转 --":
            self.result['go_task'] = go_task_val

        # 处理 next
        next_val = self.vars['next'].get()
        if next_val and next_val != "-- 无跳转 --":
            self.result['next'] = next_val

        self.destroy()


# plans/aura_ui/node_properties_dialog.py (v3.0 - 兼容性微调)

import tkinter as tk
from tkinter import ttk
import json


class NodePropertiesDialog(tk.Toplevel):
    def __init__(self, parent, title, step_data, scheduler):
        super().__init__(parent)
        self.transient(parent)
        self.title(title)
        self.parent = parent
        self.result = None

        self.step_data = step_data.copy()
        self.scheduler = scheduler
        self.initial_focus = None

        # --- 为所有变量创建 tk Vars ---
        self.common_vars = {
            'name': tk.StringVar(value=self.step_data.get('name', '')),
            'when': tk.StringVar(value=self.step_data.get('when', '')),
            'output_to': tk.StringVar(value=self.step_data.get('output_to', '')),
            'wait_before': tk.StringVar(value=self.step_data.get('wait_before', '')),
            'continue_on_failure': tk.BooleanVar(value=self.step_data.get('continue_on_failure', False)),
        }

        retry_data = self.step_data.get('retry')
        if isinstance(retry_data, dict):
            retry_enabled, retry_count, retry_interval = True, str(retry_data.get('count', '3')), str(
                retry_data.get('interval', '1.0'))
        elif isinstance(retry_data, (int, float, str)):
            retry_enabled, retry_count, retry_interval = True, str(retry_data), '1.0'
        else:
            retry_enabled, retry_count, retry_interval = False, '3', '1.0'

        self.retry_vars = {
            'enabled': tk.BooleanVar(value=retry_enabled),
            'count': tk.StringVar(value=retry_count),
            'interval': tk.StringVar(value=retry_interval),
        }
        self.param_vars = {}
        self.logic_vars = {}

        body = ttk.Frame(self)
        self.body(body)
        body.pack(padx=10, pady=10)

        self.buttonbox()
        self.grab_set()

        if self.initial_focus:
            self.initial_focus.focus_set()
        else:
            self.focus_set()

        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.geometry(f"+{parent.winfo_rootx() + 50}+{parent.winfo_rooty() + 50}")
        self.wait_window(self)

    def body(self, master):
        self._create_common_options_editor(master)

        if 'if' in self.step_data:
            self._create_if_editor(master)
        elif 'for' in self.step_data:
            self._create_for_editor(master)
        elif 'action' in self.step_data:
            self._create_action_editor(master)

    def _create_action_editor(self, master):
        params_frame = ttk.LabelFrame(master, text="行为参数 (Params)", padding=10)
        params_frame.pack(fill=tk.X, expand=True, pady=5, ipady=5)
        params_frame.columnconfigure(1, weight=1)

        action_name = self.step_data.get('action')
        action_sig = self.scheduler.get_action_signature(action_name)
        if not action_sig:
            ttk.Label(params_frame, text=f"警告: 无法找到行为 '{action_name}' 的签名。").pack()
            return

        current_params = self.step_data.get('params', {})
        params_list = action_sig.get('parameters', [])
        if not params_list:
            ttk.Label(params_frame, text="此行为无需额外参数。").pack()
            return

        for i, param_info in enumerate(params_list):
            param_name = param_info['name']
            ttk.Label(params_frame, text=f"{param_name}:").grid(row=i, column=0, sticky="w", pady=2, padx=5)

            default_val = param_info.get('default_value', '')
            if isinstance(default_val, (dict, list)): default_val = json.dumps(default_val)

            val = current_params.get(param_name, default_val)
            if not isinstance(val, str): val = json.dumps(val)

            param_var = tk.StringVar(value=val)
            self.param_vars[param_name] = param_var
            entry = ttk.Entry(params_frame, textvariable=param_var)
            entry.grid(row=i, column=1, sticky="ew", pady=2, padx=5)
            if i == 0 and not self.initial_focus: self.initial_focus = entry

    def _create_if_editor(self, master):
        logic_frame = ttk.LabelFrame(master, text="If 条件", padding=10)
        logic_frame.pack(fill=tk.X, expand=True, pady=5, ipady=5)
        logic_frame.columnconfigure(1, weight=1)
        ttk.Label(logic_frame, text="条件表达式:").grid(row=0, column=0, sticky="w", pady=2, padx=5)
        if_var = tk.StringVar(value=self.step_data.get('if', ''))
        self.logic_vars['if'] = if_var
        entry = ttk.Entry(logic_frame, textvariable=if_var)
        entry.grid(row=0, column=1, sticky="ew")
        if not self.initial_focus: self.initial_focus = entry

    def _create_for_editor(self, master):
        logic_frame = ttk.LabelFrame(master, text="For 循环", padding=10)
        logic_frame.pack(fill=tk.X, expand=True, pady=5, ipady=5)
        logic_frame.columnconfigure(1, weight=1)
        for_data = self.step_data.get('for', {})
        ttk.Label(logic_frame, text="迭代变量名 (as):").grid(row=0, column=0, sticky="w", pady=2, padx=5)
        as_var = tk.StringVar(value=for_data.get('as', 'item'))
        self.logic_vars['as'] = as_var
        as_entry = ttk.Entry(logic_frame, textvariable=as_var)
        as_entry.grid(row=0, column=1, sticky="ew", padx=5)
        if not self.initial_focus: self.initial_focus = as_entry
        ttk.Label(logic_frame, text="迭代对象 (in):").grid(row=1, column=0, sticky="w", pady=2, padx=5)
        in_var = tk.StringVar(value=for_data.get('in', ''))
        self.logic_vars['in'] = in_var
        ttk.Entry(logic_frame, textvariable=in_var).grid(row=1, column=1, sticky="ew", padx=5)

    def _create_common_options_editor(self, master):
        common_frame = ttk.LabelFrame(master, text="通用执行选项", padding=10)
        common_frame.pack(fill=tk.X, expand=True, pady=5, ipady=5)
        common_frame.columnconfigure(1, weight=1)
        ttk.Label(common_frame, text="节点名称:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        name_entry = ttk.Entry(common_frame, textvariable=self.common_vars['name'])
        name_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=5)
        if not self.initial_focus: self.initial_focus = name_entry
        ttk.Label(common_frame, text="执行条件 (when):").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(common_frame, textvariable=self.common_vars['when']).grid(row=1, column=1, columnspan=2, sticky="ew",
                                                                            padx=5)
        ttk.Label(common_frame, text="输出到变量 (output_to):").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(common_frame, textvariable=self.common_vars['output_to']).grid(row=2, column=1, columnspan=2,
                                                                                 sticky="ew", padx=5)
        ttk.Label(common_frame, text="执行前等待 (秒):").grid(row=3, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(common_frame, textvariable=self.common_vars['wait_before']).grid(row=3, column=1, columnspan=2,
                                                                                   sticky="ew", padx=5)
        retry_check = ttk.Checkbutton(common_frame, text="失败后重试", variable=self.retry_vars['enabled'],
                                      command=self._toggle_retry_widgets)
        retry_check.grid(row=4, column=0, sticky='w', padx=5, pady=5)
        self.retry_count_label = ttk.Label(common_frame, text="次数:")
        self.retry_count_entry = ttk.Entry(common_frame, textvariable=self.retry_vars['count'], width=5)
        self.retry_interval_label = ttk.Label(common_frame, text="间隔(秒):")
        self.retry_interval_entry = ttk.Entry(common_frame, textvariable=self.retry_vars['interval'], width=5)
        self.retry_count_label.grid(row=5, column=0, sticky='e', padx=(20, 2))
        self.retry_count_entry.grid(row=5, column=1, sticky='w')
        self.retry_interval_label.grid(row=5, column=1, sticky='e', padx=(20, 2))
        self.retry_interval_entry.grid(row=5, column=2, sticky='w')
        ttk.Checkbutton(common_frame, text="失败后继续执行 (continue_on_failure)",
                        variable=self.common_vars['continue_on_failure']).grid(row=6, column=0, columnspan=3,
                                                                               sticky='w', padx=5, pady=5)
        self._toggle_retry_widgets()

    def _toggle_retry_widgets(self):
        state = 'normal' if self.retry_vars['enabled'].get() else 'disabled'
        for widget in [self.retry_count_label, self.retry_count_entry, self.retry_interval_label,
                       self.retry_interval_entry]:
            widget.config(state=state)

    def buttonbox(self):
        box = ttk.Frame(self)
        w = ttk.Button(box, text="确定", width=10, command=self.ok, default=tk.ACTIVE)
        w.pack(side=tk.LEFT, padx=5, pady=5)
        w = ttk.Button(box, text="取消", width=10, command=self.cancel)
        w.pack(side=tk.LEFT, padx=5, pady=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        box.pack()

    def ok(self, event=None):
        self.withdraw()
        self.update_idletasks()
        self.apply()
        self.cancel()

    def cancel(self, event=None):
        self.parent.focus_set()
        self.destroy()

    def apply(self):
        for key, var in self.common_vars.items():
            value = var.get()
            if value or (isinstance(value, bool) and value is True):
                self.step_data[key] = value
            elif key in self.step_data:
                del self.step_data[key]

        if self.retry_vars['enabled'].get():
            try:
                count = int(self.retry_vars['count'].get())
                if self.retry_vars['interval'].get() in ['1.0', '1']:
                    self.step_data['retry'] = count
                else:
                    self.step_data['retry'] = {'count': count, 'interval': float(self.retry_vars['interval'].get())}
            except (ValueError, TypeError):
                self.step_data.pop('retry', None)
        elif 'retry' in self.step_data:
            del self.step_data['retry']

        if 'action' in self.step_data:
            params = {}
            for name, var in self.param_vars.items():
                val_str = var.get()
                if val_str:
                    try:
                        params[name] = json.loads(val_str)
                    except (json.JSONDecodeError, TypeError):
                        params[name] = val_str
            if params:
                self.step_data['params'] = params
            elif 'params' in self.step_data:
                del self.step_data['params']

        if 'if' in self.step_data: self.step_data['if'] = self.logic_vars['if'].get()
        if 'for' in self.step_data: self.step_data['for'] = {'as': self.logic_vars['as'].get(),
                                                             'in': self.logic_vars['in'].get()}

        self.result = self.step_data

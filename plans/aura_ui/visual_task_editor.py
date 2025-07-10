# plans/aura_ui/visual_task_editor.py (优化版 v3.5.0)

import tkinter as tk
from tkinter import ttk, messagebox
import uuid
import yaml

# 【修改】导入 BasePanel
from .base_panel import BasePanel
from .node_properties_dialog import NodePropertiesDialog
from .flow_control_dialog import FlowControlDialog


class VisualTaskEditor(BasePanel):  # 【修改】继承自 BasePanel
    # 【核心修正】改造构造函数以匹配 BasePanel 体系
    def __init__(self, parent, scheduler, ide, **kwargs):
        # 从 kwargs 中提取本类特有的参数
        self.plan_name = kwargs.get('plan_name')
        self.file_path = kwargs.get('file_path')
        self.task_name = kwargs.get('task_name')
        self.task_data = kwargs.get('task_data')

        if self.task_data is None:
            self.task_data = {}
        self.task_data.setdefault('steps', [])

        # 调用父类的构造函数，传递核心依赖
        super().__init__(parent, scheduler, ide, **kwargs)

    # 【新增】重写 destroy 方法，以包含自定义的清理逻辑
    def destroy(self):
        # 执行本类特有的清理（如解绑全局事件）
        try:
            self.unbind_all("<MouseWheel>")
        except tk.TclError:
            # 如果窗口已经销毁，可能会报错，安全地忽略
            pass
        # 调用父类的destroy，它会负责取消所有 after 循环
        super().destroy()

    # 【修改】将样式配置移入 _create_widgets，或作为一个独立的私有方法
    def _configure_styles(self):
        style = ttk.Style()
        style.configure("Card.TFrame", background="white", borderwidth=1, relief='solid')
        style.configure("Inner.TFrame", background="white")
        style.configure("Case.TFrame", background="#f8f9fa", borderwidth=1, relief='groove')
        style.configure("Card.TLabel", background="white", font=('Segoe UI', 9))
        style.configure("Branch.TLabel", background="white", font=('Segoe UI', 9, 'italic'), foreground='gray50')
        style.configure("Case.TLabel", background="#f8f9fa", font=('Segoe UI', 9, 'bold'))
        style.configure("Mini.TButton", padding=(2, 2), font=('Segoe UI', 8))
        style.configure("Move.TButton", padding=(1, 1), font=('Segoe UI', 10))
        style.configure("Flow.TLabel", background="#e7f5ff", foreground="#00529B", font=('Segoe UI', 8), borderwidth=1,
                        relief='solid', padding=2)
        style.configure("Skipped.TFrame", background="gray90", borderwidth=1, relief='dashed')
        style.configure("Skipped.TLabel", background="gray90")

    # 【修改】将UI创建逻辑放入 _create_widgets
    def _create_widgets(self):
        self.step_widgets = {}
        self._configure_styles()

        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True)

        toolbox_frame = ttk.LabelFrame(main_pane, text="工具箱", padding=5)
        main_pane.add(toolbox_frame, weight=1)

        ttk.Label(toolbox_frame, text="行为 (双击添加)").pack(anchor='w')
        action_list_frame = ttk.Frame(toolbox_frame)
        action_list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.action_list = tk.Listbox(action_list_frame, exportselection=False)
        action_scrollbar = ttk.Scrollbar(action_list_frame, orient="vertical", command=self.action_list.yview)
        self.action_list.config(yscrollcommand=action_scrollbar.set)
        action_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.action_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.action_list.bind("<Double-Button-1>", lambda e: self._on_toolbox_double_click(e, 'action'))

        ttk.Label(toolbox_frame, text="逻辑 (双击添加)").pack(anchor='w')
        self.logic_list = tk.Listbox(toolbox_frame, exportselection=False, height=4)
        self.logic_list.pack(fill=tk.X, pady=5)
        self.logic_list.insert(tk.END, "If-Else Block")
        self.logic_list.insert(tk.END, "For Loop Block")
        self.logic_list.insert(tk.END, "While Loop")
        self.logic_list.insert(tk.END, "Switch Block")
        self.logic_list.bind("<Double-Button-1>", lambda e: self._on_toolbox_double_click(e, 'logic'))

        editor_frame = ttk.Frame(main_pane)
        main_pane.add(editor_frame, weight=5)

        self.canvas = tk.Canvas(editor_frame, bg="gray95", highlightthickness=0)
        scrollbar = ttk.Scrollbar(editor_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 绑定滚轮事件
        self.bind_all("<MouseWheel>", self._on_mousewheel)

    # 【修改】将数据加载逻辑放入 _initial_load
    def _initial_load(self):
        self.update_actions_list()
        self.load_and_render()

    # --- 以下所有其他方法保持不变 ---
    # (为了简洁，这里省略了未变动的方法体，请保留你文件中的这些方法)
    def _on_mousewheel(self, event):
        # 检查鼠标是否在canvas区域内
        if str(self.canvas.winfo_containing(event.x_root, event.y_root)).startswith(str(self.canvas)):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def update_actions_list(self):
        self.action_list.delete(0, tk.END)
        actions = self.scheduler.get_all_actions_with_signatures()
        for action_name in sorted(actions.keys()):
            self.action_list.insert(tk.END, action_name)

    def load_and_render(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.step_widgets.clear()

        skipped_ids = self._analyze_flow_for_skipped_steps(self.task_data['steps'])

        self._render_step_list(self.task_data['steps'], self.scrollable_frame, 0, skipped_ids)
        add_button = ttk.Button(self.scrollable_frame, text="+ 添加顶层步骤",
                                command=lambda: self.show_add_step_menu(self.task_data['steps'], add_button))
        add_button.pack(pady=10, padx=20, fill='x')

    def _render_step_list(self, steps, parent_widget, depth, skipped_ids):
        for i, step_data in enumerate(steps):
            step_data.setdefault('id', str(uuid.uuid4()))
            step_id = step_data['id']
            is_skipped = step_id in skipped_ids
            widget = StepWidget(parent_widget, self, step_data, depth, i, len(steps), is_skipped)
            widget.pack(fill='x', padx=(depth * 20, 0), pady=2)
            self.step_widgets[step_id] = widget

    def _is_definitive_jumper(self, step_data):
        if 'go_step' in step_data or 'go_task' in step_data:
            return True
        if 'if' in step_data:
            then_block = step_data.get('then', [])
            else_block = step_data.get('else', [])
            if not else_block:
                return False
            then_jumps = False
            if then_block:
                last_then_step = then_block[-1]
                if self._is_definitive_jumper(last_then_step):
                    then_jumps = True
            else_jumps = False
            if else_block:
                last_else_step = else_block[-1]
                if self._is_definitive_jumper(last_else_step):
                    else_jumps = True
            return then_jumps and else_jumps
        return False

    def _analyze_flow_for_skipped_steps(self, steps_list):
        skipped_ids = set()
        flow_is_broken = False
        for step in steps_list:
            if flow_is_broken:
                skipped_ids.add(step['id'])
            for child_key in ['then', 'else', 'do', 'default']:
                if child_key in step:
                    skipped_ids.update(self._analyze_flow_for_skipped_steps(step[child_key]))
            if 'cases' in step:
                for case in step['cases']:
                    skipped_ids.update(self._analyze_flow_for_skipped_steps(case.get('then', [])))
            if self._is_definitive_jumper(step):
                flow_is_broken = True
        return skipped_ids

    def show_add_step_menu(self, target_list, button):
        menu = tk.Menu(self, tearoff=0)
        action_menu = tk.Menu(menu, tearoff=0)
        for i in range(self.action_list.size()):
            action_name = self.action_list.get(i)
            action_menu.add_command(label=action_name,
                                    command=lambda name=action_name: self.add_step(target_list, 'action', name))
        menu.add_cascade(label="添加行为", menu=action_menu)
        menu.add_separator()
        menu.add_command(label="添加 If-Else 块", command=lambda: self.add_step(target_list, 'if'))
        menu.add_command(label="添加 For 循环块", command=lambda: self.add_step(target_list, 'for'))
        menu.add_command(label="添加 While 循环", command=lambda: self.add_step(target_list, 'while'))
        menu.add_command(label="添加 Switch 块", command=lambda: self.add_step(target_list, 'switch'))
        x, y = button.winfo_rootx(), button.winfo_rooty() + button.winfo_height()
        menu.post(x, y)

    def add_step(self, target_list, step_type, action_name=None):
        new_step = {'id': str(uuid.uuid4())}
        if step_type == 'action':
            new_step.update({'action': action_name or 'log', 'name': f"新的 {action_name or 'log'}"})
        elif step_type == 'if':
            new_step.update({'if': '{{ True }}', 'then': [], 'else': []})
        elif step_type == 'for':
            new_step.update({'for': {'as': 'item', 'in': '[]'}, 'do': []})
        elif step_type == 'while':
            new_step.update({'while': '{{ True }}', 'do': []})
        elif step_type == 'switch':
            new_step.update({'switch': '{{ value }}', 'cases': [], 'default': []})
        target_list.append(new_step)
        self.load_and_render()

    def add_case_to_switch(self, switch_step_data):
        new_case = {'id': str(uuid.uuid4()), 'case': '""', 'then': []}
        switch_step_data.setdefault('cases', []).append(new_case)
        self.load_and_render()

    def _on_toolbox_double_click(self, event, item_type):
        listbox = self.action_list if item_type == 'action' else self.logic_list
        selection = listbox.curselection()
        if not selection: return
        item_name = listbox.get(selection[0])
        action_name = item_name if item_type == 'action' else None
        step_type_map = {"If-Else Block": "if", "For Loop Block": "for", "While Loop": "while",
                         "Switch Block": "switch"}
        step_type = step_type_map.get(item_name, 'action')
        self.add_step(self.task_data['steps'], step_type, action_name)

    def edit_step(self, step_data):
        dialog = NodePropertiesDialog(self, f"编辑步骤", step_data, self.scheduler)
        if dialog.result:
            for key in list(step_data.keys()):
                if key not in ['id', 'then', 'else', 'do', 'cases', 'default', 'case'] and key not in dialog.result:
                    del step_data[key]
            step_data.update(dialog.result)
            self.load_and_render()

    def delete_step(self, step_id):
        if messagebox.askyesno("确认删除", "确定要删除这个步骤及其所有子步骤吗？"):
            self._find_and_remove_step(self.task_data, step_id)
            self.load_and_render()

    def _find_and_remove_step(self, parent_data, step_id):
        possible_lists = ['steps', 'then', 'else', 'do', 'default']
        for key in possible_lists:
            if key in parent_data and isinstance(parent_data[key], list):
                steps_list = parent_data[key]
                for i, step in enumerate(steps_list):
                    if step.get('id') == step_id:
                        del steps_list[i]
                        return True
                    if self._find_and_remove_step(step, step_id): return True
        if 'cases' in parent_data:
            for i, case in enumerate(parent_data['cases']):
                if case.get('id') == step_id:
                    del parent_data['cases'][i]
                    return True
                if self._find_and_remove_step(case, step_id): return True
        return False

    def save(self):
        try:
            if self.task_name:
                self.scheduler.update_task_in_file(self.plan_name, self.file_path, self.task_name, self.task_data)
            else:
                content = yaml.dump(self.task_data, allow_unicode=True, sort_keys=False, default_flow_style=False)
                self.scheduler.save_file_content(self.plan_name, self.file_path, content)
            messagebox.showinfo("成功", "任务已成功保存！", parent=self)
        except Exception as e:
            messagebox.showerror("保存失败", f"保存任务时出错:\n{e}", parent=self)
            raise

    def _get_all_steps_in_task(self, steps_list=None):
        if steps_list is None:
            steps_list = self.task_data['steps']
        all_steps = []
        for step in steps_list:
            all_steps.append(step)
            for child_key in ['then', 'else', 'do', 'default']:
                if child_key in step and isinstance(step[child_key], list):
                    all_steps.extend(self._get_all_steps_in_task(step[child_key]))
            if 'cases' in step and isinstance(step['cases'], list):
                for case in step['cases']:
                    all_steps.append(case)
                    if 'then' in case and isinstance(case['then'], list):
                        all_steps.extend(self._get_all_steps_in_task(case['then']))
        return all_steps

    def open_flow_control_dialog(self, step_id):
        step_data = self.step_widgets[step_id].step_data
        all_steps = self._get_all_steps_in_task()
        all_tasks = sorted(list(self.scheduler.all_tasks_definitions.keys()))
        dialog = FlowControlDialog(self, step_data, all_steps, all_tasks)
        if dialog.result is not None:
            for key in ['go_step', 'go_task', 'next']:
                if key in step_data:
                    del step_data[key]
            step_data.update(dialog.result)
            self.load_and_render()

    def move_step(self, step_id, direction):
        found, parent_list, index = self._find_step_parent_and_index(self.task_data, step_id)
        if not found: return
        if direction == 'up':
            if index > 0:
                parent_list[index], parent_list[index - 1] = parent_list[index - 1], parent_list[index]
        elif direction == 'down':
            if index < len(parent_list) - 1:
                parent_list[index], parent_list[index + 1] = parent_list[index + 1], parent_list[index]
        elif direction == 'indent':
            if index > 0:
                prev_sibling = parent_list[index - 1]
                if any(k in prev_sibling for k in ['if', 'for', 'while', 'switch']):
                    step_to_move = parent_list.pop(index)
                    if 'if' in prev_sibling:
                        prev_sibling.setdefault('then', []).append(step_to_move)
                    elif 'switch' in prev_sibling:
                        prev_sibling.setdefault('cases', [])[0].setdefault('then', []).append(step_to_move)
                    else:
                        prev_sibling.setdefault('do', []).append(step_to_move)
        elif direction == 'outdent':
            grandparent_found, grandparent_list, parent_index = self._find_step_parent_and_index(self.task_data,
                                                                                                 found['parent_id'])
            if grandparent_found:
                step_to_move = parent_list.pop(index)
                grandparent_list.insert(parent_index + 1, step_to_move)
        self.load_and_render()

    def _find_step_parent_and_index(self, current_data, step_id, parent_id=None):
        possible_lists = ['steps', 'then', 'else', 'do', 'default']
        for key in possible_lists:
            if key in current_data and isinstance(current_data[key], list):
                steps_list = current_data[key]
                for i, step in enumerate(steps_list):
                    step['parent_id'] = current_data.get('id', None)
                    if step.get('id') == step_id:
                        return step, steps_list, i
                    found, p_list, idx = self._find_step_parent_and_index(step, step_id)
                    if found: return found, p_list, idx
        if 'cases' in current_data and isinstance(current_data['cases'], list):
            for case in current_data['cases']:
                case['parent_id'] = current_data.get('id', None)
                found, p_list, idx = self._find_step_parent_and_index(case, step_id, current_data.get('id'))
                if found: return found, p_list, idx
        return None, None, -1


# StepWidget 类保持不变，因为它已经是 VisualTaskEditor 的一部分，不需要直接修改
class StepWidget(ttk.Frame):
    def __init__(self, parent, editor, step_data, depth, index, list_len, is_skipped=False):
        frame_style = "Skipped.TFrame" if is_skipped else "Card.TFrame"
        super().__init__(parent, style=frame_style, padding=5)

        self.editor, self.step_data, self.step_id, self.depth = editor, step_data, step_data['id'], depth
        self.is_container = any(k in step_data for k in ['if', 'for', 'while', 'switch', 'case'])

        label_style = "Skipped.TLabel" if is_skipped else "Card.TLabel"
        header_frame_style = "Skipped.TFrame" if is_skipped else "Card.TFrame"

        self.header_frame = ttk.Frame(self, style=header_frame_style)
        self.header_frame.pack(fill='x')

        move_controls_frame = ttk.Frame(self.header_frame, style=header_frame_style)
        move_controls_frame.pack(side='left', padx=(0, 10))

        up_btn = ttk.Button(move_controls_frame, text="↑", style="Move.TButton",
                            command=lambda: self.editor.move_step(self.step_id, 'up'))
        up_btn.grid(row=0, column=0)
        down_btn = ttk.Button(move_controls_frame, text="↓", style="Move.TButton",
                              command=lambda: self.editor.move_step(self.step_id, 'down'))
        down_btn.grid(row=1, column=0)
        outdent_btn = ttk.Button(move_controls_frame, text="←", style="Move.TButton",
                                 command=lambda: self.editor.move_step(self.step_id, 'outdent'))
        outdent_btn.grid(row=0, column=1, rowspan=2, sticky='ns')
        indent_btn = ttk.Button(move_controls_frame, text="→", style="Move.TButton",
                                command=lambda: self.editor.move_step(self.step_id, 'indent'))
        indent_btn.grid(row=0, column=2, rowspan=2, sticky='ns')
        if index == 0: up_btn.config(state='disabled')
        if index == list_len - 1: down_btn.config(state='disabled')
        if depth == 0: outdent_btn.config(state='disabled')

        self.info_label = ttk.Label(self.header_frame, text=self._get_display_text(), style=label_style, anchor='w',
                                    wraplength=400)
        self.info_label.pack(side='left', fill='x', expand=True)

        btn_frame = ttk.Frame(self.header_frame, style=header_frame_style)
        btn_frame.pack(side='right')

        flow_btn = ttk.Button(btn_frame, text="🔗流程",
                              command=lambda: self.editor.open_flow_control_dialog(self.step_id), style="Mini.TButton")
        flow_btn.pack(side='left', padx=2)

        edit_btn = ttk.Button(btn_frame, text="编辑", command=lambda: self.editor.edit_step(self.step_data),
                              style="Mini.TButton")
        edit_btn.pack(side='left', padx=2)
        del_btn = ttk.Button(btn_frame, text="删除", command=lambda: self.editor.delete_step(self.step_id),
                             style="Mini.TButton")
        del_btn.pack(side='left', padx=2)

        self._render_flow_labels(is_skipped)
        if self.is_container: self._create_container_body(is_skipped)

    def _render_flow_labels(self, is_skipped):
        has_flow_control = any(k in self.step_data for k in ['go_step', 'go_task', 'next'])
        if not has_flow_control:
            return
        footer_frame_style = "Skipped.TFrame" if is_skipped else "Card.TFrame"
        flow_footer = ttk.Frame(self, style=footer_frame_style)
        flow_footer.pack(fill='x', padx=(20, 0), pady=(5, 0))
        if 'go_step' in self.step_data:
            target_id = self.step_data['go_step']
            target_widget = self.editor.step_widgets.get(target_id)
            target_name = target_widget._get_display_text().split('] ')[-1] if target_widget else "未知步骤"
            ttk.Label(flow_footer, text=f"↪️ go_step → {target_name}", style="Flow.TLabel").pack(side='left', padx=2)
        if 'go_task' in self.step_data:
            target_name = self.step_data['go_task']
            ttk.Label(flow_footer, text=f"🚀 go_task → {target_name}", style="Flow.TLabel").pack(side='left', padx=2)
        if 'next' in self.step_data:
            target_name = self.step_data['next']
            ttk.Label(flow_footer, text=f"➡️ next → {target_name}", style="Flow.TLabel").pack(side='left', padx=2)

    def _get_display_text(self):
        if 'action' in self.step_data: return f"[行为: {self.step_data['action']}] {self.step_data.get('name', '')}"
        if 'if' in self.step_data: return f"[如果] {self.step_data['if']}"
        if 'for' in self.step_data: loop = self.step_data[
            'for']; return f"[循环: {loop.get('as', 'item')} 在 {loop.get('in', '...')}]"
        if 'while' in self.step_data: return f"[当] {self.step_data['while']}"
        if 'switch' in self.step_data: return f"[切换] on {self.step_data['switch']}"
        if 'case' in self.step_data: return f"情况 (Case): {self.step_data.get('case')}"
        return "未知步骤"

    def _create_container_body(self, is_skipped):
        style = "Inner.TFrame"
        self.body_frame = ttk.Frame(self, style=style, padding=10)
        self.body_frame.pack(fill='x', padx=(20, 0), pady=5)
        skipped_ids = self.editor._analyze_flow_for_skipped_steps(self.step_data.get('steps', []))
        if 'if' in self.step_data:
            then_frame = ttk.Frame(self.body_frame, style=style)
            then_frame.pack(fill='x')
            ttk.Label(then_frame, text="那么 (Then):", style="Branch.TLabel").pack(anchor='w')
            then_steps = self.step_data.setdefault('then', [])
            self.editor._render_step_list(then_steps, then_frame, self.depth + 1,
                                          self.editor._analyze_flow_for_skipped_steps(then_steps))
            add_then_btn = ttk.Button(then_frame, text="+ 添加到 Then",
                                      command=lambda: self.editor.show_add_step_menu(self.step_data['then'],
                                                                                     add_then_btn))
            add_then_btn.pack(pady=5, anchor='w')
            else_frame = ttk.Frame(self.body_frame, style=style)
            else_frame.pack(fill='x', pady=(10, 0))
            ttk.Label(else_frame, text="否则 (Else):", style="Branch.TLabel").pack(anchor='w')
            else_steps = self.step_data.setdefault('else', [])
            self.editor._render_step_list(else_steps, else_frame, self.depth + 1,
                                          self.editor._analyze_flow_for_skipped_steps(else_steps))
            add_else_btn = ttk.Button(else_frame, text="+ 添加到 Else",
                                      command=lambda: self.editor.show_add_step_menu(self.step_data['else'],
                                                                                     add_else_btn))
            add_else_btn.pack(pady=5, anchor='w')
        elif 'for' in self.step_data or 'while' in self.step_data:
            key = 'do'
            do_steps = self.step_data.setdefault(key, [])
            self.editor._render_step_list(do_steps, self.body_frame, self.depth + 1,
                                          self.editor._analyze_flow_for_skipped_steps(do_steps))
            add_do_btn = ttk.Button(self.body_frame, text="+ 添加到循环",
                                    command=lambda: self.editor.show_add_step_menu(self.step_data[key], add_do_btn))
            add_do_btn.pack(pady=5, anchor='w')
        elif 'switch' in self.step_data:
            cases = self.step_data.setdefault('cases', [])
            for i, case_data in enumerate(cases):
                case_data.setdefault('id', str(uuid.uuid4()))
                case_frame = StepWidget(self.body_frame, self.editor, case_data, self.depth + 1, i, len(cases),
                                        case_data['id'] in skipped_ids)
                case_frame.pack(fill='x', pady=4)
            ttk.Button(self.body_frame, text="+ 添加新Case",
                       command=lambda: self.editor.add_case_to_switch(self.step_data)).pack(pady=5, side='left')
            default_frame = ttk.Frame(self.body_frame, style="Case.TFrame", padding=5)
            default_frame.pack(fill='x', pady=(10, 4))
            ttk.Label(default_frame, text="默认 (Default):", style="Case.TLabel").pack(anchor='w')
            default_steps = self.step_data.setdefault('default', [])
            self.editor._render_step_list(default_steps, default_frame, self.depth + 1,
                                          self.editor._analyze_flow_for_skipped_steps(default_steps))
            add_default_btn = ttk.Button(default_frame, text="+ 添加到Default",
                                         command=lambda: self.editor.show_add_step_menu(self.step_data['default'],
                                                                                        add_default_btn))
            add_default_btn.pack(pady=5, anchor='w')
        elif 'case' in self.step_data:
            then_steps = self.step_data.setdefault('then', [])
            self.editor._render_step_list(then_steps, self.body_frame, self.depth + 1,
                                          self.editor._analyze_flow_for_skipped_steps(then_steps))
            add_case_btn = ttk.Button(self.body_frame, text="+ 添加到此Case",
                                      command=lambda: self.editor.show_add_step_menu(self.step_data['then'],
                                                                                     add_case_btn))
            add_case_btn.pack(pady=5, anchor='w')


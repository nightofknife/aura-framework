# src/ui/context_editor.py

import tkinter as tk
from tkinter import ttk, simpledialog, messagebox


class ContextEditorWindow(tk.Toplevel):
    def __init__(self, parent, scheduler):
        super().__init__(parent)
        self.title("长期上下文编辑器")
        self.geometry("600x500")
        self.scheduler = scheduler
        self.current_plan = tk.StringVar()
        self._create_widgets()
        self._populate_plans()

    def _create_widgets(self):
        top_frame = ttk.Frame(self, padding=10)
        top_frame.pack(fill=tk.X)
        ttk.Label(top_frame, text="选择方案包:").pack(side=tk.LEFT, padx=(0, 5))
        self.plan_combobox = ttk.Combobox(top_frame, textvariable=self.current_plan, state="readonly")
        self.plan_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.plan_combobox.bind("<<ComboboxSelected>>", self._on_plan_selected)

        tree_frame = ttk.LabelFrame(self, text="键/值", padding=10)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.context_tree = ttk.Treeview(tree_frame, columns=("Key", "Value"), show="headings")
        self.context_tree.heading("Key", text="键 (Key)")
        self.context_tree.heading("Value", text="值 (Value)")
        self.context_tree.pack(fill=tk.BOTH, expand=True)
        self.context_tree.bind("<Double-1>", self._on_double_click)

        button_frame = ttk.Frame(self, padding=10)
        button_frame.pack(fill=tk.X)
        ttk.Button(button_frame, text="新增...", command=self._add_item).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="删除选中", command=self._delete_item).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="保存更改", command=self._save_context).pack(side=tk.RIGHT)

    def _populate_plans(self):
        plans = self.scheduler.get_all_plans()
        self.plan_combobox['values'] = plans
        if plans:
            self.plan_combobox.current(0)
            self._load_context_data()

    def _on_plan_selected(self, event):
        self._load_context_data()

    def _load_context_data(self):
        self.context_tree.delete(*self.context_tree.get_children())
        plan_name = self.current_plan.get()
        if not plan_name: return
        data = self.scheduler.get_persistent_context(plan_name)
        for key, value in sorted(data.items()):
            self.context_tree.insert("", "end", values=(key, str(value)))

    def _on_double_click(self, event):
        item_id = self.context_tree.identify_row(event.y)
        column = self.context_tree.identify_column(event.x)
        if not item_id or column != "#2": return
        x, y, width, height = self.context_tree.bbox(item_id, column)
        value = self.context_tree.set(item_id, column)
        entry = ttk.Entry(self.context_tree)
        entry.place(x=x, y=y, width=width, height=height)
        entry.insert(0, value)
        entry.focus_force()
        entry.bind("<FocusOut>", lambda e: (self.context_tree.set(item_id, column, entry.get()), entry.destroy()))
        entry.bind("<Return>", lambda e: (self.context_tree.set(item_id, column, entry.get()), entry.destroy()))

    def _add_item(self):
        key = simpledialog.askstring("新增条目", "请输入新的 '键' (Key):", parent=self)
        if not key: return
        value = simpledialog.askstring("新增条目", f"请输入 '{key}' 的 '值' (Value):", parent=self)
        if value is not None:
            self.context_tree.insert("", "end", values=(key, value))

    def _delete_item(self):
        selected = self.context_tree.selection()
        if selected: self.context_tree.delete(selected)

    def _save_context(self):
        plan_name = self.current_plan.get()
        if not plan_name: return
        new_data = {}
        for child_id in self.context_tree.get_children():
            key, value_raw = self.context_tree.item(child_id)['values']
            value_str = str(value_raw)
            try:
                value = int(value_str) if '.' not in value_str else float(value_str)
            except ValueError:
                if value_str.lower() == 'true':
                    value = True
                elif value_str.lower() == 'false':
                    value = False
                else:
                    value = value_str
            new_data[key] = value
        try:
            self.scheduler.save_persistent_context(plan_name, new_data)
            messagebox.showinfo("成功", f"'{plan_name}' 的长期上下文已保存。", parent=self)
            self.destroy()
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self)

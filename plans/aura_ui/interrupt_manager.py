# src/ui/interrupt_manager.py

import tkinter as tk
from tkinter import ttk

from packages.aura_core.logger import logger


class InterruptManagerWindow(tk.Toplevel):
    def __init__(self, parent, scheduler):
        super().__init__(parent)
        self.title("中断管理器")
        self.geometry("800x600")
        self.scheduler = scheduler
        self._create_widgets()
        self._populate_tree()
        self.after(1000, self._refresh_ui)

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        help_text = "这里管理所有已定义的中断规则。\n- 全局中断: 默认情况下会持续监控，你可以通过双击来启用或禁用它们。\n- 任务作用域中断: 只有在特定任务运行时才会被临时激活，此处仅供查看。"
        ttk.Label(main_frame, text=help_text, justify=tk.LEFT, wraplength=780).pack(fill=tk.X, pady=(0, 10))

        tree_frame = ttk.LabelFrame(main_frame, text="中断规则列表", padding=10)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=("Name", "Plan", "Status"), show="headings")
        self.tree.heading("Name", text="中断名称")
        self.tree.heading("Plan", text="来源方案包")
        self.tree.heading("Status", text="当前状态")
        self.tree.column("Name", width=300)
        self.tree.column("Plan", width=150)
        self.tree.column("Status", width=200)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        button_frame = ttk.Frame(main_frame, padding=(0, 10, 0, 0))
        button_frame.pack(fill=tk.X)
        ttk.Button(button_frame, text="关闭", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(button_frame, text="刷新列表", command=self._populate_tree).pack(side=tk.RIGHT, padx=5)

    def _populate_tree(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        self.global_id = self.tree.insert("", "end", text="全局中断", open=True)
        self.task_id = self.tree.insert("", "end", text="任务作用域中断", open=True)
        self.tree.tag_bind('global_interrupt', '<Double-1>', self._toggle_global_interrupt)
        self._refresh_ui(initial_load=True)

    def _toggle_global_interrupt(self, event):
        item_id = self.tree.focus()
        if not item_id or not self.tree.exists(item_id) or self.tree.parent(item_id) != self.global_id: return
        rule_name = self.tree.item(item_id, 'values')[0]
        is_enabled = (self.tree.item(item_id, 'values')[2] == "已启用")
        if is_enabled:
            self.scheduler.disable_global_interrupt(rule_name)
        else:
            self.scheduler.enable_global_interrupt(rule_name)
        self._refresh_ui()

    def _refresh_ui(self, initial_load=False):
        try:
            if not self.winfo_exists(): return
            interrupt_map = {rule['name']: rule for rule in self.scheduler.get_all_interrupts_status()}

            if initial_load:
                for rule_name, rule in sorted(interrupt_map.items()):
                    values = (rule_name, rule.get('plan_name', 'N/A'), "已启用" if rule.get('enabled') else "已禁用")
                    parent_id, tag = (self.global_id, 'global_interrupt') if rule['scope'] == 'global' else (
                        self.task_id, 'task_interrupt')
                    if rule['scope'] != 'global': values = (
                        values[0], values[1], "激活中" if rule.get('enabled') else "非活动")
                    self.tree.insert(parent_id, "end", iid=rule_name, values=values, tags=(tag,))
            else:
                for rule_name, rule_data in interrupt_map.items():
                    if not self.tree.exists(rule_name): continue
                    values = list(self.tree.item(rule_name, 'values'))
                    new_status = "已启用" if rule_data.get('enabled') else "已禁用"
                    if rule_data['scope'] != 'global': new_status = "激活中" if rule_data.get('enabled') else "非活动"
                    if values[2] != new_status: self.tree.item(rule_name, values=(values[0], values[1], new_status))

            self.after(1000, self._refresh_ui)
        except Exception as e:
            logger.error(f"刷新中断管理器UI时出错: {e}")

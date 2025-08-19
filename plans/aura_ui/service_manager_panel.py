import tkinter as tk
from collections import defaultdict
from tkinter import ttk, scrolledtext

from .base_panel import BasePanel


class ServiceManagerPanel(BasePanel):
    def __init__(self, parent, scheduler, ide, **kwargs):
        super().__init__(parent, scheduler, ide, **kwargs)

    def _create_widgets(self):
        self.service_data = []
        toolbar = ttk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=5, padx=5)
        # 【修正】刷新按钮直接调用 reload_plans，它会自动触发UI更新
        self.refresh_button = ttk.Button(toolbar, text="刷新服务列表", command=self.scheduler.reload_plans)
        self.refresh_button.pack(side=tk.LEFT)
        main_pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))
        list_frame = ttk.Frame(main_pane)
        main_pane.add(list_frame, weight=3)
        columns = ("alias", "status", "path")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings")
        self.tree.heading("alias", text="服务别名")
        self.tree.heading("status", text="状态")
        self.tree.heading("path", text="源文件类")
        self.tree.column("alias", width=200)
        self.tree.column("status", width=80, anchor='center')
        self.tree.column("path", width=400)
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(list_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side='right', fill='y')
        hsb.pack(side='bottom', fill='x')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_service_select)

        # 标签配置移到 update 方法中，确保它们在数据加载后应用

        detail_frame = ttk.LabelFrame(main_pane, text="详情")
        main_pane.add(detail_frame, weight=1)
        self.detail_text = scrolledtext.ScrolledText(detail_frame, wrap=tk.WORD, height=5, state='disabled')
        self.detail_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def _initial_load(self):
        """初始加载时，从 scheduler 获取一次全量数据。"""
        self.update_service_list(self.scheduler.get_all_services_status())

    def update_service_list(self, service_list: list):
        """【修正】被动接收服务列表数据并更新UI，使用对象属性访问。"""
        for item in self.tree.get_children(): self.tree.delete(item)
        self._set_detail_text("")
        self.service_data = service_list

        grouped_services = defaultdict(list)
        # 【修正】service_info 现在是对象，而不是字典
        for service_info in self.service_data:
            namespace = service_info.plugin.canonical_id if service_info.plugin else 'Unknown'
            grouped_services[namespace].append(service_info)

        for namespace, services in sorted(grouped_services.items()):
            ns_node = self.tree.insert('', tk.END, values=(namespace, '', ''), open=True, tags=('namespace',))
            # 【修正】使用 .alias 属性访问
            for service_info in sorted(services, key=lambda s: s.alias or ''):
                # 【修正】全部改为 . 属性访问
                alias = service_info.alias or 'N/A'
                status = service_info.status or 'N/A'

                if service_info.service_class:
                    module_path = service_info.service_class.__module__
                    class_name = service_info.service_class.__name__
                else:
                    module_path = 'unknown.module'
                    class_name = 'UnknownClass'

                path_display = f"{module_path}.{class_name}"
                tag = status if status in ['resolved', 'failed', 'defined'] else ''
                fqid = service_info.fqid or ''
                self.tree.insert(ns_node, tk.END, values=(alias, status, path_display), tags=(tag,), iid=fqid)

        # 【修正】将标签配置放在数据填充之后
        self.tree.tag_configure('namespace', background='#f0f0f0', font=("", 9, "bold"))
        self.tree.tag_configure('resolved', foreground='green')
        self.tree.tag_configure('failed', foreground='red')
        self.tree.tag_configure('defined', foreground='orange')

    def _on_service_select(self, event):
        """【修正】使用对象属性访问。"""
        selected_items = self.tree.selection()
        if not selected_items: return
        selected_iid = selected_items[0]
        # 【修正】使用 .fqid 属性进行匹配
        service_info = next((s for s in self.service_data if s.fqid == selected_iid), None)

        if service_info:
            # 【修正】全部改为 . 属性访问，并增加安全检查
            details = f"FQID: {service_info.fqid or 'N/A'}\n"
            details += f"别名: {service_info.alias or 'N/A'}\n"
            details += f"状态: {service_info.status or 'N/A'}\n"
            details += f"插件: {service_info.plugin.canonical_id if service_info.plugin else 'N/A'}\n"
            if service_info.service_class:
                details += f"模块: {service_info.service_class.module or 'N/A'}\n"
                details += f"类名: {service_info.service_class.name or 'N/A'}\n"
            details += f"公开: {'是' if service_info.public else '否'}\n"
            if service_info.is_extension:
                details += f"继承自: {service_info.parent_fqid or 'N/A'}\n"
            self._set_detail_text(details)
        else:
            values = self.tree.item(selected_iid, 'values')
            if values:
                self._set_detail_text(f"插件命名空间: {values[0]}")

    def _set_detail_text(self, text):
        self.detail_text.config(state='normal')
        self.detail_text.delete('1.0', tk.END)
        self.detail_text.insert('1.0', text)
        self.detail_text.config(state='disabled')


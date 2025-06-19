# src/ui/service_manager_panel.py

import tkinter as tk
from tkinter import ttk, scrolledtext
from collections import defaultdict


class ServiceManagerPanel(ttk.Frame):
    """
    【最终版】一个用于显示、监控和调试所有已加载服务的UI面板。
    支持按命名空间分组显示。
    """

    def __init__(self, parent, scheduler):
        super().__init__(parent)
        self.scheduler = scheduler
        self.service_data = []

        self._create_widgets()
        self._populate_services()

    def _create_widgets(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=5, padx=5)
        self.refresh_button = ttk.Button(toolbar, text="刷新服务列表", command=self._populate_services)
        self.refresh_button.pack(side=tk.LEFT)

        main_pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        list_frame = ttk.Frame(main_pane)
        main_pane.add(list_frame, weight=3)

        # 【核心修改 #1】使用 Treeview 来支持层级结构
        # 我们不再需要 'namespace' 列，因为命名空间将成为父节点
        columns = ("short_name", "status", "path")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings")

        self.tree.heading("short_name", text="服务短名称")
        self.tree.heading("status", text="状态")
        self.tree.heading("path", text="源文件路径")

        self.tree.column("short_name", width=200)
        self.tree.column("status", width=80, anchor='center')
        self.tree.column("path", width=400)

        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(list_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side='right', fill='y')
        hsb.pack(side='bottom', fill='x')
        self.tree.pack(side='left', fill='both', expand=True)

        self.tree.bind("<<TreeviewSelect>>", self._on_service_select)

        self.tree.tag_configure('resolved', foreground='green')
        self.tree.tag_configure('failed', foreground='red')
        self.tree.tag_configure('defined', foreground='orange')

        detail_frame = ttk.LabelFrame(main_pane, text="详情")
        main_pane.add(detail_frame, weight=1)
        self.detail_text = scrolledtext.ScrolledText(detail_frame, wrap=tk.WORD, height=5, state='disabled')
        self.detail_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def _populate_services(self):
        """【核心修改 #2】按命名空间分组填充服务列表。"""
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._set_detail_text("")

        # 使用 service_registry 获取最新的定义
        self.service_data = self.scheduler.service_registry.get_all_service_definitions()

        # 按插件（命名空间）分组
        grouped_services = defaultdict(list)
        for service_def in self.service_data:
            namespace = service_def.plugin.canonical_id
            grouped_services[namespace].append(service_def)

        # 填充 Treeview
        for namespace, services in sorted(grouped_services.items()):
            # 创建命名空间父节点
            ns_node = self.tree.insert('', tk.END, values=(namespace, '', ''), open=True, tags=('namespace',))
            for service_info in sorted(services, key=lambda s: s.short_name):
                short_name = service_info.short_name
                status = service_info.status
                path = service_info.source_path

                tag = ''
                if status == 'resolved':
                    tag = 'resolved'
                elif status == 'failed':
                    tag = 'failed'
                elif status == 'defined':
                    tag = 'defined'

                # 将服务作为子节点插入
                self.tree.insert(ns_node, tk.END, values=(short_name, status, path), tags=(tag,), iid=service_info.fqid)
        self.tree.tag_configure('namespace', background='#f0f0f0', font=("", 9, "bold"))


    def _on_service_select(self, event):
        """当用户选择一个服务时，显示其详细信息。"""
        selected_items = self.tree.selection()
        if not selected_items: return

        selected_iid = selected_items[0]

        # 通过iid（我们设置为fqid）找到对应的服务定义
        service_info = next((s for s in self.service_data if s.fqid == selected_iid), None)

        if service_info:
            details = f"FQID: {service_info.fqid}\n"
            details += f"短名称: {service_info.short_name}\n"
            details += f"状态: {service_info.status}\n"
            details += f"插件: {service_info.plugin.canonical_id}\n"
            details += f"类名: {service_info.service_class.__name__}\n"
            details += f"路径: {service_info.source_path}\n"

            if service_info.is_extension:
                details += f"继承自: {service_info.parent_fqid}\n"

            self._set_detail_text(details)
        else:
            # 用户可能点击了命名空间节点
            self._set_detail_text(f"插件命名空间: {self.tree.item(selected_iid, 'text')}")

    def _set_detail_text(self, text):
        self.detail_text.config(state='normal')
        self.detail_text.delete('1.0', tk.END)
        self.detail_text.insert('1.0', text)
        self.detail_text.config(state='disabled')

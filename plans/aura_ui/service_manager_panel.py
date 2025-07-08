# packages/aura_ui/service_manager_panel.py (最终修正版)

import tkinter as tk
from tkinter import ttk, scrolledtext
from collections import defaultdict
from pathlib import Path


class ServiceManagerPanel(ttk.Frame):
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
        self.tree.tag_configure('resolved', foreground='green')
        self.tree.tag_configure('failed', foreground='red')
        self.tree.tag_configure('defined', foreground='orange')
        detail_frame = ttk.LabelFrame(main_pane, text="详情")
        main_pane.add(detail_frame, weight=1)
        self.detail_text = scrolledtext.ScrolledText(detail_frame, wrap=tk.WORD, height=5, state='disabled')
        self.detail_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def _populate_services(self):
        for item in self.tree.get_children(): self.tree.delete(item)
        self._set_detail_text("")

        # 【【【核心修正：使用 get_all_services_status() 获取安全的字典列表】】】
        self.service_data = self.scheduler.get_all_services_status()

        grouped_services = defaultdict(list)
        for service_dict in self.service_data:
            namespace = service_dict.get('plugin', {}).get('canonical_id', 'Unknown')
            grouped_services[namespace].append(service_dict)

        for namespace, services in sorted(grouped_services.items()):
            ns_node = self.tree.insert('', tk.END, values=(namespace, '', ''), open=True, tags=('namespace',))
            for service_info in sorted(services, key=lambda s: s.get('alias', '')):
                alias = service_info.get('alias', 'N/A')
                status = service_info.get('status', 'N/A')

                # 【【【核心修正：从字典中安全地构造路径】】】
                class_info = service_info.get('service_class', {})
                module_path = class_info.get('module', 'unknown.module')
                class_name = class_info.get('name', 'UnknownClass')
                path_display = f"{module_path}.{class_name}"

                tag = ''
                if status == 'resolved':
                    tag = 'resolved'
                elif status == 'failed':
                    tag = 'failed'
                elif status == 'defined':
                    tag = 'defined'

                fqid = service_info.get('fqid', '')
                self.tree.insert(ns_node, tk.END, values=(alias, status, path_display), tags=(tag,), iid=fqid)

        self.tree.tag_configure('namespace', background='#f0f0f0', font=("", 9, "bold"))

    def _on_service_select(self, event):
        selected_items = self.tree.selection()
        if not selected_items: return
        selected_iid = selected_items[0]

        # 【【【核心修正：从 self.service_data (字典列表) 中查找】】】
        service_info = next((s for s in self.service_data if s.get('fqid') == selected_iid), None)

        if service_info:
            details = f"FQID: {service_info.get('fqid', 'N/A')}\n"
            details += f"别名: {service_info.get('alias', 'N/A')}\n"
            details += f"状态: {service_info.get('status', 'N/A')}\n"
            details += f"插件: {service_info.get('plugin', {}).get('canonical_id', 'N/A')}\n"

            class_info = service_info.get('service_class', {})
            details += f"模块: {class_info.get('module', 'N/A')}\n"
            details += f"类名: {class_info.get('name', 'N/A')}\n"

            details += f"公开: {'是' if service_info.get('public') else '否'}\n"

            if service_info.get('is_extension'):
                details += f"继承自: {service_info.get('parent_fqid', 'N/A')}\n"

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

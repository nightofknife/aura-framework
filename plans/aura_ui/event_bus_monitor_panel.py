# plans/aura_ui/event_bus_monitor_panel.py (完整修正版)
import json
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from .base_panel import BasePanel


class EventBusMonitorPanel(BasePanel):
    def __init__(self, parent, scheduler, ide, **kwargs):
        super().__init__(parent, scheduler, ide, **kwargs)

    def _create_widgets(self):
        self.ui_event_queue = self.scheduler.get_ui_event_queue()
        self.all_events = []
        self.is_paused = False

        control_frame = ttk.Frame(self, padding=(5, 5))
        control_frame.pack(fill='x', side='top')
        ttk.Label(control_frame, text="频道:").pack(side='left', padx=(0, 5))
        self.channel_filter_var = tk.StringVar()
        self.channel_filter_combo = ttk.Combobox(control_frame, textvariable=self.channel_filter_var,
                                                 values=["* (所有)"])
        self.channel_filter_combo.pack(side='left', padx=(0, 10))
        self.channel_filter_combo.set("* (所有)")
        self.channel_filter_combo.bind("<<ComboboxSelected>>", self._apply_filters)
        self.channel_filter_var.trace_add("write", self._apply_filters)
        ttk.Label(control_frame, text="事件名:").pack(side='left', padx=(0, 5))
        self.name_filter_var = tk.StringVar()
        self.name_filter_entry = ttk.Entry(control_frame, textvariable=self.name_filter_var)
        self.name_filter_entry.pack(side='left', expand=True, fill='x', padx=(0, 10))
        self.name_filter_var.trace_add("write", self._apply_filters)
        self.pause_button = ttk.Button(control_frame, text="暂停", command=self._toggle_pause)
        self.pause_button.pack(side='left', padx=(0, 5))
        clear_button = ttk.Button(control_frame, text="清空", command=self._clear_all)
        clear_button.pack(side='left')

        tree_frame = ttk.Frame(self)
        tree_frame.pack(expand=True, fill='both', side='top')
        columns = ("timestamp", "name", "channel", "source", "payload")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show='headings')
        self.tree.heading("timestamp", text="时间")
        self.tree.heading("name", text="事件名称")
        self.tree.heading("channel", text="频道")
        self.tree.heading("source", text="来源")
        self.tree.heading("payload", text="载荷摘要")
        self.tree.column("timestamp", width=150, anchor='w')
        self.tree.column("name", width=200, anchor='w')
        self.tree.column("channel", width=150, anchor='w')
        self.tree.column("source", width=150, anchor='w')
        self.tree.column("payload", width=300, anchor='w')
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side='right', fill='y')
        hsb.pack(side='bottom', fill='x')
        self.tree.pack(side='left', expand=True, fill='both')
        self.tree.bind("<Double-1>", self._on_double_click)

    def _initial_load(self):
        self.schedule_update(200, self._process_ui_queue, "process_event_queue")

    def _process_ui_queue(self):
        try:
            if not self.ui_event_queue: return
            while not self.ui_event_queue.empty():
                event_dict = self.ui_event_queue.get_nowait()
                self.all_events.append(event_dict)
                channel = event_dict['channel']
                if channel not in self.channel_filter_combo['values']:
                    self.channel_filter_combo['values'] = (*self.channel_filter_combo['values'], channel)
                if not self.is_paused:
                    self._add_event_to_tree(event_dict)
        finally:
            self.schedule_update(200, self._process_ui_queue, "process_event_queue")

    def _add_event_to_tree(self, event_dict, at_start=True):
        if not self._matches_filters(event_dict):
            return
        ts = datetime.fromtimestamp(event_dict['timestamp']).strftime('%H:%M:%S.%f')[:-3]
        payload_summary = json.dumps(event_dict['payload'], ensure_ascii=False)
        if len(payload_summary) > 100:
            payload_summary = payload_summary[:100] + "..."
        values = (ts, event_dict['name'], event_dict['channel'], event_dict['source'], payload_summary)
        position = 0 if at_start else 'end'
        item_id = self.tree.insert("", position, values=values)
        self.tree.item(item_id, tags=(event_dict['id'],))

    def _matches_filters(self, event_dict):
        channel_filter = self.channel_filter_var.get()
        name_filter = self.name_filter_var.get().lower()
        channel_match = (channel_filter == "* (所有)" or channel_filter == event_dict['channel'])
        name_match = (not name_filter or name_filter in event_dict['name'].lower())
        return channel_match and name_match

    def _apply_filters(self, *args):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for event_dict in reversed(self.all_events):
            self._add_event_to_tree(event_dict, at_start=True)

    def _toggle_pause(self):
        self.is_paused = not self.is_paused
        self.pause_button.config(text="继续" if self.is_paused else "暂停")
        if not self.is_paused:
            self._apply_filters()

    def _clear_all(self):
        self.all_events.clear()
        self.tree.delete(*self.tree.get_children())
        self.channel_filter_combo['values'] = ["* (所有)"]
        self.channel_filter_combo.set("* (所有)")
        self.name_filter_var.set("")

    def _on_double_click(self, event):
        item_id = self.tree.focus()
        if not item_id:
            return
        event_uuid = self.tree.item(item_id, "tags")[0]
        selected_event = next((ev for ev in self.all_events if ev['id'] == event_uuid), None)
        if selected_event:
            self._show_event_details(selected_event)

    def _show_event_details(self, event_dict):
        top = tk.Toplevel(self)
        top.title(f"事件详情: {event_dict['name']}")
        top.geometry("600x500")
        text = tk.Text(top, wrap=tk.WORD, font=("Courier New", 10))
        text.pack(expand=True, fill='both', padx=10, pady=10)
        details = (
            f"ID: {event_dict['id']}\n"
            f"时间戳: {datetime.fromtimestamp(event_dict['timestamp'])}\n"
            f"名称: {event_dict['name']}\n"
            f"频道: {event_dict['channel']}\n"
            f"来源: {event_dict['source']}\n"
            f"深度: {event_dict['depth']}\n\n"
            f"调用链 (Causation Chain):\n"
            f"--------------------------\n"
            f"{json.dumps(event_dict['causation_chain'], indent=2)}\n\n"
            f"载荷 (Payload):\n"
            f"----------------\n"
            f"{json.dumps(event_dict['payload'], indent=2, ensure_ascii=False)}"
        )
        text.insert(tk.END, details)
        text.config(state=tk.DISABLED)
        top.transient(self)
        top.grab_set()
        self.wait_window(top)

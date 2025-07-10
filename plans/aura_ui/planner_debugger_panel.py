# plans/aura_ui/planner_debugger_panel.py (最终优化版)

import tkinter as tk
from tkinter import ttk, scrolledtext
import math
import queue
from typing import Dict, Any, List, Tuple
from .base_panel import BasePanel


class PlannerDebuggerPanel(BasePanel):
    def __init__(self, parent, scheduler, ide, **kwargs):
        super().__init__(parent, scheduler, ide, **kwargs)

    def _create_widgets(self):
        self.event_bus = self.scheduler.get_event_bus()
        self.ui_queue = queue.Queue()

        # 【新增】用于存储订阅句柄的列表
        self.subscription_handles = []

        # ... (其余 _create_widgets 代码保持不变) ...
        self.NODE_RADIUS, self.NODE_COLOR, self.NODE_TEXT_COLOR, self.NODE_HIGHLIGHT_COLOR, self.NODE_CURRENT_COLOR, self.EDGE_COLOR, self.PATH_COLOR, self.PATH_WIDTH, self.FONT, self.FONT_BOLD = 25, "#A9CCE3", "#1A5276", "#F7DC6F", "#5DADE2", "#ABB2B9", "#2ECC71", 3, (
        "Arial", 10), ("Arial", 10, "bold")
        self.nodes, self.edges, self.node_positions, self.current_state, self.current_path = {}, [], {}, None, []
        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(expand=True, fill='both')
        canvas_frame = ttk.Frame(main_pane)
        self.canvas = tk.Canvas(canvas_frame, bg="white", highlightthickness=0)
        self.canvas.pack(expand=True, fill='both')
        main_pane.add(canvas_frame, weight=3)
        info_frame = ttk.Frame(main_pane, padding=5)
        main_pane.add(info_frame, weight=1)
        info_frame.rowconfigure(1, weight=1)
        info_frame.columnconfigure(0, weight=1)
        status_label = ttk.Label(info_frame, text="实时状态", font=("Arial", 12, "bold"))
        status_label.grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.log_text = scrolledtext.ScrolledText(info_frame, wrap=tk.WORD, font=("Courier New", 9), height=10)
        self.log_text.grid(row=1, column=0, sticky="nsew")
        self.log_text.config(state=tk.DISABLED)
        clear_button = ttk.Button(info_frame, text="清空画布和日志", command=self.clear_all)
        clear_button.grid(row=2, column=0, sticky="ew", pady=(5, 0))

    def _initial_load(self):
        self._subscribe_to_events()
        self.schedule_update(100, self._process_ui_queue, "process_planner_queue")

    def destroy(self):
        # 【核心修正】使用正确的取消订阅逻辑
        if self.event_bus:
            print("Unsubscribing from planner events...")
            for handle in self.subscription_handles:
                self.event_bus.unsubscribe(handle)
        super().destroy()

    def _subscribe_to_events(self):
        # 【核心修正】保存 subscribe 返回的句柄
        handle = self.event_bus.subscribe(
            event_pattern='*',
            callback=self._handle_planner_event,
            channel='planner'
        )
        self.subscription_handles.append(handle)

    # ... (其余所有方法，如 _handle_planner_event, _process_ui_queue, _log, _draw_canvas 等，都保持不变) ...
    def _handle_planner_event(self, event):
        self.ui_queue.put(event)

    def _process_ui_queue(self):
        try:
            while not self.ui_queue.empty():
                event = self.ui_queue.get_nowait()
                handler_name = f"_on_{event.name.lower()}"
                handler = getattr(self, handler_name, self._on_default_event)
                handler(event)
        finally:
            self.schedule_update(100, self._process_ui_queue, "process_planner_queue")

    def _log(self, message: str, tag: str = "INFO"):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{tag}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def clear_all(self):
        self.canvas.delete("all")
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.nodes.clear()
        self.edges.clear()
        self.node_positions.clear()
        self.current_state = None
        self.current_path = []

    def _calculate_node_positions(self):
        self.node_positions.clear()
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        center_x, center_y = width / 2, height / 2
        radius = min(center_x, center_y) * 0.8
        node_count = len(self.nodes)
        if node_count == 0:
            return
        angle_step = 2 * math.pi / node_count
        for i, node_name in enumerate(self.nodes.keys()):
            angle = i * angle_step
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            self.node_positions[node_name] = (int(x), int(y))

    def _draw_canvas(self):
        self.canvas.delete("all")
        if not self.node_positions:
            return
        for edge in self.edges:
            pos_from = self.node_positions.get(edge['from'])
            pos_to = self.node_positions.get(edge['to'])
            if pos_from and pos_to:
                self.canvas.create_line(pos_from, pos_to, fill=self.EDGE_COLOR, width=1, tags="edge")
                mid_x = (pos_from[0] + pos_to[0]) / 2
                mid_y = (pos_from[1] + pos_to[1]) / 2
                self.canvas.create_text(mid_x, mid_y, text=str(edge['cost']), font=self.FONT, fill=self.EDGE_COLOR)
        if self.current_path:
            for i in range(len(self.current_path) - 1):
                node_from = self.current_path[i]
                node_to = self.current_path[i + 1]
                pos_from = self.node_positions.get(node_from)
                pos_to = self.node_positions.get(node_to)
                if pos_from and pos_to:
                    self.canvas.create_line(pos_from, pos_to, fill=self.PATH_COLOR, width=self.PATH_WIDTH, tags="path")
        for name, pos in self.node_positions.items():
            color = self.NODE_COLOR
            if name == self.current_state:
                color = self.NODE_CURRENT_COLOR
            elif name in self.current_path:
                color = self.NODE_HIGHLIGHT_COLOR
            x, y = pos
            self.canvas.create_oval(x - self.NODE_RADIUS, y - self.NODE_RADIUS,
                                    x + self.NODE_RADIUS, y + self.NODE_RADIUS,
                                    fill=color, outline=self.NODE_TEXT_COLOR, width=1.5, tags=("node", name))
            self.canvas.create_text(x, y, text=name, font=self.FONT_BOLD, fill=self.NODE_TEXT_COLOR,
                                    tags=("node_text", name))

    def _on_planner_started(self, event: Any):
        self.clear_all()
        self._log(f"规划开始，目标: '{event.payload.get('target')}'", "START")

    def _on_planner_map_loaded(self, event: Any):
        self._log("世界地图已加载", "MAP")
        payload = event.payload
        self.nodes = {node: {} for node in payload.get('nodes', [])}
        self.edges = payload.get('transitions', [])
        self._calculate_node_positions()
        self._draw_canvas()

    def _on_planner_state_located(self, event: Any):
        state = event.payload.get('current_state')
        self._log(f"定位到当前状态: '{state}'", "LOCATE")
        self.current_state = state
        self._draw_canvas()

    def _on_planner_path_found(self, event: Any):
        path = event.payload.get('path', [])
        cost = event.payload.get('total_cost', 0)
        self._log(f"找到路径: {' -> '.join(path)} (成本: {cost})", "PATH")
        self.current_path = path
        self._draw_canvas()

    def _on_planner_step_executing(self, event: Any):
        payload = event.payload
        self._log(f"执行步骤: {payload.get('from')} -> {payload.get('to')}", "EXEC")
        self.current_state = payload.get('from')
        self._draw_canvas()

    def _on_planner_step_completed(self, event: Any):
        state = event.payload.get('state_reached')
        self._log(f"步骤完成，到达: '{state}'", "STEP_OK")
        self.current_state = state
        self._draw_canvas()

    def _on_planner_succeeded(self, event: Any):
        reason = event.payload.get('reason')
        self._log(f"规划成功: {reason}", "SUCCESS")
        self.current_path = []
        self._draw_canvas()

    def _on_planner_failed(self, event: Any):
        reason = event.payload.get('reason')
        self._log(f"规划失败: {reason}", "FAIL")
        self.current_path = []
        self._draw_canvas()

    def _on_default_event(self, event: Any):
        self._log(f"收到未知事件: {event.name}", "UNKNOWN")

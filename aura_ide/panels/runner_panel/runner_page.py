# src/aura_ide/panels/runner_panel/runner_page.py (FINAL VERSION)

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

import yaml
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QWidget, QSplitter, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QPlainTextEdit,
    QTreeWidget, QTreeWidgetItem, QGroupBox, QFormLayout, QSpinBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox
)

from .detail_panel import TaskRunDetailPanel


@dataclass
class QueueItem:
    id: str
    plan: str
    task_name: str
    params_override: Dict[str, Any]
    env: str = "Default"
    mode: str = "serial"
    group_id: Optional[str] = None
    status: str = "pending"
    submitted_at: Optional[float] = None
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    client_run_tag: str = field(default_factory=lambda: str(uuid.uuid4()))


class LiveLogView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        v.addLayout(bar)
        bar.addWidget(QLabel("级别筛选:"))
        self.level_combo = QComboBox()
        self.level_combo.addItems(["ALL", "INFO", "WARNING", "ERROR", "STEP", "EVENT"])
        bar.addWidget(self.level_combo)
        bar.addWidget(QLabel("搜索:"))
        self.search_edit = QPlainTextEdit()
        self.search_edit.setFixedHeight(26)
        self.search_edit.setPlaceholderText("输入关键字过滤显示（不影响采集）")
        bar.addWidget(self.search_edit, 1)
        self.pause_btn = QPushButton("暂停自动滚动")
        self.pause_btn.setCheckable(True)
        bar.addWidget(self.pause_btn)
        self.clear_btn = QPushButton("清屏")
        bar.addWidget(self.clear_btn)
        self.export_btn = QPushButton("导出")
        bar.addWidget(self.export_btn)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        v.addWidget(self.text, 1)
        self.clear_btn.clicked.connect(self.text.clear)
        self.export_btn.clicked.connect(self._export_logs)
        self._buffer: List[str] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(120)
        self._flush_timer.timeout.connect(self._flush)
        self._flush_timer.start()

    def append(self, line: str, level: str = "INFO", tag: str = ""):
        lvl = (level or "INFO").upper()
        sel = self.level_combo.currentText()
        kw = self.search_edit.toPlainText().strip()
        show = True
        if sel != "ALL" and lvl != sel and tag != sel: show = False
        if kw and kw not in line: show = False
        prefix = f"[{(tag or lvl):>5}] "
        if show: self._buffer.append(prefix + line)

    def _flush(self):
        if not self._buffer: return
        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text.setUpdatesEnabled(False)
        for line in self._buffer: cursor.insertText(line + "\n")
        self.text.setUpdatesEnabled(True)
        self._buffer.clear()
        if not self.pause_btn.isChecked(): self.text.verticalScrollBar().setValue(
            self.text.verticalScrollBar().maximum())

    def _export_logs(self):
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"runner_logs_{ts}.txt"
        try:
            with open(fname, "w", encoding="utf-8") as f:
                f.write(self.text.toPlainText())
            QMessageBox.information(self, "导出成功", f"日志已导出到: {fname}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))


class TaskPickerWidget(QWidget):
    run_now_requested = Signal(str, str, dict)
    add_to_queue_requested = Signal(dict)

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        group = QGroupBox("任务选择")
        outer.addWidget(group)
        form = QFormLayout(group)
        self.plan_combo = QComboBox()
        self.task_tree = QTreeWidget()
        self.task_tree.setHeaderLabels(["任务（relative_path / task_key）"])
        self.task_tree.setRootIsDecorated(True)
        self.task_tree.setAnimated(True)
        self.env_combo = QComboBox()
        self.env_combo.addItems(["Default", "Dev", "Prod"])
        self.params_edit = QPlainTextEdit()
        self.params_edit.setPlaceholderText("# 在此覆盖参数（YAML）")
        self.params_edit.setFixedHeight(140)
        btns = QHBoxLayout()
        self.btn_run = QPushButton("Run Now")
        self.btn_add = QPushButton("Add to Queue")
        btns.addWidget(self.btn_run)
        btns.addWidget(self.btn_add)
        form.addRow("Plan:", self.plan_combo)
        form.addRow(QLabel("任务列表:"), self.task_tree)
        form.addRow("环境:", self.env_combo)
        form.addRow("参数覆盖 (YAML):", self.params_edit)
        form.addRow(btns)
        self._reload_plans()
        self.plan_combo.currentTextChanged.connect(self._reload_tasks)
        self.btn_run.clicked.connect(self._emit_run_now)
        self.btn_add.clicked.connect(self._emit_add_to_queue)
        outer.addStretch()

    def _reload_plans(self):
        plans = []
        try:
            plans = self.bridge.list_plans() or []
        except Exception:
            pass
        self.plan_combo.clear()
        self.plan_combo.addItems(plans)
        if plans: self._reload_tasks(plans[0])

    def _reload_tasks(self, plan_name: str):
        self.task_tree.clear()
        if not plan_name: return
        tasks = []
        try:
            tasks = self.bridge.list_tasks(plan_name) or []
        except Exception:
            pass
        root = self.task_tree.invisibleRootItem()
        node_map = {}
        for t in sorted(tasks):
            parts = t.split('/')
            parent = root
            accum = []
            for i, p in enumerate(parts):
                accum.append(p)
                key = "/".join(accum)
                if i == len(parts) - 1:
                    leaf = QTreeWidgetItem([p])
                    leaf.setData(0, Qt.UserRole, t)
                    parent.addChild(leaf)
                else:
                    item = node_map.get(key)
                    if not item: item = QTreeWidgetItem([p]); parent.addChild(item); node_map[key] = item
                    parent = item
        self.task_tree.expandToDepth(2)

    def _get_selected_task(self) -> Optional[str]:
        items = self.task_tree.selectedItems()
        if not items: return None
        return items[0].data(0, Qt.UserRole)

    def _parse_params(self) -> Optional[dict]:
        txt = self.params_edit.toPlainText().strip()
        if not txt: return {}
        try:
            data = yaml.safe_load(txt)
            if data is None: return {}
            if not isinstance(data, dict): raise ValueError("参数覆盖必须是字典（YAML 映射）")
            return data
        except Exception as e:
            QMessageBox.critical(self, "参数错误", f"无法解析参数 YAML：\n{e}")
            return None

    def _emit_run_now(self):
        task_name = self._get_selected_task()
        if not task_name: QMessageBox.warning(self, "请选择任务", "请在任务列表中选择一个具体的任务。"); return
        plan = self.plan_combo.currentText() or ""
        params = self._parse_params()
        if params is None: return
        if self.env_combo.currentText(): params = dict(params); params.setdefault("_env", self.env_combo.currentText())
        self.run_now_requested.emit(plan, task_name, params)

    def _emit_add_to_queue(self):
        task_name = self._get_selected_task()
        if not task_name: QMessageBox.warning(self, "请选择任务", "请在任务列表中选择一个具体的任务。"); return
        plan = self.plan_combo.currentText() or ""
        params = self._parse_params()
        if params is None: return
        if self.env_combo.currentText(): params = dict(params); params.setdefault("_env", self.env_combo.currentText())
        payload = {"plan": plan, "task_name": task_name, "params_override": params, "env": self.env_combo.currentText()}
        self.add_to_queue_requested.emit(payload)


class RunQueueWidget(QWidget):
    queue_changed = Signal()
    play_serial_requested = Signal()
    play_parallel_requested = Signal(int)
    stop_all_requested = Signal()
    pause_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: List[QueueItem] = []
        self.paused = False
        v = QVBoxLayout(self)
        grp = QGroupBox("待做任务队列")
        v.addWidget(grp)
        gl = QVBoxLayout(grp)
        ctrl = QHBoxLayout()
        self.btn_play_serial = QPushButton("▶︎ 串行执行")
        self.btn_play_parallel = QPushButton("⏩ 并行执行")
        self.spin_conc = QSpinBox()
        self.spin_conc.setRange(1, 16)
        self.spin_conc.setValue(2)
        self.btn_pause = QPushButton("⏸ 暂停")
        self.btn_pause.setCheckable(True)
        self.btn_stop_all = QPushButton("⏹ Stop All")
        self.btn_clear = QPushButton("清空队列")
        ctrl.addWidget(self.btn_play_serial)
        ctrl.addWidget(self.btn_play_parallel)
        ctrl.addWidget(QLabel("并发上限:"))
        ctrl.addWidget(self.spin_conc)
        ctrl.addStretch()
        ctrl.addWidget(self.btn_pause)
        ctrl.addWidget(self.btn_stop_all)
        ctrl.addWidget(self.btn_clear)
        gl.addLayout(ctrl)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Plan", "Task", "Mode", "Status", "Env", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        gl.addWidget(self.table, 1)
        self.btn_play_serial.clicked.connect(self.play_serial_requested.emit)
        self.btn_play_parallel.clicked.connect(lambda: self.play_parallel_requested.emit(self.spin_conc.value()))
        self.btn_stop_all.clicked.connect(self.stop_all_requested.emit)
        self.btn_pause.toggled.connect(self._on_pause_toggled)
        self.btn_clear.clicked.connect(self.clear)

    def _on_pause_toggled(self, checked: bool):
        self.paused = checked; self.pause_toggled.emit(checked)

    def add_item(self, item: QueueItem):
        self.items.append(item); self._append_row(item); self.queue_changed.emit()

    def clear(self):
        self.items.clear(); self.table.setRowCount(0); self.queue_changed.emit()

    def _append_row(self, item: QueueItem):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(item.plan))
        self.table.setItem(r, 1, QTableWidgetItem(item.task_name))
        self.table.setItem(r, 2, QTableWidgetItem(item.mode))
        self.table.setItem(r, 3, QTableWidgetItem(item.status))
        self.table.setItem(r, 4, QTableWidgetItem(item.env))
        cell = QWidget()
        h = QHBoxLayout(cell)
        h.setContentsMargins(0, 0, 0, 0)
        btn_up = QPushButton("↑")
        btn_down = QPushButton("↓")
        btn_del = QPushButton("🗑")
        h.addWidget(btn_up)
        h.addWidget(btn_down)
        h.addWidget(btn_del)
        h.addStretch()
        self.table.setCellWidget(r, 5, cell)

        def do_up(idx=r):
            if idx <= 0: return
            self.items[idx - 1], self.items[idx] = self.items[idx], self.items[idx - 1]
            self._reload_table()

        def do_down(idx=r):
            if idx >= len(self.items) - 1: return
            self.items[idx + 1], self.items[idx] = self.items[idx], self.items[idx + 1]
            self._reload_table()

        def do_del(idx=r):
            if 0 <= idx < len(self.items): del self.items[idx]; self._reload_table()

        btn_up.clicked.connect(do_up)
        btn_down.clicked.connect(do_down)
        btn_del.clicked.connect(do_del)

    def _reload_table(self):
        self.table.setRowCount(0)
        for it in self.items: self._append_row(it)
        self.queue_changed.emit()

    def set_item_status(self, item: QueueItem, status: str):
        item.status = status
        for r in range(self.table.rowCount()):
            if (self.table.item(r, 0).text(), self.table.item(r, 1).text()) == (item.plan, item.task_name):
                self.table.item(r, 3).setText(status)
                break


class RunnerPage(QWidget):
    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        main_split = QSplitter(Qt.Horizontal, self)
        left = QWidget()
        right_split = QSplitter(Qt.Vertical)
        main_split.addWidget(left)
        main_split.addWidget(right_split)
        main_split.setStretchFactor(0, 0)
        main_split.setStretchFactor(1, 1)

        lv = QVBoxLayout(left)
        lv.setContentsMargins(6, 6, 6, 6)
        self.picker = TaskPickerWidget(bridge)
        lv.addWidget(self.picker)
        self.queue = RunQueueWidget()
        lv.addWidget(self.queue, 1)

        self.detail_panel = TaskRunDetailPanel()
        self.logs = LiveLogView()
        right_split.addWidget(self.detail_panel)
        right_split.addWidget(self.logs)
        right_split.setStretchFactor(0, 6)
        right_split.setStretchFactor(1, 4)

        outer = QVBoxLayout(self)
        header = QHBoxLayout()
        self.status_label = QLabel("状态: IDLE")
        header.addWidget(self.status_label)
        header.addStretch()
        outer.addLayout(header)
        outer.addWidget(main_split, 1)

        self.state = "IDLE"
        self.current_plan: Optional[str] = None
        self.current_task_name: Optional[str] = None
        self.current_task_def: Optional[Dict[str, Any]] = None

        self.bridge.runner_event_received.connect(self._on_runner_event)
        self.bridge.raw_event_received.connect(self._on_raw_log)
        self.picker.run_now_requested.connect(self._run_single_now)
        self.picker.add_to_queue_requested.connect(self._add_to_queue)
        self.queue.play_serial_requested.connect(self._play_serial)
        self.queue.play_parallel_requested.connect(self._play_parallel)
        self.queue.stop_all_requested.connect(self._stop_all)
        self.queue.pause_toggled.connect(self._pause_toggled)

        self._dispatch_timer = QTimer(self)
        self._dispatch_timer.setInterval(150)
        self._dispatch_timer.timeout.connect(self._dispatch_loop)
        self._dispatch_timer.start()
        self._parallel_max: int = 1
        self._parallel_mode: bool = False

        self.bridge.attach_runner_event_pump()
        self.picker.task_tree.itemSelectionChanged.connect(self._auto_load_task_details)

    def _set_state(self, s: str):
        self.state = s
        self.status_label.setText(f"状态: {s}")

    def _auto_load_task_details(self):
        items = self.picker.task_tree.selectedItems()
        if not items: return
        task_name = items[0].data(0, Qt.UserRole)
        if not task_name: return
        plan = self.picker.plan_combo.currentText()

        if (self.current_plan, self.current_task_name) == (plan, task_name): return

        parts = task_name.split('/')
        if len(parts) > 1:
            file_rel_path = f"tasks/{'/'.join(parts[:-1])}.yaml"
            task_key = parts[-1]
        else:
            file_rel_path = f"tasks/{task_name}.yaml"
            task_key = task_name

        try:
            content = self.bridge.read_task_file(plan, file_rel_path)
            data = yaml.safe_load(content) or {}
            task_def = data.get(task_key)
            if not isinstance(task_def, dict): raise ValueError(f"任务键 '{task_key}' 未在文件中定义")

            self.current_plan = plan
            self.current_task_name = task_name
            self.current_task_def = task_def
            self.detail_panel.load_task_definition(plan, task_name, task_def)
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"无法加载任务详情 '{file_rel_path}'：\n{e}")
            self.detail_panel.clear_panel()

    @Slot(str, str, dict)
    def _run_single_now(self, plan: str, task_name: str, params: dict):
        if (self.current_plan, self.current_task_name) != (plan, task_name):
            self._switch_to_task(plan, task_name)

        if self.current_task_def:
            self.detail_panel.load_task_definition(plan, task_name, self.current_task_def)

        ok = self._do_run_ad_hoc(plan, task_name, params)
        if ok: self._set_state("RUNNING")

    @Slot(dict)
    def _add_to_queue(self, payload: dict):
        item = QueueItem(id=str(uuid.uuid4()), plan=payload["plan"], task_name=payload["task_name"],
                         params_override=payload.get("params_override") or {}, env=payload.get("env") or "Default",
                         mode="serial")
        self.queue.add_item(item)
        self.logs.append(f"已加入队列：{item.plan}/{item.task_name}", tag="STEP")

    def _play_serial(self):
        self._parallel_mode = False
        self._parallel_max = 1
        self._set_state("RUNNING")
        self.logs.append("开始串行执行队列…", tag="STEP")

    def _play_parallel(self, conc: int):
        self._parallel_mode = True
        self._parallel_max = max(1, conc)
        self._set_state("RUNNING")
        self.logs.append(f"开始并行执行队列（并发上限={self._parallel_max}）…", tag="STEP")

    def _stop_all(self):
        try:
            self._set_state("STOPPING")
            self.logs.append("正在停止调度器并重启（StopAll）…", tag="STEP")
            self.bridge.stop_scheduler()
            self.bridge.start_scheduler()
            self.logs.append("StopAll 完成。", tag="STEP")
            for it in self.queue.items:
                if it.status in ("queued", "running"): it.status = "cancelled"
            self.queue._reload_table()
            self._set_state("IDLE")
            self.detail_panel.clear_panel()
        except Exception as e:
            QMessageBox.critical(self, "StopAll 失败", str(e))
            self._set_state("IDLE")

    def _pause_toggled(self, paused: bool):
        self.logs.append("已暂停出队" if paused else "已恢复出队", tag="STEP")

    def _dispatch_loop(self):
        if self.state != "RUNNING" or self.queue.paused: return
        running_now = sum(1 for it in self.queue.items if it.status == "running")
        queued_now = sum(1 for it in self.queue.items if it.status == "queued")
        cap = (self._parallel_max if self._parallel_mode else 1) - (running_now + queued_now)
        if cap <= 0: return
        dispatched = 0
        for it in self.queue.items:
            if dispatched >= cap: break
            if it.status == "pending":
                params = dict(it.params_override or {})
                params.setdefault("__runner_tag", it.client_run_tag)
                ok = self._do_run_ad_hoc(it.plan, it.task_name, params)
                if ok:
                    it.status = "queued"
                    self.queue.set_item_status(it, "queued")
                    self.logs.append(f"已入 Core 队列：{it.plan}/{it.task_name}", tag="STEP")
                    dispatched += 1
        if all(it.status in ("ok", "failed", "cancelled", "skipped") for it in self.queue.items if
               it.status != "pending"):
            if all(it.status not in ("queued", "running") for it in self.queue.items): self._set_state("IDLE")

    def _do_run_ad_hoc(self, plan: str, task_name: str, params: dict) -> bool:
        try:
            res = self.bridge.run_ad_hoc(plan, task_name, params or {})
            if not isinstance(res, dict) or res.get("status") != "success":
                msg = res.get("message") if isinstance(res, dict) else str(res)
                self.logs.append(f"运行失败：{msg}", level="ERROR")
                QMessageBox.critical(self, "运行失败", msg or "未知错误")
                return False
            self.logs.append(f"已触发运行：{plan}/{task_name}", tag="STEP")
            return True
        except Exception as e:
            self.logs.append(f"运行调用异常：{e}", level="ERROR")
            QMessageBox.critical(self, "运行调用异常", str(e))
            return False

    @Slot(dict)
    def _on_runner_event(self, ev: dict):

        self.detail_panel.update_for_event(ev)

        try:
            name = ev.get("name", "unknown_event")
            # Use default=str to handle non-serializable objects like datetime
            payload_str = json.dumps(ev.get("payload", {}), indent=2, ensure_ascii=False, default=str)
            self.logs.append(f"{name}\n{payload_str}", tag="EVENT")
        except Exception:
            self.logs.append(str(ev), tag="EVENT")

    def _switch_to_task(self, plan: str, task_name: str):
        if (self.current_plan, self.current_task_name) == (plan, task_name): return
        try:
            # This is a simplified way to find and select the item in the tree
            # A more robust solution might involve iterating through the tree
            items = self.picker.task_tree.findItems(task_name.split('/')[-1], Qt.MatchFlag.MatchRecursive)
            if items: self.picker.task_tree.setCurrentItem(items[0])
            self._auto_load_task_details()
            self.logs.append(f"运行视图已切换到: {plan}/{task_name}", tag="STEP")
        except Exception as e:
            self.logs.append(f"自动切换视图失败: {e}", level="ERROR")

    @Slot(dict)
    def _on_raw_log(self, event: dict):
        if (event or {}).get("name") != "log.emitted": return
        rec = (event.get("payload") or {}).get("log_record") or {}
        message = rec.get("message", "")
        level = rec.get("level", "INFO")
        self.logs.append(message, level=level)

        try:
            m_start = re.search(r"开始执行主任务:\s*'([^']+)'", message)
            m_ok = re.search(r"任务\s*'([^']+)'\s*执行成功", message)
            m_failed = re.search(r"任务\s*'([^']+)'\s*执行.*失败", message)

            def find_item(full_task_id: str) -> Optional[QueueItem]:
                for it in self.queue.items:
                    if f"{it.plan}/{it.task_name}" == full_task_id: return it
                return None

            if m_start:
                full = m_start.group(1)
                it = find_item(full)
                if it and it.status in ("queued", "pending"): it.status = "running"; self.queue.set_item_status(it,
                                                                                                                "running")
                plan, task_name = full.split("/", 1)
                self._switch_to_task(plan, task_name)

            def finish_as(full: str, status: str):
                it = find_item(full)
                if it: it.status = status; self.queue.set_item_status(it, status)
                if all(x.status in ("ok", "failed", "cancelled", "skipped") for x in self.queue.items if
                       x.status != "pending"):
                    if all(x.status not in ("queued", "running") for x in self.queue.items): self._set_state("IDLE")

            if m_ok:
                finish_as(m_ok.group(1), "ok")
            elif m_failed:
                finish_as(m_failed.group(1), "failed")
        except Exception as e:
            print(f"Error parsing raw log for state: {e}")

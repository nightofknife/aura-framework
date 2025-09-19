# aura_ide/panels/runner_panel/detail_panel.py

import json
import time
from typing import Dict, Any, List, Optional

import yaml
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QColor, QPalette
from PySide6.QtWidgets import (
    QWidget, QSplitter, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QTreeWidget, QTreeWidgetItem, QGroupBox, QTabWidget, QHeaderView, QApplication, QStyle,
    QProgressBar, QCheckBox, QAbstractItemView
)

# Icon cache
ICONS: Dict[str, QIcon] = {}


def get_icon(name: str) -> QIcon:
    if name in ICONS: return ICONS[name]
    icon = {
        "pending": QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight),
        "running": QApplication.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload),
        "success": QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton),
        "failed": QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton),
        "skipped": QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DialogDiscardButton),
    }.get(name)
    if icon: ICONS[name] = icon
    return icon or QIcon()


class TaskRunDetailPanel(QWidget):
    COL_STATUS, COL_STEP, COL_START, COL_DURATION, COL_DETAILS = range(5)

    def __init__(self, parent=None):
        super().__init__(parent)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        header_group = QGroupBox("任务总览")
        main_layout.addWidget(header_group)
        header_layout = QVBoxLayout(header_group)
        self.plan_label = QLabel("Plan: -")
        self.task_label = QLabel("任务: -")
        self.description_label = QLabel("描述: -")
        self.description_label.setWordWrap(True)
        self.status_label = QLabel("状态: [未运行]")
        font = self.status_label.font()
        font.setBold(True)
        self.status_label.setFont(font)
        summary_layout = QHBoxLayout()
        self.start_time_label = QLabel("开始: -")
        self.duration_label = QLabel("总耗时: -")
        summary_layout.addWidget(self.status_label)
        summary_layout.addStretch()
        summary_layout.addWidget(self.start_time_label)
        summary_layout.addWidget(self.duration_label)
        header_layout.addWidget(self.plan_label)
        header_layout.addWidget(self.task_label)
        header_layout.addWidget(self.description_label)
        header_layout.addLayout(summary_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        main_layout.addWidget(splitter, 1)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("步骤执行列表"))
        self.step_tree = QTreeWidget()
        self.step_tree.setHeaderLabels(["", "步骤与动作", "开始时间", "耗时", "详情/错误"])
        self.step_tree.header().setSectionResizeMode(self.COL_STEP, QHeaderView.ResizeMode.Stretch)
        self.step_tree.setColumnWidth(self.COL_STATUS, 30)
        self.step_tree.setColumnWidth(self.COL_START, 100)
        self.step_tree.setColumnWidth(self.COL_DURATION, 70)
        left_layout.addWidget(self.step_tree)

        progress_layout = QHBoxLayout()
        self.auto_scroll_checkbox = QCheckBox("自动滚动到当前步骤")
        self.auto_scroll_checkbox.setChecked(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m (%p%)")
        progress_layout.addWidget(self.auto_scroll_checkbox)
        progress_layout.addWidget(self.progress_bar, 1)
        left_layout.addLayout(progress_layout)
        splitter.addWidget(left_widget)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.params_edit = QPlainTextEdit()
        self.params_edit.setReadOnly(True)
        self.context_edit = QPlainTextEdit()
        self.context_edit.setReadOnly(True)
        self.events_edit = QPlainTextEdit()
        self.events_edit.setReadOnly(True)
        self.tabs.addTab(self.params_edit, "运行参数")
        self.tabs.addTab(self.context_edit, "实时上下文")
        self.tabs.addTab(self.events_edit, "原始事件")
        right_layout.addWidget(self.tabs)
        splitter.addWidget(right_widget)
        splitter.setSizes([600, 400])

        # State variables
        self._step_items: Dict[str, QTreeWidgetItem] = {}
        self._step_events: Dict[str, List[Dict]] = {}
        self._run_start_time: Optional[float] = None
        self._step_start_times: Dict[str, float] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._update_durations)
        self.step_tree.currentItemChanged.connect(self._on_step_selected)

        self._current_task_id: Optional[str] = None
        self._is_legacy_list = False
        self._legacy_list_step_order: List[str] = []
        self._legacy_list_current_index = -1

        # --- NEW: Reliable state storage ---
        self._step_states: Dict[str, str] = {}

    def clear_panel(self):
        self.plan_label.setText("Plan: -")
        self.task_label.setText("任务: -")
        self.description_label.setText("描述: -")
        self.status_label.setText("状态: [未运行]")
        self.start_time_label.setText("开始: -")
        self.duration_label.setText("总耗时: -")
        self.step_tree.clear()
        self.params_edit.clear()
        self.context_edit.clear()
        self.events_edit.clear()

        self._step_items = {}
        self._step_events = {}
        self._step_states = {}
        self._run_start_time = None
        self._step_start_times = {}
        if self._timer.isActive(): self._timer.stop()

        self._current_task_id = None
        self._is_legacy_list = False
        self._legacy_list_step_order = []
        self._legacy_list_current_index = -1

        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.auto_scroll_checkbox.setChecked(True)

    def load_task_definition(self, plan_name: str, task_name: str, task_def: Dict[str, Any]):
        self.clear_panel()
        self._current_task_id = f"{plan_name}/{task_name}"

        self.plan_label.setText(f"Plan: {plan_name}")
        self.task_label.setText(f"任务: {task_name}")
        desc = task_def.get('meta', {}).get('description', '无')
        self.description_label.setText(f"描述: {desc}")

        steps = task_def.get('steps', {})

        if isinstance(steps, list):
            self._is_legacy_list = True
            steps_dict = {}
            for i, step_def in enumerate(steps):
                step_id = step_def.get('name', f'step_{i}')
                steps_dict[step_id] = step_def
                self._legacy_list_step_order.append(step_id)
            steps = steps_dict
        else:
            self._is_legacy_list = False

        for step_id, step_def in steps.items():
            action = step_def.get('action', 'N/A')
            item = QTreeWidgetItem(["", f"{step_id} [{action}]", "", "", ""])
            self._step_states[step_id] = "PENDING"
            item.setIcon(self.COL_STATUS, get_icon("pending"))
            self.step_tree.addTopLevelItem(item)
            self._step_items[step_id] = item

        total_steps = len(self._step_items)
        if total_steps > 0:
            self.progress_bar.setMaximum(total_steps)
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)

    def update_for_event(self, event: Dict[str, Any]):
        event_name = event.get("name", "")
        payload = event.get("payload", {})

        event_plan = payload.get('plan_name')
        event_task = payload.get('task_name')
        if not event_plan or not event_task: return

        event_task_id = f"{event_plan}/{event_task}"
        if self._current_task_id != event_task_id:
            return

        if event_name == 'task.started':
            self._legacy_list_current_index = -1
            self._run_start_time = payload.get('start_time', time.time())
            self.status_label.setText("状态: [运行中...]")
            self.start_time_label.setText(f"开始: {time.strftime('%H:%M:%S', time.localtime(self._run_start_time))}")
            initial_context = payload.get('initial_context', {})
            self.params_edit.setPlainText(yaml.dump(initial_context, allow_unicode=True, sort_keys=False))
            self.context_edit.setPlainText(yaml.dump(initial_context, allow_unicode=True, sort_keys=False))
            if not self._timer.isActive(): self._timer.start()

        elif event_name == 'task.finished':
            if self._timer.isActive(): self._timer.stop()
            status = payload.get('final_status', 'unknown').upper()
            self.status_label.setText(f"状态: [{status}]")
            self._update_durations()

        elif event_name.startswith('step.'):
            step_id_from_event = payload.get('step_id')

            if self._is_legacy_list and step_id_from_event == '__legacy_linear_task':
                self._handle_legacy_list_event(event_name, payload)
            else:
                self._handle_dag_step_event(event_name, payload)

    def _handle_dag_step_event(self, event_name: str, payload: Dict):
        step_id = payload.get('step_id')
        item = self._step_items.get(step_id)
        if not item: return
        self._update_item_from_event(item, step_id, event_name, payload)
        self._update_progress()



    def _handle_legacy_list_event(self, event_name: str, payload: Dict):
        if event_name == 'step.started':
            self._legacy_list_current_index = 0
            if 0 <= self._legacy_list_current_index < len(self._legacy_list_step_order):
                step_id = self._legacy_list_step_order[self._legacy_list_current_index]
                item = self._step_items.get(step_id)
                if item:
                    self._update_item_from_event(item, step_id, event_name, payload)

        elif event_name == 'step.succeeded':
            # Mark ALL steps as successful
            for step_id in self._legacy_list_step_order:
                item = self._step_items.get(step_id)
                if item and self._step_states.get(step_id) in ("PENDING", "RUNNING"):
                    self._step_states[step_id] = "SUCCESS"
                    item.setIcon(self.COL_STATUS, get_icon("success"))
            self.context_edit.setPlainText(
                yaml.dump(payload.get('context_after_step', {}), allow_unicode=True, sort_keys=False))
            self._update_progress()

        elif event_name == 'step.failed':
            # Mark current as failed, subsequent as skipped
            if 0 <= self._legacy_list_current_index < len(self._legacy_list_step_order):
                # Mark current as failed
                failed_step_id = self._legacy_list_step_order[self._legacy_list_current_index]
                item = self._step_items.get(failed_step_id)
                if item:
                    self._update_item_from_event(item, failed_step_id, event_name, payload)
                # Mark subsequent as skipped
                for i in range(self._legacy_list_current_index + 1, len(self._legacy_list_step_order)):
                    skipped_step_id = self._legacy_list_step_order[i]
                    item = self._step_items.get(skipped_step_id)
                    if item:
                        self._step_states[skipped_step_id] = "SKIPPED"
                        item.setIcon(self.COL_STATUS, get_icon("skipped"))
                        item.setText(self.COL_DETAILS, "Previous step failed")
            self._update_progress()

    def _update_item_from_event(self, item: QTreeWidgetItem, step_id: str, event_name: str, payload: Dict):
        self._step_events.setdefault(step_id, []).append(payload)

        if event_name == 'step.started':
            self._step_states[step_id] = "RUNNING"
            item.setIcon(self.COL_STATUS, get_icon("running"))
            start_time = payload.get('start_time', time.time())
            self._step_start_times[step_id] = start_time
            item.setText(self.COL_START, time.strftime('%H:%M:%S', time.localtime(start_time)))
            for i in reversed(range(item.childCount())): item.removeChild(item.child(i))
            input_params = payload.get('step_input_params', {})
            child = QTreeWidgetItem(["[P] 输入:", json.dumps(input_params, ensure_ascii=False, indent=2)])
            item.addChild(child)
            item.setExpanded(True)
            if self.auto_scroll_checkbox.isChecked():
                self.step_tree.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)

        elif event_name == 'step.succeeded':
            self._step_states[step_id] = "SUCCESS"
            item.setIcon(self.COL_STATUS, get_icon("success"))
            duration = payload.get('duration')
            if duration is not None: item.setText(self.COL_DURATION, f"{duration:.2f}s")
            self.context_edit.setPlainText(
                yaml.dump(payload.get('context_after_step', {}), allow_unicode=True, sort_keys=False))
            output = payload.get('step_output', {})
            child = QTreeWidgetItem(["[O] 输出:", json.dumps(output, ensure_ascii=False, indent=2)])
            item.addChild(child)

        elif event_name == 'step.failed':
            self._step_states[step_id] = "FAILED"
            item.setIcon(self.COL_STATUS, get_icon("failed"))
            duration = payload.get('duration')
            if duration is not None: item.setText(self.COL_DURATION, f"{duration:.2f}s")
            error_msg = payload.get('error_message', '未知错误')
            item.setText(self.COL_DETAILS, error_msg)
            item.setForeground(self.COL_DETAILS, self.palette().color(QPalette.ColorRole.PlaceholderText))

        if self.step_tree.currentItem() == item or self.step_tree.currentItem() is None:
            self._on_step_selected(item)

    def _update_durations(self):
        now = time.time()
        if self._run_start_time:
            self.duration_label.setText(f"总耗时: {now - self._run_start_time:.2f}s")

        for step_id, item in self._step_items.items():
            if self._step_states.get(step_id) == "RUNNING" and step_id in self._step_start_times:
                item.setText(self.COL_DURATION, f"{now - self._step_start_times[step_id]:.2f}s")

    def _update_progress(self):
        if not self.progress_bar.isVisible(): return

        completed_count = 0
        for state in self._step_states.values():
            if state in ("SUCCESS", "FAILED", "SKIPPED"):
                completed_count += 1
        self.progress_bar.setValue(completed_count)

    def _on_step_selected(self, current: Optional[QTreeWidgetItem], previous: Optional[QTreeWidgetItem] = None):
        if not current:
            self.events_edit.clear()
            return

        parent = current.parent() or current
        step_id = ""
        for sid, item in self._step_items.items():
            if item == parent:
                step_id = sid
                break

        if step_id and step_id in self._step_events:
            self.events_edit.setPlainText(
                json.dumps(self._step_events[step_id], indent=2, ensure_ascii=False, default=str))
        else:
            self.events_edit.clear()




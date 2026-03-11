# -*- coding: utf-8 -*-
"""Interactive TUI mode for manual task execution."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import click
from prompt_toolkit.shortcuts import input_dialog, message_dialog, radiolist_dialog, yes_no_dialog

from packages.aura_core.config.loader import get_config_value
from packages.aura_core.runtime.bootstrap import start_runtime, stop_runtime
from packages.aura_core.scheduler import Scheduler

_TERMINAL_STATUSES = {"success", "error", "failed", "timeout", "cancelled"}


@dataclass
class TuiState:
    recent_cids: list[str] = field(default_factory=list)

    def remember_cid(self, cid: str | None) -> None:
        if not cid:
            return
        self.recent_cids = [item for item in self.recent_cids if item != cid]
        self.recent_cids.insert(0, cid)
        del self.recent_cids[20:]


def run_tui() -> None:
    timeout = int(get_config_value("backend.scheduler_startup_timeout_sec", 10))
    scheduler = start_runtime(profile="tui_manual", startup_timeout_sec=timeout)
    state = TuiState()
    try:
        _main_loop(scheduler, state)
    finally:
        stop_runtime()


def _main_loop(scheduler: Scheduler, state: TuiState) -> None:
    while True:
        action = radiolist_dialog(
            title="Aura TUI (Manual Mode)",
            text="选择操作",
            values=[
                ("entry_task", "运行入口任务"),
                ("scheduled_task", "手动触发调度项"),
                ("run_status", "查看最近运行状态"),
                ("exit", "退出"),
            ],
        ).run()

        if action in (None, "exit"):
            return
        if action == "entry_task":
            _run_entry_task(scheduler, state)
        elif action == "scheduled_task":
            _run_scheduled_item(scheduler, state)
        elif action == "run_status":
            _show_recent_status(scheduler, state)


def _run_entry_task(scheduler: Scheduler, state: TuiState) -> None:
    entry_tasks = _load_entry_tasks(scheduler)
    if not entry_tasks:
        message_dialog(title="提示", text="未找到入口任务（meta.entry_point: true）。").run()
        return

    values = []
    task_map: dict[str, dict[str, Any]] = {}
    for task in entry_tasks:
        task_key = task["full_task_id"]
        title = f"{task['plan_name']}/{task['task_ref']}"
        description = ((task.get("meta") or {}).get("description") or "").strip()
        label = f"{title}  -  {description}" if description else title
        values.append((task_key, label))
        task_map[task_key] = task

    selected_key = radiolist_dialog(
        title="入口任务",
        text="上下选择任务，回车运行",
        values=values,
    ).run()
    if not selected_key:
        return

    task = task_map[selected_key]
    inputs = _collect_inputs(task.get("meta") or {})
    if inputs is None:
        return

    result = scheduler.run_ad_hoc_task(task["plan_name"], task["task_ref"], inputs)
    _handle_dispatch_result(scheduler, state, result)


def _run_scheduled_item(scheduler: Scheduler, state: TuiState) -> None:
    schedule_items = scheduler.get_schedule_status() or []
    if not schedule_items:
        message_dialog(title="提示", text="当前没有可用调度项。").run()
        return

    values = []
    item_map: dict[str, dict[str, Any]] = {}
    for item in schedule_items:
        item_id = str(item.get("id") or "")
        if not item_id:
            continue
        plan_name = item.get("plan_name") or "unknown_plan"
        task_name = item.get("task") or item.get("task_name") or "unknown_task"
        status = item.get("status") or "idle"
        label = f"{item_id}  -  {plan_name}/{task_name}  [{status}]"
        values.append((item_id, label))
        item_map[item_id] = item

    if not values:
        message_dialog(title="提示", text="调度项缺少可用 ID。").run()
        return

    selected_id = radiolist_dialog(
        title="调度项",
        text="上下选择调度项，回车手动触发",
        values=values,
    ).run()
    if not selected_id:
        return

    result = scheduler.run_manual_task(selected_id)
    _handle_dispatch_result(scheduler, state, result)


def _show_recent_status(scheduler: Scheduler, state: TuiState) -> None:
    if not state.recent_cids:
        message_dialog(title="提示", text="暂无最近运行记录。").run()
        return

    statuses = scheduler.get_batch_task_status(state.recent_cids)
    lines = []
    for item in statuses:
        cid = item.get("cid")
        status = item.get("status")
        plan_name = item.get("plan_name") or "-"
        task_name = item.get("task_name") or "-"
        lines.append(f"{cid}  |  {status}  |  {plan_name}/{task_name}")

    message_dialog(
        title="最近运行状态",
        text="\n".join(lines[:20]) or "无数据",
    ).run()


def _load_entry_tasks(scheduler: Scheduler) -> list[dict[str, Any]]:
    tasks = scheduler.get_all_task_definitions_with_meta()
    entry_tasks = []
    for task in tasks:
        meta = task.get("meta") or {}
        if bool(meta.get("entry_point", False)):
            entry_tasks.append(task)
    entry_tasks.sort(key=lambda x: str(x.get("full_task_id") or ""))
    return entry_tasks


def _collect_inputs(meta: dict[str, Any]) -> dict[str, Any] | None:
    inputs_meta = meta.get("inputs") or []
    if not isinstance(inputs_meta, list) or not inputs_meta:
        raw = input_dialog(
            title="任务输入",
            text="输入 JSON（留空使用 {}）:",
            default="{}",
        ).run()
        if raw is None:
            return None
        raw = raw.strip()
        if not raw:
            return {}
        try:
            loaded = json.loads(raw)
            if not isinstance(loaded, dict):
                message_dialog(title="输入错误", text="输入必须是 JSON 对象。").run()
                return None
            return loaded
        except Exception as exc:
            message_dialog(title="输入错误", text=f"JSON 解析失败: {exc}").run()
            return None

    collected: dict[str, Any] = {}
    for field in inputs_meta:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        required = bool(field.get("required", False))
        field_type = str(field.get("type") or "string").strip().lower()
        default_value = field.get("default")
        desc = str(field.get("description") or "").strip()
        hint_default = "" if default_value is None else f" (默认: {default_value})"
        prompt = f"{name} [{field_type}]{hint_default}\n{desc}".strip()

        while True:
            raw = input_dialog(title="任务输入", text=prompt, default="" if default_value is None else str(default_value)).run()
            if raw is None:
                return None
            raw = raw.strip()
            if not raw:
                if default_value is not None:
                    collected[name] = default_value
                    break
                if required:
                    message_dialog(title="输入错误", text=f"参数 {name} 为必填。").run()
                    continue
                break
            try:
                collected[name] = _convert_input(raw, field_type)
                break
            except Exception as exc:
                message_dialog(title="输入错误", text=f"参数 {name} 解析失败: {exc}").run()

    return collected


def _convert_input(raw: str, field_type: str) -> Any:
    if field_type in {"int", "integer"}:
        return int(raw)
    if field_type in {"float", "number"}:
        return float(raw)
    if field_type in {"bool", "boolean"}:
        lowered = raw.lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
        raise ValueError("布尔值仅支持 true/false/yes/no/1/0")
    if field_type in {"array", "list", "object", "dict", "map"}:
        return json.loads(raw)
    return raw


def _handle_dispatch_result(scheduler: Scheduler, state: TuiState, result: dict[str, Any]) -> None:
    status = result.get("status")
    message = result.get("message") or ""
    cid = result.get("cid")
    trace_id = result.get("trace_id")

    if status != "success":
        message_dialog(title="执行失败", text=message or "任务提交失败。").run()
        return

    state.remember_cid(cid)
    text = f"提交成功\nCID: {cid}\nTraceID: {trace_id}\n{message}".strip()
    message_dialog(title="任务已提交", text=text).run()

    if cid and yes_no_dialog(title="状态跟踪", text="是否等待任务执行完成？").run():
        _watch_task_until_terminal(scheduler, cid)


def _watch_task_until_terminal(scheduler: Scheduler, cid: str, timeout_sec: int = 600) -> None:
    click.echo(f"[watch] 开始跟踪任务: {cid}")
    start = time.time()
    last_status = "queued"
    while time.time() - start < timeout_sec:
        status_rows = scheduler.get_batch_task_status([cid])
        if not status_rows:
            break
        status = str(status_rows[0].get("status") or "unknown").lower()
        if status != last_status:
            click.echo(f"[watch] {cid} -> {status}")
            last_status = status
        if status in _TERMINAL_STATUSES:
            break
        time.sleep(1)

    message_dialog(title="状态跟踪结束", text=f"CID: {cid}\n最终状态: {last_status}").run()

# -*- coding: utf-8 -*-
"""Observability and run-tracking service."""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from packages.aura_core.config.loader import get_config_value
from packages.aura_core.observability.events import Event, EventBus
from packages.aura_core.observability.logging.core_logger import logger


class ObservabilityService:
    def __init__(self, event_bus: Any, base_path: Path, running_tasks_provider: Optional[Callable[[], int]] = None):
        self._event_bus = event_bus
        self._running_tasks_provider = running_tasks_provider
        self._lock = threading.RLock()

        self._obs_runs: Dict[str, Dict[str, Any]] = {}
        self._obs_ready: Dict[str, Dict[str, Any]] = {}
        self._obs_delayed: Dict[str, Dict[str, Any]] = {}
        self._obs_runs_by_trace: Dict[str, str] = {}

        # ✅ NEW: 已完成任务的历史记录（选项3）
        self._obs_completed: Dict[str, Dict[str, Any]] = {}

        # ✅ NEW: TTL清理配置（选项4）
        # 已完成任务保留时间（秒），默认30分钟
        self.completed_task_ttl = int(get_config_value("observability.completed_task_ttl", 1800))
        # 清理间隔（秒），默认5分钟
        self.cleanup_interval = int(get_config_value("observability.cleanup_interval", 300))
        # 最大保留的已完成任务数量，默认1000
        self.max_completed_tasks = int(get_config_value("observability.max_completed_tasks", 1000))

        # 后台清理任务
        self._cleanup_task: Optional[asyncio.Task] = None

        runs_dir_cfg = get_config_value(
            "observability.runs.dir",
            str(base_path / "logs" / "runs"),
        )
        self.persist_runs = bool(get_config_value("observability.persist_runs", False))
        self.run_history_dir = Path(runs_dir_cfg).resolve()

        self._metrics: Dict[str, Any] = {
            "tasks_started": 0,
            "tasks_finished": 0,
            "tasks_success": 0,
            "tasks_error": 0,
            "tasks_failed": 0,
            "tasks_timeout": 0,
            "tasks_cancelled": 0,
            "tasks_running": 0,
            "nodes_total": 0,
            "nodes_succeeded": 0,
            "nodes_failed": 0,
            "nodes_duration_ms_sum": 0.0,
            "nodes_duration_ms_avg": 0.0,
            "updated_at": time.time(),
        }

        self._ui_event_queue: queue.Queue = queue.Queue(maxsize=0)

    def get_ui_event_queue(self) -> queue.Queue:
        return self._ui_event_queue

    async def mirror_event_to_ui_queue(self, event: Event):
        if self._ui_event_queue:
            try:
                self._ui_event_queue.put_nowait(event.to_dict())
            except queue.Full:
                pass

    def _update_metrics_from_event(self, name: str, payload: Dict[str, Any]) -> bool:
        changed = False
        m = self._metrics
        now = time.time()
        if name == "task.started":
            m["tasks_started"] += 1
            m["tasks_running"] = max(0, m.get("tasks_running", 0)) + 1
            changed = True
        elif name == "task.finished":
            m["tasks_finished"] += 1
            m["tasks_running"] = max(0, m.get("tasks_running", 0) - 1)
            status = (payload.get("final_status") or payload.get("status") or "").lower()
            if status == "success":
                m["tasks_success"] += 1
            elif status == "error":
                m["tasks_error"] += 1
            elif status == "failed":
                m["tasks_failed"] += 1
            elif status == "timeout":
                m["tasks_timeout"] += 1
            elif status == "cancelled":
                m["tasks_cancelled"] += 1
            changed = True
        elif name in ("node.finished", "node.failed"):
            m["nodes_total"] += 1
            duration_ms = payload.get("duration_ms")
            if duration_ms is not None:
                try:
                    dur_val = float(duration_ms)
                    m["nodes_duration_ms_sum"] = m.get("nodes_duration_ms_sum", 0.0) + dur_val
                    if m["nodes_total"] > 0:
                        m["nodes_duration_ms_avg"] = m["nodes_duration_ms_sum"] / max(1, m["nodes_total"])
                except Exception:
                    pass
            status = (payload.get("status") or payload.get("final_status") or "").lower()
            if status == "success":
                m["nodes_succeeded"] += 1
            elif status in ("error", "failed"):
                m["nodes_failed"] += 1
            changed = True
        elif name.startswith("queue."):
            changed = True
        if changed:
            m["updated_at"] = now
        return changed

    async def ingest_event(self, event: Event):
        name = (event.name or "").lower()
        p = event.payload or {}
        cid = p.get("cid") or p.get("trace_id")
        trace_id = p.get("trace_id")
        trace_label = p.get("trace_label")
        source = p.get("source")
        parent_cid = p.get("parent_cid")

        if not cid:
            return

        run_snapshot = None
        metrics_changed = False
        persist_event = False
        with self._lock:
            if trace_id and cid:
                self._obs_runs_by_trace.setdefault(trace_id, cid)
            if name == "task.started":
                run = self._obs_runs.setdefault(
                    cid,
                    {
                        "cid": cid,
                        "trace_id": trace_id,
                        "trace_label": trace_label,
                        "source": source,
                        "parent_cid": parent_cid,
                        "plan_name": p.get("plan_name"),
                        "task_name": p.get("task_name"),
                        "started_at": int((p.get("start_time") or 0) * 1000)
                        if p.get("start_time") and p.get("start_time") < 1e12
                        else int(p.get("start_time") or 0),
                        "finished_at": None,
                        "status": "running",
                        "nodes": [],
                        "queue_wait_ms": p.get("queue_wait_ms"),
                        "dequeued_at": p.get("start_time"),
                    },
                )
                if trace_id:
                    run["trace_id"] = trace_id
                if trace_label:
                    run["trace_label"] = trace_label
                if source:
                    run["source"] = source
                if parent_cid is not None:
                    run["parent_cid"] = parent_cid
                if p.get("queue_wait_ms") is not None:
                    run["queue_wait_ms"] = p.get("queue_wait_ms")
                self._obs_ready.pop(cid, None)

                persist_event = True
                run_snapshot = run
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name == "task.finished":
                run = self._obs_runs.setdefault(
                    cid,
                    {
                        "cid": cid,
                        "trace_id": trace_id,
                        "trace_label": trace_label,
                        "source": source,
                        "parent_cid": parent_cid,
                        "plan_name": p.get("plan_name"),
                        "task_name": p.get("task_name"),
                        "started_at": None,
                        "finished_at": None,
                        "status": "unknown",
                        "nodes": [],
                    },
                )
                end_ms = (
                    int((p.get("end_time") or 0) * 1000)
                    if p.get("end_time") and p.get("end_time") < 1e12
                    else int(p.get("end_time") or 0)
                )
                run["finished_at"] = end_ms or run.get("finished_at")
                status = (p.get("final_status") or "unknown").lower()
                run["status"] = "success" if status == "success" else ("error" if status == "error" else status)
                if run.get("started_at") and end_ms:
                    run["duration_ms"] = max(0, end_ms - int(run.get("started_at") or 0))
                if p.get("duration") is not None:
                    run["duration_ms"] = int(float(p.get("duration")) * 1000)
                if trace_id:
                    run["trace_id"] = trace_id
                if trace_label:
                    run["trace_label"] = trace_label
                if source:
                    run["source"] = source
                if parent_cid is not None:
                    run["parent_cid"] = parent_cid
                if p.get("queue_wait_ms") is not None:
                    run["queue_wait_ms"] = p.get("queue_wait_ms")
                if p.get("duration_ms") is not None:
                    run["duration_ms"] = int(p.get("duration_ms") or 0)

                # ✅ NEW: 将完成的任务从运行队列移动到已完成队列（选项3）
                # 添加完成时间戳用于TTL清理
                run["completed_timestamp"] = time.time()
                self._obs_completed[cid] = run
                self._obs_runs.pop(cid, None)

                persist_event = True
                run_snapshot = run
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name == "node.started":
                run = self._obs_runs.setdefault(
                    cid,
                    {
                        "cid": cid,
                        "trace_id": trace_id,
                        "trace_label": trace_label,
                        "source": source,
                        "parent_cid": parent_cid,
                        "plan_name": p.get("plan_name"),
                        "task_name": p.get("task_name"),
                        "started_at": None,
                        "finished_at": None,
                        "status": "running",
                        "nodes": [],
                    },
                )
                node_id = p.get("node_id") or p.get("step_name") or "node"
                start_ts = p.get("start_time") or event.timestamp
                start_ms = (
                    int(start_ts * 1000)
                    if start_ts and isinstance(start_ts, (int, float)) and start_ts < 1e12
                    else int(start_ts or 0)
                )
                nodes = run["nodes"]
                idx = next((i for i, n in enumerate(nodes) if n.get("node_id") == node_id), -1)
                item = {
                    "node_id": node_id,
                    "node_name": p.get("node_name"),
                    "startMs": start_ms,
                    "endMs": None,
                    "status": "running",
                    "loop_index": p.get("loop_index", 0),
                    "loop_item": p.get("loop_item"),
                }
                if idx >= 0:
                    nodes[idx].update(item)
                else:
                    nodes.append(item)
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name in ("node.finished", "node.failed"):
                run = self._obs_runs.setdefault(
                    cid,
                    {
                        "cid": cid,
                        "trace_id": trace_id,
                        "trace_label": trace_label,
                        "source": source,
                        "parent_cid": parent_cid,
                        "plan_name": p.get("plan_name"),
                        "task_name": p.get("task_name"),
                        "started_at": None,
                        "finished_at": None,
                        "status": "running",
                        "nodes": [],
                    },
                )
                node_id = p.get("node_id") or "node"
                end_ts = p.get("end_time") or event.timestamp
                end_ms = (
                    int(end_ts * 1000)
                    if end_ts and isinstance(end_ts, (int, float)) and end_ts < 1e12
                    else int(end_ts or 0)
                )
                status = (p.get("status") or ("error" if name == "node.failed" else "success")).lower()
                nodes = run["nodes"]
                idx = next((i for i, n in enumerate(nodes) if n.get("node_id") == node_id), -1)
                if idx >= 0:
                    nodes[idx].update(
                        {
                            "endMs": end_ms,
                            "status": status,
                            "duration_ms": p.get("duration_ms"),
                            "retry_count": p.get("retry_count"),
                            "exception_type": p.get("exception_type"),
                            "exception_message": p.get("exception_message"),
                            "loop_index": p.get("loop_index", nodes[idx].get("loop_index", 0)),
                            "loop_item": p.get("loop_item", nodes[idx].get("loop_item")),
                        }
                    )
                else:
                    nodes.append(
                        {
                            "node_id": node_id,
                            "node_name": p.get("node_name"),
                            "startMs": end_ms,
                            "endMs": end_ms,
                            "status": status,
                            "duration_ms": p.get("duration_ms"),
                            "retry_count": p.get("retry_count"),
                            "exception_type": p.get("exception_type"),
                            "exception_message": p.get("exception_message"),
                            "loop_index": p.get("loop_index", 0),
                            "loop_item": p.get("loop_item"),
                        }
                    )

                run_snapshot = run
                persist_event = True
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name == "queue.completed":
                run = self._obs_runs.setdefault(
                    cid,
                    {
                        "cid": cid,
                        "trace_id": trace_id,
                        "trace_label": trace_label,
                        "source": source,
                        "parent_cid": parent_cid,
                        "plan_name": p.get("plan_name"),
                        "task_name": p.get("task_name"),
                        "started_at": None,
                        "finished_at": None,
                        "status": "running",
                        "nodes": [],
                    },
                )
                if p.get("queue_wait_ms") is not None:
                    run["queue_wait_ms"] = p.get("queue_wait_ms")
                if p.get("exec_ms") is not None:
                    run["exec_ms"] = p.get("exec_ms")
                if p.get("dequeued_at"):
                    run["dequeued_at"] = int(float(p.get("dequeued_at")) * 1000)
                if p.get("completed_at"):
                    run["completed_at"] = int(float(p.get("completed_at")) * 1000)

                run_snapshot = run
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name == "queue.enqueued":
                item = {
                    "cid": cid,
                    "trace_id": trace_id,
                    "trace_label": trace_label,
                    "source": source,
                    "parent_cid": parent_cid,
                    "plan_name": p.get("plan_name"),
                    "task_name": p.get("task_name"),
                    "priority": p.get("priority"),
                    "enqueued_at": p.get("enqueued_at"),
                    "delay_until": p.get("delay_until"),
                }
                if item["delay_until"]:
                    self._obs_delayed[cid] = item
                else:
                    self._obs_ready[cid] = item

                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name in ("queue.dequeued", "task.started"):
                self._obs_ready.pop(cid, None)
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name == "queue.promoted":
                it = self._obs_delayed.pop(cid, None)
                if it:
                    it["delay_until"] = None
                    self._obs_ready[cid] = it
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

            elif name in ("queue.dropped",):
                self._obs_ready.pop(cid, None)
                self._obs_delayed.pop(cid, None)
                metrics_changed = metrics_changed or self._update_metrics_from_event(name, p)

        if persist_event and run_snapshot and self.persist_runs:
            await self._persist_run_snapshot(cid, run_snapshot)
        if metrics_changed and self._event_bus:
            snap = self.get_metrics_snapshot()
            await self._event_bus.publish(Event(name="metrics.update", payload=snap))

    def get_queue_overview(self) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            ready_list = list(self._obs_ready.values())
            delayed_list = list(self._obs_delayed.values())

        waits = []
        for it in ready_list:
            enq = it.get("enqueued_at")
            if enq:
                waits.append(max(0.0, now - float(enq)))

        avg_wait = float(sum(waits) / len(waits)) if waits else 0.0
        p95 = 0.0
        if waits:
            waits_sorted = sorted(waits)
            k = max(0, int(len(waits_sorted) * 0.95) - 1)
            p95 = float(waits_sorted[k])

        by_plan: Dict[str, int] = {}
        by_pri: Dict[int, int] = {}
        for it in ready_list + delayed_list:
            plan_name = it.get("plan_name") or ""
            by_plan[plan_name] = by_plan.get(plan_name, 0) + 1
            pri = int(it.get("priority") or 0)
            by_pri[pri] = by_pri.get(pri, 0) + 1

        oldest_age = 0.0
        for it in ready_list:
            if it.get("enqueued_at"):
                oldest_age = max(oldest_age, now - float(it["enqueued_at"]))

        return {
            "ready_length": len(ready_list),
            "delayed_length": len(delayed_list),
            "by_plan": [{"plan": k, "count": v} for k, v in by_plan.items()],
            "by_priority": [{"priority": k, "count": v} for k, v in by_pri.items()],
            "avg_wait_sec": avg_wait,
            "p95_wait_sec": p95,
            "oldest_age_sec": oldest_age,
            "throughput": {"m5": 0, "m15": 0, "m60": 0},
        }

    def list_queue(self, state: str, limit: int = 200) -> Dict[str, Any]:
        with self._lock:
            if state == "ready":
                items = list(self._obs_ready.values())
                items.sort(key=lambda x: x.get("enqueued_at") or 0, reverse=True)
            else:
                items = list(self._obs_delayed.values())
                items.sort(key=lambda x: x.get("delay_until") or 0)

        filtered = [it for it in items if it.get("cid")]
        if len(filtered) != len(items):
            logger.warning(
                f"[list_queue] filtered {len(items) - len(filtered)} entries missing cid"
            )

        items = filtered[: max(1, int(limit))]
        for it in items:
            it["__key"] = (
                it.get("trace_id")
                or it.get("cid")
                or f"{it.get('plan_name')}/{it.get('task_name')}:{it.get('enqueued_at') or it.get('delay_until')}"
            )
        return {"items": items, "next_cursor": None}

    def get_metrics_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            snap = dict(self._metrics)
            snap["queue_ready"] = len(self._obs_ready)
            snap["queue_delayed"] = len(self._obs_delayed)
            if self._running_tasks_provider:
                try:
                    snap["running_tasks"] = int(self._running_tasks_provider())
                except Exception:
                    snap["running_tasks"] = 0
            else:
                snap["running_tasks"] = 0
        return snap

    async def _persist_run_snapshot(self, cid: str, run: Dict[str, Any]):
        if not self.persist_runs:
            return
        if not cid or not run:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        try:
            run_copy = json.loads(json.dumps(run, default=str))
        except Exception:
            run_copy = dict(run)
        run_copy.setdefault("cid", cid)
        run_copy.setdefault("trace_id", run_copy.get("trace_id"))
        run_copy["persisted_at"] = int(time.time() * 1000)
        target_path = self.run_history_dir / f"{cid}.json"

        def _write():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(run_copy, f, ensure_ascii=False, indent=2)

        try:
            await loop.run_in_executor(None, _write)
        except Exception as exc:
            logger.error(f"Failed to persist run {cid}: {exc}", exc_info=True)

    def list_persisted_runs(
        self,
        limit: int = 50,
        plan_name: Optional[str] = None,
        task_name: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self.persist_runs:
            return []
        if not self.run_history_dir.exists():
            return []
        try:
            files = sorted(self.run_history_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            return []

        out: List[Dict[str, Any]] = []
        status_lower = status.lower() if status else None
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if plan_name and data.get("plan_name") != plan_name:
                continue
            if task_name and data.get("task_name") != task_name:
                continue
            if status_lower and (data.get("status") or data.get("final_status") or "").lower() != status_lower:
                continue
            data.setdefault("cid", path.stem)
            out.append(data)
            if len(out) >= max(1, int(limit)):
                break
        return out

    def get_persisted_run(self, cid: str) -> Dict[str, Any]:
        if not self.persist_runs or not cid:
            return {}
        target = self.run_history_dir / f"{cid}.json"
        if not target.is_file():
            return {}
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def get_run_timeline(self, cid_or_trace: str) -> Dict[str, Any]:
        with self._lock:
            cid = cid_or_trace
            if cid_or_trace in self._obs_runs_by_trace:
                cid = self._obs_runs_by_trace.get(cid_or_trace, cid_or_trace)

            # ✅ NEW: 先从运行队列查找，再从已完成队列查找
            run = self._obs_runs.get(cid)
            if not run:
                run = self._obs_completed.get(cid)

            if not run:
                return {}
            return {
                "cid": cid,
                "trace_id": run.get("trace_id"),
                "trace_label": run.get("trace_label"),
                "parent_cid": run.get("parent_cid"),
                "plan_name": run.get("plan_name"),
                "task_name": run.get("task_name"),
                "started_at": run.get("started_at"),
                "finished_at": run.get("finished_at"),
                "queue_wait_ms": run.get("queue_wait_ms"),
                "duration_ms": run.get("duration_ms"),
                "exec_ms": run.get("exec_ms"),
                "status": run.get("status"),
                "nodes": run.get("nodes") or [],
            }

    def get_active_runs_snapshot(self) -> List[Dict[str, Any]]:
        import time as _time

        with self._lock:
            active_list = []
            current_time_ms = int(_time.time() * 1000)

            for cid in list(self._obs_runs.keys()):
                run_data = self._obs_runs.get(cid)

                if run_data and run_data.get("status") == "running":
                    active_list.append(run_data)
                else:
                    logger.debug(f"[get_active_runs_snapshot] Task {cid} is running but not in _obs_runs yet")

                    ready_item = self._obs_ready.get(cid, {})

                    active_list.append(
                        {
                            "cid": cid,
                            "trace_id": ready_item.get("trace_id"),
                            "trace_label": ready_item.get("trace_label"),
                            "plan_name": ready_item.get("plan_name"),
                            "task_name": ready_item.get("task_name"),
                            "status": "starting",
                            "started_at": current_time_ms,
                            "finished_at": None,
                            "nodes": [],
                        }
                    )

            for cid, item in self._obs_ready.items():
                if cid not in self._obs_runs:
                    active_list.append(
                        {
                            "cid": cid,
                            "trace_id": item.get("trace_id"),
                            "trace_label": item.get("trace_label"),
                            "plan_name": item.get("plan_name"),
                            "task_name": item.get("task_name"),
                            "status": "queued",
                            "enqueued_at": int(item.get("enqueued_at", 0) * 1000),
                            "started_at": None,
                            "finished_at": None,
                            "nodes": [],
                        }
                    )

            logger.debug(f"[get_active_runs_snapshot] Returning {len(active_list)} active runs")
            return active_list

    def get_batch_task_status(self, cids: List[str]) -> List[Dict[str, Any]]:
        results = []
        with self._lock:
            for cid in cids:
                # ✅ NEW: 先从运行队列查找，再从已完成队列查找
                run_data = self._obs_runs.get(cid)
                if not run_data:
                    run_data = self._obs_completed.get(cid)

                if run_data:
                    results.append(
                        {
                            "cid": cid,
                            "status": run_data.get("status"),
                            "plan_name": run_data.get("plan_name"),
                            "task_name": run_data.get("task_name"),
                            "started_at": run_data.get("started_at"),
                            "finished_at": run_data.get("finished_at"),
                            "nodes": run_data.get("nodes", []),
                        }
                    )
                else:
                    results.append(
                        {
                            "cid": cid,
                            "status": "not_found",
                            "plan_name": None,
                            "task_name": None,
                            "started_at": None,
                            "finished_at": None,
                            "nodes": None,
                        }
                    )

        return results

    # ========== ✅ NEW: TTL清理方法（选项4） ==========

    def _cleanup_completed_tasks(self):
        """清理过期的已完成任务（基于TTL和数量限制）。"""
        now = time.time()
        removed_count = 0

        with self._lock:
            # 1. 基于TTL清理
            expired_cids = [
                cid for cid, run in self._obs_completed.items()
                if now - run.get("completed_timestamp", 0) > self.completed_task_ttl
            ]
            for cid in expired_cids:
                self._obs_completed.pop(cid, None)
                removed_count += 1

            # 2. 基于数量限制清理（保留最新的N个）
            if len(self._obs_completed) > self.max_completed_tasks:
                # 按完成时间排序，删除最旧的
                sorted_items = sorted(
                    self._obs_completed.items(),
                    key=lambda x: x[1].get("completed_timestamp", 0),
                    reverse=True
                )
                # 保留前 max_completed_tasks 个
                to_keep = dict(sorted_items[:self.max_completed_tasks])
                removed = len(self._obs_completed) - len(to_keep)
                self._obs_completed = to_keep
                removed_count += removed

        if removed_count > 0:
            logger.debug(f"[ObservabilityService] Cleaned up {removed_count} completed tasks")

    async def _cleanup_loop(self):
        """后台清理循环任务。"""
        logger.info(f"[ObservabilityService] Cleanup loop started (interval={self.cleanup_interval}s, ttl={self.completed_task_ttl}s)")
        try:
            while True:
                await asyncio.sleep(self.cleanup_interval)
                self._cleanup_completed_tasks()
        except asyncio.CancelledError:
            logger.info("[ObservabilityService] Cleanup loop cancelled")
            raise

    def start_cleanup_task(self):
        """启动后台清理任务。"""
        if self._cleanup_task is None or self._cleanup_task.done():
            try:
                self._cleanup_task = asyncio.create_task(self._cleanup_loop())
                logger.info("[ObservabilityService] Cleanup task started")
            except RuntimeError:
                # 如果没有运行的事件循环，记录警告
                logger.warning("[ObservabilityService] Cannot start cleanup task: no running event loop")

    async def stop_cleanup_task(self):
        """停止后台清理任务。"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("[ObservabilityService] Cleanup task stopped")

    # ========== ✅ NEW: 前端查询API（选项3扩展） ==========

    def get_completed_runs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取已完成任务列表（按完成时间倒序）。"""
        with self._lock:
            sorted_runs = sorted(
                self._obs_completed.values(),
                key=lambda x: x.get("completed_timestamp", 0),
                reverse=True
            )
            return sorted_runs[:limit]

    def get_running_runs(self) -> List[Dict[str, Any]]:
        """获取正在运行的任务列表。"""
        with self._lock:
            return list(self._obs_runs.values())

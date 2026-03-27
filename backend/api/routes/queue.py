# -*- coding: utf-8 -*-
"""Queue routes for task arrangement."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, Query

from backend.api.dependencies import peek_core_scheduler
from backend.api.schemas import (
    GenericMessageResponse,
    QueueItemResponse,
    QueueListResponse,
    QueueOverviewResponse,
    QueueReorderRequest,
)
from packages.aura_core.scheduler import Scheduler

router = APIRouter(tags=["queue"])


def _scheduler_running() -> Scheduler:
    scheduler = peek_core_scheduler()
    if scheduler is None or not bool((scheduler.get_master_status() or {}).get("is_running")):
        raise HTTPException(status_code=409, detail="Scheduler is not running.")
    return scheduler


def _queue_status_from_state(state: str) -> str:
    return "queued" if state == "ready" else "delayed"


def _to_ms(raw):
    if raw is None:
        return None
    value = float(raw)
    if value <= 0:
        return None
    return int(value if value > 1e12 else value * 1000)


@router.get("/queue/overview", response_model=QueueOverviewResponse)
def get_queue_overview() -> QueueOverviewResponse:
    scheduler = peek_core_scheduler()
    if scheduler is None:
        return QueueOverviewResponse()

    overview = scheduler.get_queue_overview() or {}
    ready_count = int(overview.get("ready_length") or 0)
    if scheduler._loop and scheduler._loop.is_running() and scheduler.task_queue is not None:
        ready_count = int(scheduler.task_queue.qsize())
    running = 0
    for run in scheduler.get_active_runs_snapshot():
        if str(run.get("status") or "").lower() in {"running", "starting"}:
            running += 1
    return QueueOverviewResponse(
        ready_count=ready_count,
        running_count=running,
        delayed_count=int(overview.get("delayed_length") or 0),
        ready_length=ready_count,
        delayed_length=int(overview.get("delayed_length") or 0),
        avg_wait_sec=float(overview.get("avg_wait_sec") or 0.0),
    )


@router.get("/queue/list", response_model=QueueListResponse)
def list_queue(
    state: str = Query("ready", pattern="^(ready|delayed)$"),
    limit: int = Query(200, ge=1, le=500),
) -> QueueListResponse:
    scheduler = peek_core_scheduler()
    if scheduler is None:
        return QueueListResponse(items=[])

    payload = scheduler.list_queue(state, limit) or {}
    items: List[QueueItemResponse] = []
    raw_items = payload.get("items", [])
    if state == "ready" and scheduler._loop and scheduler._loop.is_running():
        actual_items = scheduler.run_on_control_loop(scheduler.queue_list_all(), timeout=5.0)
        meta_by_cid = {item.get("cid"): item for item in raw_items}
        raw_items = []
        for item in actual_items:
            cid = item.get("cid")
            meta = meta_by_cid.get(cid, {})
            merged = dict(meta)
            merged.update(item)
            if "task_name" not in merged:
                merged["task_name"] = item.get("task_name")
            raw_items.append(merged)

    for item in raw_items:
        cid = item.get("cid")
        if not cid:
            continue
        task_ref = item.get("task_name")
        if "/" in str(task_ref or "") and "payload" not in item:
            task_ref = None
        if task_ref is None and state == "ready" and scheduler is not None:
            meta_items = payload.get("items", [])
            meta = next((row for row in meta_items if row.get("cid") == cid), {})
            task_ref = meta.get("task_name")
        items.append(
            QueueItemResponse(
                cid=cid,
                plan_name=item.get("plan_name"),
                task_ref=task_ref,
                task_name=task_ref,
                trace_id=item.get("trace_id"),
                trace_label=item.get("trace_label"),
                status=_queue_status_from_state(state),
                queued_at=_to_ms(item.get("enqueued_at") or item.get("delay_until")),
                enqueued_at=_to_ms(item.get("enqueued_at")),
                source=item.get("source"),
            )
        )
    return QueueListResponse(items=items)


@router.post("/queue/reorder", response_model=GenericMessageResponse)
def reorder_queue(req: QueueReorderRequest) -> GenericMessageResponse:
    scheduler = _scheduler_running()
    result = scheduler.run_on_control_loop(scheduler.queue_reorder(req.cid_order), timeout=5.0)
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to reorder queue."))
    return GenericMessageResponse(status="success", message=result.get("message", "Queue reordered."))


@router.delete("/queue/clear", response_model=GenericMessageResponse)
def clear_queue() -> GenericMessageResponse:
    scheduler = _scheduler_running()
    result = scheduler.run_on_control_loop(scheduler.queue_clear(), timeout=5.0)
    return GenericMessageResponse(status="success", message=result.get("message", "Queue cleared."))


@router.delete("/queue/{cid}", response_model=GenericMessageResponse)
def remove_queue_item(cid: str) -> GenericMessageResponse:
    scheduler = _scheduler_running()
    result = scheduler.run_on_control_loop(scheduler.queue_remove_task(cid), timeout=5.0)
    if result.get("status") != "success":
        raise HTTPException(status_code=404, detail=result.get("message", f"Task '{cid}' not found."))
    return GenericMessageResponse(status="success", message=result.get("message", "Task removed."))


@router.post("/queue/{cid}/move-to-front", response_model=GenericMessageResponse)
def move_queue_item_to_front(cid: str) -> GenericMessageResponse:
    scheduler = _scheduler_running()
    result = scheduler.run_on_control_loop(scheduler.queue_move_to_front(cid), timeout=5.0)
    if result.get("status") != "success":
        raise HTTPException(status_code=404, detail=result.get("message", f"Task '{cid}' not found."))
    return GenericMessageResponse(status="success", message=result.get("message", "Task moved to front."))

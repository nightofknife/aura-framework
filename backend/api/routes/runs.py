# -*- coding: utf-8 -*-
"""Run history and detail routes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.api.dependencies import peek_core_scheduler
from backend.api.schemas import RunDetailResponse, RunHistoryResponse, RunSummary

router = APIRouter(tags=["runs"])


def _normalize_status(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in {"queued", "running", "success", "cancelled"}:
        return value
    if value == "starting":
        return "running"
    return "failed"


def _normalize_run_summary(run: Dict[str, Any]) -> RunSummary:
    started_at = run.get("started_at")
    finished_at = run.get("finished_at")
    if started_at is None:
        started_at = run.get("started_at_ms")
    if finished_at is None:
        finished_at = run.get("finished_at_ms")

    task_ref = run.get("task_ref") or run.get("task_name")
    error = run.get("error")
    final_result = run.get("final_result")
    if error is None and isinstance(final_result, dict):
        error = final_result.get("error")

    return RunSummary(
        cid=run.get("cid"),
        plan_name=run.get("plan_name"),
        task_ref=task_ref,
        task_name=task_ref,
        trace_id=run.get("trace_id"),
        trace_label=run.get("trace_label"),
        status=_normalize_status(run.get("status")),
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=run.get("duration_ms"),
        error=error,
    )


@router.get("/runs/active", response_model=List[RunSummary])
def list_active_runs() -> List[RunSummary]:
    scheduler = peek_core_scheduler()
    if scheduler is None:
        return []

    rows = []
    for run in scheduler.get_active_runs_snapshot():
        status = str(run.get("status") or "").lower()
        if status not in {"running", "starting"}:
            continue
        rows.append(_normalize_run_summary(run))
    return rows


@router.get("/runs/history", response_model=RunHistoryResponse)
def list_run_history(
    limit: int = Query(50, ge=1, le=500),
    plan_name: Optional[str] = Query(None),
    task_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
) -> RunHistoryResponse:
    scheduler = peek_core_scheduler()
    if scheduler is None:
        return RunHistoryResponse(runs=[])

    rows = scheduler.list_run_history(
        limit=limit,
        plan_name=plan_name,
        task_name=task_name,
        status=status,
    )
    return RunHistoryResponse(runs=[_normalize_run_summary(row) for row in rows])


@router.get("/runs/{cid}", response_model=RunDetailResponse)
def get_run_detail(cid: str) -> RunDetailResponse:
    scheduler = peek_core_scheduler()
    if scheduler is None:
        raise HTTPException(status_code=404, detail=f"Run '{cid}' not found.")

    run = scheduler.get_run_detail(cid)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{cid}' not found.")

    summary = _normalize_run_summary(run)
    final_result = run.get("final_result") or {}
    user_data = final_result.get("user_data") if isinstance(final_result, dict) else None
    framework_data = final_result.get("framework_data") if isinstance(final_result, dict) else None
    error = summary.error
    if error is None and isinstance(final_result, dict):
        error = final_result.get("error")

    return RunDetailResponse(
        cid=summary.cid,
        plan_name=summary.plan_name,
        task_ref=summary.task_ref,
        task_name=summary.task_name,
        trace_id=summary.trace_id,
        trace_label=summary.trace_label,
        status=summary.status,
        started_at=summary.started_at,
        finished_at=summary.finished_at,
        duration_ms=summary.duration_ms,
        error=error,
        user_data=user_data,
        framework_data=framework_data,
        nodes=run.get("nodes") or [],
    )


@router.get("/run/{cid}/detail")
def get_legacy_run_detail(cid: str):
    detail = get_run_detail(cid)
    payload = detail.model_dump()
    return {
        "run": payload,
        "timeline": payload.get("nodes", []),
        "logs": [],
    }

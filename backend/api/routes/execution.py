# -*- coding: utf-8 -*-
"""Task dispatch routes."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api.dependencies import CoreScheduler
from backend.api.schemas import BatchTaskStatusResponse, TaskRunResponse, TaskStatusItem
from packages.aura_core.scheduler import Scheduler

router = APIRouter(tags=["execution"])


class TaskDispatchRequest(BaseModel):
    plan_name: str
    task_ref: str
    inputs: Dict[str, Any] = Field(default_factory=dict)


class BatchTaskDispatchRequest(BaseModel):
    tasks: List[TaskDispatchRequest]


class BatchStatusRequest(BaseModel):
    cids: List[str]


@router.post("/tasks/dispatch", status_code=202, response_model=TaskRunResponse)
def dispatch_task(req: TaskDispatchRequest, scheduler: Scheduler = CoreScheduler) -> TaskRunResponse:
    result = scheduler.run_ad_hoc_task(req.plan_name, req.task_ref, req.inputs)
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to queue task."))

    return TaskRunResponse(
        status="queued",
        message=result.get("message", "Task queued."),
        cid=result.get("cid"),
        trace_id=result.get("trace_id"),
        trace_label=result.get("trace_label"),
    )


@router.post("/tasks/dispatch/batch", status_code=202)
def dispatch_batch_tasks(req: BatchTaskDispatchRequest, scheduler: Scheduler = CoreScheduler):
    tasks_input = [
        {"plan_name": task.plan_name, "task_name": task.task_ref, "inputs": task.inputs}
        for task in req.tasks
    ]
    result = scheduler.run_batch_ad_hoc_tasks(tasks_input)
    for row in result.get("results", []):
        row["task_ref"] = row.pop("task_name", None)
        if row.get("status") == "success":
            row["status"] = "queued"
    return result


@router.post("/tasks/status/batch", response_model=BatchTaskStatusResponse)
def get_batch_task_status(req: BatchStatusRequest, scheduler: Scheduler = CoreScheduler) -> BatchTaskStatusResponse:
    rows = []
    for item in scheduler.get_batch_task_status(req.cids):
        status = str(item.get("status") or "").lower()
        if status == "success":
            normalized = "success"
        elif status in {"queued", "running", "cancelled"}:
            normalized = status
        else:
            normalized = "failed"
        rows.append(
            TaskStatusItem(
                cid=item.get("cid"),
                status=normalized,
                plan_name=item.get("plan_name"),
                task_ref=item.get("task_name"),
                started_at=item.get("started_at"),
                finished_at=item.get("finished_at"),
            )
        )
    return BatchTaskStatusResponse(tasks=rows)

# backend/api/routes/execution.py

from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from packages.aura_core.scheduler import Scheduler
from ..dependencies import CoreScheduler
from ..schemas import TaskRunResponse


router = APIRouter()


class TaskDispatchRequest(BaseModel):
    plan_name: str
    task_ref: str
    inputs: Dict[str, Any] = Field(default_factory=dict)


class BatchTaskDispatchRequest(BaseModel):
    tasks: List[TaskDispatchRequest]


class BatchStatusRequest(BaseModel):
    cids: List[str]


@router.post("/tasks/dispatch", status_code=202, response_model=TaskRunResponse)
def dispatch_task(req: TaskDispatchRequest, scheduler: Scheduler = CoreScheduler) -> dict:
    result = scheduler.run_ad_hoc_task(req.plan_name, req.task_ref, req.inputs)
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to queue task."))

    return {
        "status": "queued",
        "message": result.get("message", "Task has been successfully queued."),
        "cid": result.get("cid"),
        "trace_id": result.get("trace_id"),
        "trace_label": result.get("trace_label"),
    }


@router.post("/tasks/dispatch/batch", status_code=202)
def dispatch_batch_tasks(req: BatchTaskDispatchRequest, scheduler: Scheduler = CoreScheduler):
    tasks_input = [
        {"plan_name": t.plan_name, "task_name": t.task_ref, "inputs": t.inputs}
        for t in req.tasks
    ]
    return scheduler.run_batch_ad_hoc_tasks(tasks_input)


@router.post("/tasks/dispatch/schedule/{item_id}", status_code=202, response_model=TaskRunResponse)
def dispatch_scheduled_task(item_id: str, scheduler: Scheduler = CoreScheduler) -> dict:
    result = scheduler.run_manual_task(item_id)
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to queue task."))

    return {
        "status": "queued",
        "message": f"Scheduled item '{item_id}' has been successfully queued.",
        "cid": result.get("cid"),
        "trace_id": result.get("trace_id"),
        "trace_label": result.get("trace_label"),
    }


@router.post("/tasks/status/batch")
def get_batch_task_status(req: BatchStatusRequest, scheduler: Scheduler = CoreScheduler):
    result = scheduler.get_batch_task_status(req.cids)
    return {"tasks": result}

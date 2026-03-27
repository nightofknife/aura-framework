# -*- coding: utf-8 -*-
"""Plan and task metadata routes."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, HTTPException, Query, Request

from backend.api.dependencies import CoreScheduler
from backend.api.schemas import GenericMessageResponse, PlanSummary, TaskLoadErrorResponse, TaskSummary
from packages.aura_core.scheduler import Scheduler

router = APIRouter(tags=["plans"])


def _plan_exists(scheduler: Scheduler, plan_name: str) -> bool:
    return plan_name in set(scheduler.get_all_plans())


@router.get("/plans", response_model=List[PlanSummary])
def list_plans(scheduler: Scheduler = CoreScheduler) -> List[PlanSummary]:
    tasks = scheduler.get_all_task_definitions_with_meta()
    errors = scheduler.get_task_load_errors()
    task_counts: Dict[str, int] = {}
    error_counts: Dict[str, int] = {}

    for item in tasks:
        plan_name = item.get("plan_name")
        if not plan_name:
            continue
        task_counts[plan_name] = task_counts.get(plan_name, 0) + 1

    for item in errors:
        plan_name = item.get("plan_name")
        if not plan_name:
            continue
        error_counts[plan_name] = error_counts.get(plan_name, 0) + 1

    return [
        PlanSummary(
            name=plan_name,
            task_count=task_counts.get(plan_name, 0),
            task_error_count=error_counts.get(plan_name, 0),
        )
        for plan_name in scheduler.get_all_plans()
    ]


@router.get("/plans/{plan_name}/tasks", response_model=List[TaskSummary])
def list_plan_tasks(plan_name: str, scheduler: Scheduler = CoreScheduler) -> List[TaskSummary]:
    if not _plan_exists(scheduler, plan_name):
        raise HTTPException(status_code=404, detail=f"Plan '{plan_name}' not found.")

    rows = []
    for task in scheduler.get_all_task_definitions_with_meta():
        if task.get("plan_name") != plan_name:
            continue
        rows.append(
            TaskSummary(
                full_task_id=task.get("full_task_id"),
                plan_name=task.get("plan_name"),
                task_name_in_plan=task.get("task_name_in_plan"),
                task_ref=task.get("task_ref"),
                meta=task.get("meta") or {},
                definition=task.get("definition"),
            )
        )
    return rows


@router.get("/plans/{plan_name}/task-load-errors", response_model=List[TaskLoadErrorResponse])
def list_plan_task_errors(plan_name: str, scheduler: Scheduler = CoreScheduler) -> List[TaskLoadErrorResponse]:
    if not _plan_exists(scheduler, plan_name):
        raise HTTPException(status_code=404, detail=f"Plan '{plan_name}' not found.")
    return [
        TaskLoadErrorResponse(**item)
        for item in scheduler.get_task_load_errors(plan_name=plan_name)
    ]


@router.get("/plans/{plan_name}/files/tree")
def get_plan_files_tree(plan_name: str, scheduler: Scheduler = CoreScheduler):
    try:
        return scheduler.get_plan_files(plan_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/plans/{plan_name}/files/content")
async def get_plan_file_content(
    plan_name: str,
    path: str = Query(..., min_length=1),
    scheduler: Scheduler = CoreScheduler,
):
    try:
        return await scheduler.get_file_content(plan_name, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/plans/{plan_name}/files/content", response_model=GenericMessageResponse)
async def save_plan_file_content(
    plan_name: str,
    request: Request,
    path: str = Query(..., min_length=1),
    scheduler: Scheduler = CoreScheduler,
):
    try:
        raw = await request.body()
        content = raw.decode("utf-8")
        await scheduler.save_file_content(plan_name, path, content)
        return GenericMessageResponse(status="success", message=f"Saved '{path}'.")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/plans/{plan_name}/files/reload", response_model=GenericMessageResponse)
async def reload_plan_file(
    plan_name: str,
    path: str = Query(..., min_length=1),
    scheduler: Scheduler = CoreScheduler,
):
    orchestrator = scheduler.plan_manager.get_plan(plan_name)
    if orchestrator is None:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_name}' not found.")

    file_path = (scheduler.base_path / "plans" / plan_name / path).resolve()
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{path}' not found in plan '{plan_name}'.")

    try:
        if (scheduler.get_master_status() or {}).get("is_running"):
            await scheduler.reload_task_file(file_path)
        else:
            scheduler.reload_plans()
        return GenericMessageResponse(status="success", message=f"Reloaded '{path}'.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/plans/{plan_name}", response_model=GenericMessageResponse)
def delete_plan(plan_name: str, scheduler: Scheduler = CoreScheduler):
    result = scheduler.delete_plan(plan_name)
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to delete plan."))
    return GenericMessageResponse(status="success", message=result.get("message", "Plan deleted."))

# -*- coding: utf-8 -*-
"""Runtime operations routes."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.dependencies import CoreScheduler
from packages.aura_core.scheduler import Scheduler

router = APIRouter(tags=["runtime"])


class ReloadRequest(BaseModel):
    package_id: Optional[str] = None
    drain: bool = False
    timeout_sec: float = 30.0


@router.get("/runtime/reload/status")
def get_reload_status(scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return scheduler.get_reload_status()


@router.post("/runtime/reload/plan")
def plan_reload(req: ReloadRequest, scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return scheduler.plan_runtime_reload(package_id=req.package_id)


@router.post("/runtime/reload/apply")
async def apply_reload(req: ReloadRequest, scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    if scheduler._loop and scheduler._loop.is_running():
        result = scheduler.run_on_control_loop(
            scheduler.apply_runtime_reload(
                package_id=req.package_id,
                drain=req.drain,
                timeout_sec=req.timeout_sec,
            ),
            timeout=max(5.0, req.timeout_sec + 5.0),
        )
    else:
        result = await scheduler.apply_runtime_reload(
            package_id=req.package_id,
            drain=req.drain,
            timeout_sec=req.timeout_sec,
        )
    if result.get("status") not in {"success", "idle"}:
        raise HTTPException(status_code=409, detail=result)
    return result

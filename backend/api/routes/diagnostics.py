# -*- coding: utf-8 -*-
"""Diagnostics bundle routes."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from backend.api.dependencies import CoreScheduler
from packages.aura_core.diagnostics import DiagnosticsCollector
from packages.aura_core.scheduler import Scheduler

router = APIRouter(tags=["diagnostics"])


@router.get("/diagnostics/recent")
def list_recent_diagnostics(scheduler: Scheduler = CoreScheduler) -> List[Dict[str, Any]]:
    return DiagnosticsCollector(scheduler.base_path).recent()


@router.get("/diagnostics/{bundle_id}")
def get_diagnostic_bundle(bundle_id: str, scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    result = DiagnosticsCollector(scheduler.base_path).get(bundle_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Diagnostic bundle '{bundle_id}' not found.")
    return result


@router.post("/diagnostics/collect")
def collect_diagnostics(scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return DiagnosticsCollector(scheduler.base_path).collect()

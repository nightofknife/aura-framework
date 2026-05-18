# -*- coding: utf-8 -*-
"""Read-only observability query routes."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from backend.api.dependencies import CoreScheduler
from packages.aura_core.observability.query import ObservabilityQueryService
from packages.aura_core.scheduler import Scheduler

router = APIRouter(tags=["observability"])


def _service(scheduler: Scheduler) -> ObservabilityQueryService:
    return ObservabilityQueryService(scheduler.base_path)


@router.get("/observability/traces")
def list_traces(
    limit: int = Query(50, ge=1, le=500),
    scheduler: Scheduler = CoreScheduler,
) -> Dict[str, Any]:
    return _service(scheduler).list_traces(limit=limit)


@router.get("/observability/traces/{trace_id}")
def get_trace(trace_id: str, scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    payload = _service(scheduler).get_trace(trace_id)
    if payload.get("run") is None:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found.")
    return payload


@router.get("/observability/errors/summary")
def get_error_summary(scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return _service(scheduler).error_summary()


@router.get("/observability/metrics/actions")
def get_action_metrics(scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return _service(scheduler).action_metrics()


@router.get("/observability/metrics/backends")
def get_backend_metrics(scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return _service(scheduler).backend_metrics()


@router.get("/observability/metrics/services")
def get_service_metrics(scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return _service(scheduler).service_metrics()


@router.get("/observability/metrics/desktop")
def get_desktop_metrics(scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return _service(scheduler).desktop_metrics()


@router.get("/observability/resources")
def get_resource_samples(
    limit: int = Query(200, ge=1, le=1000),
    scheduler: Scheduler = CoreScheduler,
) -> Dict[str, Any]:
    return _service(scheduler).resources(limit=limit)


@router.get("/observability/errors/{category}")
def get_errors_by_category(category: str, scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return _service(scheduler).errors_by_category(category)


@router.get("/observability/queue/analysis")
def get_queue_analysis(scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return _service(scheduler).queue_analysis()

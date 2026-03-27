# -*- coding: utf-8 -*-
"""System status and health routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from backend.api.dependencies import get_core_scheduler, peek_core_scheduler, reset_core_scheduler
from backend.api.schemas import GenericMessageResponse, HealthResponse, SystemStatusResponse
from packages.aura_core.config.loader import get_config_value

router = APIRouter(tags=["system"])


def _build_status_payload() -> dict:
    scheduler = peek_core_scheduler()
    scheduler_initialized = scheduler is not None
    scheduler_running = False
    if scheduler is not None:
        scheduler_running = bool((scheduler.get_master_status() or {}).get("is_running"))
    return {
        "status": "ok",
        "is_running": scheduler_running,
        "scheduler_initialized": scheduler_initialized,
        "scheduler_running": scheduler_running,
        "ready": scheduler_running,
    }


@router.get("/system/status", response_model=SystemStatusResponse)
def get_system_status() -> SystemStatusResponse:
    return SystemStatusResponse(**_build_status_payload())


@router.get("/system/health", response_model=HealthResponse)
def get_system_health() -> HealthResponse:
    return HealthResponse(**_build_status_payload())


@router.get("/system/ready", response_model=HealthResponse)
def get_system_ready() -> HealthResponse:
    return HealthResponse(**_build_status_payload())


@router.get("/system/metrics")
def get_system_metrics():
    scheduler = peek_core_scheduler()
    if scheduler is None:
        return {}
    return scheduler.get_metrics_snapshot()


@router.post("/system/start", response_model=GenericMessageResponse)
def start_system() -> GenericMessageResponse:
    scheduler = get_core_scheduler()
    if (scheduler.get_master_status() or {}).get("is_running"):
        return GenericMessageResponse(status="success", message="Scheduler is already running.")
    scheduler.start_scheduler()
    return GenericMessageResponse(status="success", message="Scheduler started.")


@router.post("/system/stop", response_model=GenericMessageResponse)
def stop_system() -> GenericMessageResponse:
    scheduler = peek_core_scheduler()
    if scheduler is None:
        return GenericMessageResponse(status="success", message="Scheduler is already stopped.")
    if (scheduler.get_master_status() or {}).get("is_running"):
        scheduler.stop_scheduler()
    reset_core_scheduler()
    return GenericMessageResponse(status="success", message="Scheduler stopped.")


@router.get("/system/hot_reload/status")
def get_hot_reload_status():
    scheduler = peek_core_scheduler()
    enabled = False
    if scheduler is not None:
        enabled = bool(scheduler.is_hot_reload_enabled())
    return {"enabled": enabled}


@router.post("/system/hot_reload/enable", response_model=GenericMessageResponse)
def enable_hot_reload() -> GenericMessageResponse:
    scheduler = get_core_scheduler()
    if not (scheduler.get_master_status() or {}).get("is_running"):
        return GenericMessageResponse(status="error", message="Scheduler is not running.")
    scheduler.enable_hot_reload()
    return GenericMessageResponse(status="success", message="Hot reload enabled.")


@router.post("/system/hot_reload/disable", response_model=GenericMessageResponse)
def disable_hot_reload() -> GenericMessageResponse:
    scheduler = get_core_scheduler()
    if not (scheduler.get_master_status() or {}).get("is_running"):
        return GenericMessageResponse(status="error", message="Scheduler is not running.")
    scheduler.disable_hot_reload()
    return GenericMessageResponse(status="success", message="Hot reload disabled.")


@router.get("/system/logs")
def get_system_logs(limit: int = 200, level: str | None = None, keyword: str | None = None):
    scheduler = peek_core_scheduler()
    if scheduler is not None:
        base_path = scheduler.base_path
    else:
        base_path = Path.cwd()
    log_dir = base_path / str(get_config_value("logging.log_dir", "logs"))
    if not log_dir.exists():
        return {"lines": []}

    lines = []
    normalized_keyword = (keyword or "").strip().lower()
    normalized_level = (level or "").strip().lower()
    log_files = sorted(log_dir.glob("*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
    for log_file in log_files:
        try:
            file_lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in reversed(file_lines):
            lowered = line.lower()
            if normalized_level and normalized_level not in lowered:
                continue
            if normalized_keyword and normalized_keyword not in lowered:
                continue
            lines.append(line)
            if len(lines) >= max(1, int(limit)):
                return {"lines": list(reversed(lines))}
    return {"lines": list(reversed(lines))}

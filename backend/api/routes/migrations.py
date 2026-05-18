# -*- coding: utf-8 -*-
"""SQLite schema migration routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter

from backend.api.dependencies import CoreScheduler
from packages.aura_core.scheduler import Scheduler

router = APIRouter(tags=["migrations"])


def _legacy_path(scheduler: Scheduler) -> Path:
    return scheduler.base_path / "logs" / "runs" / "run_store.sqlite3"


@router.get("/migrations/status")
def get_migration_status(scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return scheduler.observability.run_store.migration_status(legacy_db_path=_legacy_path(scheduler))


@router.post("/migrations/plan")
def plan_migrations(scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return scheduler.observability.run_store.migration_plan(legacy_db_path=_legacy_path(scheduler))


@router.post("/migrations/apply")
def apply_migrations(scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return scheduler.observability.run_store.apply_migrations(legacy_db_path=_legacy_path(scheduler))

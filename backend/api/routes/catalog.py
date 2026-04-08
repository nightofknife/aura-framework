# -*- coding: utf-8 -*-
"""Catalog routes for actions, services and packages."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from backend.api.dependencies import CoreScheduler
from backend.api.schemas import ActionSummary, PackageSummary
from packages.aura_core.api import ACTION_REGISTRY
from packages.aura_core.scheduler import Scheduler

router = APIRouter(tags=["catalog"])


@router.get("/actions", response_model=List[ActionSummary])
def list_actions() -> List[ActionSummary]:
    actions = []
    for definition in ACTION_REGISTRY.get_all_action_definitions():
        actions.append(
            ActionSummary(
                fqid=definition.fqid,
                name=definition.name,
                public=definition.public,
                read_only=definition.read_only,
                description=definition.description or "",
            )
        )
    return actions


@router.get("/services")
def list_services(scheduler: Scheduler = CoreScheduler) -> List[Dict[str, Any]]:
    return scheduler.get_all_services_for_api()


@router.get("/packages", response_model=List[PackageSummary])
def list_packages(scheduler: Scheduler = CoreScheduler) -> List[PackageSummary]:
    results: List[PackageSummary] = []
    package_manager = scheduler.plan_manager.package_manager
    for package_id, manifest in package_manager.loaded_packages.items():
        results.append(
            PackageSummary(
                canonical_id=package_id,
                name=getattr(manifest.package, "name", package_id),
                version=getattr(manifest.package, "version", "0.0.0"),
                path=str(getattr(manifest, "path", "")),
            )
        )
    return results

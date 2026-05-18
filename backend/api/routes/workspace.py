# -*- coding: utf-8 -*-
"""Workspace profile and package lifecycle routes."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.dependencies import CoreScheduler
from packages.aura_core.api import ACTION_REGISTRY, service_registry
from packages.aura_core.packaging.core.workspace_lifecycle import WorkspaceLifecycleService
from packages.aura_core.packaging.core.workspace_lifecycle import normalize_package_id
from packages.aura_core.scheduler import Scheduler
from packages.aura_core.utils.safe_paths import UnsafePathError

router = APIRouter(tags=["workspace"])


class PackageReloadRequest(BaseModel):
    drain: bool = False
    timeout_sec: float = 30.0


class PackageUpgradeRequest(BaseModel):
    source: str
    dry_run: bool = True
    apply: bool = False


@router.get("/workspace")
def get_workspace(scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    service = WorkspaceLifecycleService(scheduler.base_path)
    return {
        "workspace": service.load_workspace(),
        "lock": service.load_lock(),
        "doctor": service.doctor(),
    }


@router.get("/workspace/packages")
def list_workspace_packages(scheduler: Scheduler = CoreScheduler) -> List[Dict[str, Any]]:
    return WorkspaceLifecycleService(scheduler.base_path).list_packages()


@router.post("/workspace/packages/lock")
def lock_workspace_packages(scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return WorkspaceLifecycleService(scheduler.base_path).write_lock()


@router.post("/workspace/packages/validate")
def validate_workspace_packages(scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return WorkspaceLifecycleService(scheduler.base_path).validate_package()


@router.get("/workspace/packages/{package_id:path}/permissions")
def get_workspace_package_permissions(package_id: str, scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    _ = scheduler
    normalized = normalize_package_id(package_id)
    actions = []
    for action in ACTION_REGISTRY.get_all_action_definitions():
        action_package = _optional_package_id(getattr(getattr(action.plugin, "package", None), "canonical_id", ""))
        if action_package == normalized:
            actions.append(
                {
                    "fqid": action.fqid,
                    "name": action.name,
                    "capabilities": list(getattr(action, "capabilities", []) or []),
                    "capabilities_declared": bool(getattr(action, "capabilities_declared", False)),
                    "side_effect_level": getattr(action, "side_effect_level", "read"),
                    "requires_foreground": bool(getattr(action, "requires_foreground", False)),
                    "requires_admin": bool(getattr(action, "requires_admin", False)),
                    "stability": getattr(action, "stability", "stable"),
                }
            )
    services = []
    for service in service_registry.get_all_service_definitions():
        service_package = _optional_package_id(getattr(getattr(service.plugin, "package", None), "canonical_id", ""))
        if service_package == normalized:
            services.append(
                {
                    "fqid": service.fqid,
                    "alias": service.alias,
                    "capabilities": list(getattr(service, "capabilities", []) or []),
                    "capabilities_declared": bool(getattr(service, "capabilities_declared", False)),
                    "side_effect_level": getattr(service, "side_effect_level", "read"),
                    "requires_foreground": bool(getattr(service, "requires_foreground", False)),
                    "requires_admin": bool(getattr(service, "requires_admin", False)),
                    "stability": getattr(service, "stability", "stable"),
                }
            )
    return {"package_id": normalized, "actions": actions, "services": services}


@router.get("/workspace/packages/{package_id:path}/migrations")
def get_workspace_package_migrations(package_id: str, scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    return WorkspaceLifecycleService(scheduler.base_path).package_migrations(package_id)


@router.post("/workspace/packages/{package_id:path}/upgrade-plan")
def plan_workspace_package_upgrade(
    package_id: str,
    req: PackageUpgradeRequest,
    scheduler: Scheduler = CoreScheduler,
) -> Dict[str, Any]:
    return WorkspaceLifecycleService(scheduler.base_path).upgrade_package(
        package_id,
        req.source,
        dry_run=True,
        apply=False,
    )


@router.post("/workspace/packages/{package_id:path}/upgrade")
def upgrade_workspace_package(
    package_id: str,
    req: PackageUpgradeRequest,
    scheduler: Scheduler = CoreScheduler,
) -> Dict[str, Any]:
    result = WorkspaceLifecycleService(scheduler.base_path).upgrade_package(
        package_id,
        req.source,
        dry_run=bool(req.dry_run or not req.apply),
        apply=bool(req.apply),
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/workspace/packages/{package_id:path}/rollback")
def rollback_workspace_package(package_id: str, scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    result = WorkspaceLifecycleService(scheduler.base_path).rollback_package(package_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/workspace/packages/{package_id:path}/reload")
def reload_workspace_package(
    package_id: str,
    req: PackageReloadRequest,
    scheduler: Scheduler = CoreScheduler,
) -> Dict[str, Any]:
    normalized = normalize_package_id(package_id)
    if scheduler._loop and scheduler._loop.is_running():
        result = scheduler.run_on_control_loop(
            scheduler.apply_runtime_reload(
                package_id=normalized,
                mode="package",
                drain=req.drain,
                timeout_sec=req.timeout_sec,
            ),
            timeout=max(5.0, req.timeout_sec + 5.0),
        )
    else:
        raise HTTPException(status_code=409, detail="Scheduler control loop is not running.")
    if result.get("status") != "success":
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/workspace/packages/{package_id:path}/enable")
def enable_workspace_package(package_id: str, scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    result = WorkspaceLifecycleService(scheduler.base_path).enable_package(package_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@router.post("/workspace/packages/{package_id:path}/disable")
def disable_workspace_package(package_id: str, scheduler: Scheduler = CoreScheduler) -> Dict[str, Any]:
    result = WorkspaceLifecycleService(scheduler.base_path).disable_package(package_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


def _optional_package_id(raw: Any) -> str:
    try:
        return normalize_package_id(raw)
    except UnsafePathError:
        return ""

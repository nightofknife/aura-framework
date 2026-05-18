# -*- coding: utf-8 -*-
"""Catalog routes for actions, services and packages."""

from __future__ import annotations

import inspect
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
                parameters=_extract_parameters(definition),
                return_schema={"type": "object"},
                supported_backend_domains=_infer_backend_domains(definition.name),
                side_effect_level=getattr(definition, "side_effect_level", "read" if definition.read_only else "input"),
                stability=getattr(definition, "stability", _infer_stability(definition.name)),
                capabilities=list(getattr(definition, "capabilities", []) or []),
                requires_foreground=bool(getattr(definition, "requires_foreground", False)),
                requires_admin=bool(getattr(definition, "requires_admin", False)),
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


def _extract_parameters(definition: Any) -> List[Dict[str, Any]]:
    service_deps = getattr(definition, "service_deps", {}) or {}
    parameters: List[Dict[str, Any]] = []
    try:
        signature = inspect.signature(definition.func)
    except Exception:
        return parameters
    for name, param in signature.parameters.items():
        if name in service_deps or name in {"context", "engine"}:
            continue
        annotation = param.annotation
        parameters.append(
            {
                "name": name,
                "type": "Any" if annotation is inspect.Parameter.empty else getattr(annotation, "__name__", str(annotation)),
                "required": param.default is inspect.Parameter.empty,
                "default": None if param.default is inspect.Parameter.empty else param.default,
            }
        )
    return parameters


def _infer_backend_domains(action_name: str) -> List[str]:
    capture_tokens = {"find_image", "image", "template", "pixel", "yolo"}
    mouse_tokens = {"click", "drag", "mouse", "scroll"}
    keyboard_tokens = {"key", "hotkey", "type_text"}
    ocr_tokens = {"text", "ocr"}
    domains: List[str] = []
    lowered = action_name.lower()
    if any(token in lowered for token in capture_tokens):
        domains.append("capture")
    if any(token in lowered for token in mouse_tokens):
        domains.append("mouse")
    if any(token in lowered for token in keyboard_tokens):
        domains.append("keyboard")
    if any(token in lowered for token in ocr_tokens):
        domains.append("ocr")
    if "window" in lowered:
        domains.append("window")
    return domains


def _infer_stability(action_name: str) -> str:
    if action_name.startswith("yolo_"):
        return "experimental"
    if action_name in {"mouse_down", "mouse_up", "key_down", "key_up"}:
        return "stable"
    return "stable"

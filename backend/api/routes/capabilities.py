# -*- coding: utf-8 -*-
"""Desktop capability catalog routes."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from backend.api.schemas import CapabilityBackendSummary, CapabilityListResponse
router = APIRouter(tags=["capabilities"])


@router.get("/capabilities", response_model=CapabilityListResponse)
def list_capabilities() -> CapabilityListResponse:
    registry = get_desktop_registry()
    return CapabilityListResponse(domains=_coerce_capabilities(registry.list()))


@router.get("/capabilities/{domain}", response_model=List[CapabilityBackendSummary])
def list_domain_capabilities(domain: str) -> List[CapabilityBackendSummary]:
    registry = get_desktop_registry()
    rows = registry.list(domain).get(domain, [])
    if not rows:
        raise HTTPException(status_code=404, detail=f"Capability domain '{domain}' not found.")
    return [CapabilityBackendSummary(**row) for row in rows]


@router.post("/capabilities/self-check")
def self_check_capabilities() -> Dict[str, Any]:
    return get_desktop_registry().self_check()


def _coerce_capabilities(raw: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[CapabilityBackendSummary]]:
    return {
        domain: [CapabilityBackendSummary(**item) for item in items]
        for domain, items in raw.items()
    }


def get_desktop_registry():
    from plans.aura_base.src.desktop_runtime import get_desktop_registry as _get_desktop_registry

    return _get_desktop_registry()

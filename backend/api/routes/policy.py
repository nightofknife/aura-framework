# -*- coding: utf-8 -*-
"""Runtime policy routes."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from packages.aura_core.api import ACTION_REGISTRY, service_registry
from packages.aura_core.policy import CAPABILITY_TAXONOMY, POLICY_PROFILES, get_active_policy_profile

router = APIRouter(tags=["policy"])


@router.get("/policy")
def get_policy() -> Dict[str, Any]:
    profile = get_active_policy_profile()
    return {
        "profile": profile,
        "capabilities": CAPABILITY_TAXONOMY,
        "profiles": {
            name: {
                "allow": sorted(rules["allow"]),
                "deny": sorted(rules["deny"]),
            }
            for name, rules in POLICY_PROFILES.items()
        },
    }


@router.get("/policy/effective")
def get_effective_policy() -> Dict[str, Any]:
    profile = get_active_policy_profile()
    rules = POLICY_PROFILES[profile]
    return {
        "profile": profile,
        "allow": sorted(rules["allow"]),
        "deny": sorted(rules["deny"]),
        "actions": [
            {
                "fqid": action.fqid,
                "capabilities": list(getattr(action, "capabilities", []) or []),
                "side_effect_level": getattr(action, "side_effect_level", "read"),
                "stability": getattr(action, "stability", "stable"),
                "capabilities_declared": bool(getattr(action, "capabilities_declared", False)),
            }
            for action in ACTION_REGISTRY.get_all_action_definitions()
        ],
        "services": [
            {
                "fqid": service.fqid,
                "alias": service.alias,
                "capabilities": list(getattr(service, "capabilities", []) or []),
                "side_effect_level": getattr(service, "side_effect_level", "read"),
                "stability": getattr(service, "stability", "stable"),
                "capabilities_declared": bool(getattr(service, "capabilities_declared", False)),
            }
            for service in service_registry.get_all_service_definitions()
        ],
    }

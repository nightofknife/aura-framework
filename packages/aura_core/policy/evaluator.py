# -*- coding: utf-8 -*-
"""Capability policy evaluation for action/service execution."""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from typing import Any, Iterable


CAPABILITY_TAXONOMY = [
    "desktop.capture.read",
    "desktop.window.read",
    "desktop.window.focus",
    "desktop.mouse.input",
    "desktop.keyboard.input",
    "desktop.raw_input.monitor",
    "desktop.hid.input",
    "desktop.ocr.read",
    "process.read",
    "process.control",
    "filesystem.read",
    "filesystem.write",
    "network.local",
    "network.remote",
]

_READ_CAPABILITIES = {
    "desktop.capture.read",
    "desktop.window.read",
    "desktop.ocr.read",
    "process.read",
    "filesystem.read",
    "network.local",
}

POLICY_PROFILES: dict[str, dict[str, Any]] = {
    "safe": {
        "allow": {
            "desktop.capture.read",
            "desktop.window.read",
            "desktop.ocr.read",
            "process.read",
            "filesystem.read",
            "network.local",
        },
        "deny": {
            "desktop.mouse.input",
            "desktop.keyboard.input",
            "desktop.raw_input.monitor",
            "desktop.hid.input",
            "process.control",
            "filesystem.write",
            "network.remote",
        },
    },
    "default": {
        "allow": {
            "desktop.capture.read",
            "desktop.window.read",
            "desktop.window.focus",
            "desktop.mouse.input",
            "desktop.keyboard.input",
            "desktop.raw_input.monitor",
            "desktop.ocr.read",
            "process.read",
            "filesystem.read",
            "filesystem.write",
            "network.local",
        },
        "deny": {
            "desktop.hid.input",
            "process.control",
            "network.remote",
        },
    },
    "trusted": {
        "allow": set(CAPABILITY_TAXONOMY),
        "deny": set(),
    },
    "dev": {
        "allow": set(CAPABILITY_TAXONOMY),
        "deny": set(),
    },
}


@dataclass(slots=True)
class PolicyDecision:
    profile: str
    decision: str
    reason: str = ""
    action: str | None = None
    package_id: str | None = None
    capabilities: list[str] = field(default_factory=list)
    side_effect_level: str = "read"
    timestamp_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data["timestamp_ms"]:
            data["timestamp_ms"] = int(time.time() * 1000)
        return data


class PolicyDeniedError(PermissionError):
    """Raised when runtime policy denies an action call."""

    def __init__(self, decision: PolicyDecision) -> None:
        self.decision = decision
        super().__init__(
            f"Policy denied action '{decision.action}' under profile '{decision.profile}': {decision.reason}"
        )


def get_active_policy_profile() -> str:
    env_value = os.environ.get("AURA_POLICY_PROFILE")
    if env_value:
        return _normalize_profile(env_value)
    try:
        from packages.aura_core.config.loader import get_config_value

        return _normalize_profile(get_config_value("policy.profile", "default"))
    except Exception:
        return "default"


def evaluate_action_policy(
    *,
    action_def: Any,
    rendered_params: dict[str, Any] | None = None,
    extra_capabilities: Iterable[str] | None = None,
    extra_requires_admin: bool = False,
    profile: str | None = None,
) -> PolicyDecision:
    selected_profile = _normalize_profile(profile or get_active_policy_profile())
    capabilities = list(getattr(action_def, "capabilities", None) or [])
    capabilities.extend(str(cap) for cap in (extra_capabilities or []) if cap)
    if rendered_params:
        capabilities = _augment_capabilities_for_params(capabilities, rendered_params)
    if not capabilities:
        capabilities = infer_action_capabilities(
            getattr(action_def, "name", ""),
            read_only=bool(getattr(action_def, "read_only", False)),
        )

    side_effect = getattr(action_def, "side_effect_level", None)
    if not side_effect:
        side_effect = "read" if getattr(action_def, "read_only", False) else "input"
    requires_admin = bool(getattr(action_def, "requires_admin", False) or extra_requires_admin)
    if requires_admin and not _admin_execution_enabled():
        return _decision(
            action_def=action_def,
            profile=selected_profile,
            decision="deny",
            reason="Execution requires admin policy enablement.",
            capabilities=sorted(set(capabilities)),
            side_effect_level=side_effect,
        )

    profile_rules = POLICY_PROFILES[selected_profile]
    deny_set = set(profile_rules["deny"])
    allow_set = set(profile_rules["allow"])
    cap_set = set(capabilities)
    denied = sorted(cap_set & deny_set)
    if denied:
        return _decision(
            action_def=action_def,
            profile=selected_profile,
            decision="deny",
            reason=f"Capability not allowed: {', '.join(denied)}",
            capabilities=sorted(set(capabilities)),
            side_effect_level=side_effect,
        )

    unknown = sorted(cap for cap in cap_set if cap not in CAPABILITY_TAXONOMY)
    if unknown and selected_profile != "dev":
        return _decision(
            action_def=action_def,
            profile=selected_profile,
            decision="deny",
            reason=f"Unknown capability: {', '.join(unknown)}",
            capabilities=sorted(set(capabilities)),
            side_effect_level=side_effect,
        )

    not_allowed = sorted(cap for cap in cap_set if cap not in allow_set and selected_profile != "dev")
    if not_allowed:
        return _decision(
            action_def=action_def,
            profile=selected_profile,
            decision="deny",
            reason=f"Capability outside profile allowlist: {', '.join(not_allowed)}",
            capabilities=sorted(set(capabilities)),
            side_effect_level=side_effect,
        )

    return _decision(
        action_def=action_def,
        profile=selected_profile,
        decision="allow",
        reason="",
        capabilities=sorted(set(capabilities)),
        side_effect_level=side_effect,
    )


def evaluate_capability_policy(
    *,
    subject: str,
    capabilities: Iterable[str],
    package_id: str | None = None,
    side_effect_level: str = "read",
    requires_admin: bool = False,
    profile: str | None = None,
) -> PolicyDecision:
    """Evaluate policy for a non-action runtime subject such as a selected backend."""

    plugin = SimpleNamespace(package=SimpleNamespace(canonical_id=package_id or "runtime/backend"))
    action_def = SimpleNamespace(
        name=subject,
        fqid=subject,
        plugin=plugin,
        read_only=side_effect_level in {"none", "read"},
        capabilities=list(capabilities),
        side_effect_level=side_effect_level,
        requires_admin=requires_admin,
    )
    return evaluate_action_policy(action_def=action_def, profile=profile)


def infer_action_capabilities(action_name: str, *, read_only: bool = False) -> list[str]:
    name = str(action_name or "").lower()
    caps: set[str] = set()
    if any(token in name for token in ["image", "template", "pixel", "screenshot", "capture", "yolo"]):
        caps.add("desktop.capture.read")
    if any(token in name for token in ["ocr", "text"]):
        caps.add("desktop.ocr.read")
    if any(token in name for token in ["window", "focus"]):
        caps.add("desktop.window.focus" if "focus" in name else "desktop.window.read")
    if any(token in name for token in ["click", "drag", "mouse", "scroll", "move_to"]):
        caps.add("desktop.mouse.input")
    if any(token in name for token in ["key", "hotkey", "type_text"]):
        caps.add("desktop.keyboard.input")
    if name.startswith("file_read"):
        caps.add("filesystem.read")
    if name.startswith("file_write"):
        caps.add("filesystem.write")
    if any(token in name for token in ["process", "start_process", "stop_process"]):
        caps.add("process.control" if any(token in name for token in ["start", "stop"]) else "process.read")
    if not caps:
        caps.add("filesystem.read" if read_only else "network.local")
    return sorted(caps)


def infer_service_capabilities(alias: str) -> list[str]:
    name = str(alias or "").lower()
    caps: set[str] = set()
    if any(token in name for token in ["screen", "capture", "vision"]):
        caps.add("desktop.capture.read")
    if "ocr" in name:
        caps.add("desktop.ocr.read")
    if any(token in name for token in ["controller", "mouse"]):
        caps.update({"desktop.mouse.input", "desktop.keyboard.input"})
    if "keyboard" in name:
        caps.add("desktop.keyboard.input")
    if any(token in name for token in ["window", "app", "navigation"]):
        caps.add("desktop.window.focus")
    if "process" in name:
        caps.add("process.control")
    if "state" in name:
        caps.add("filesystem.write")
    if not caps:
        caps.add("filesystem.read")
    return sorted(caps)


def _decision(
    *,
    action_def: Any,
    profile: str,
    decision: str,
    reason: str,
    capabilities: Iterable[str],
    side_effect_level: str,
) -> PolicyDecision:
    plugin = getattr(action_def, "plugin", None)
    package = getattr(plugin, "package", None)
    package_id = getattr(package, "canonical_id", None)
    return PolicyDecision(
        profile=profile,
        decision=decision,
        reason=reason,
        action=getattr(action_def, "fqid", getattr(action_def, "name", None)),
        package_id=str(package_id).lstrip("@") if package_id else None,
        capabilities=list(capabilities),
        side_effect_level=str(side_effect_level or "read"),
        timestamp_ms=int(time.time() * 1000),
    )


def _normalize_profile(value: Any) -> str:
    profile = str(value or "default").strip().lower()
    return profile if profile in POLICY_PROFILES else "default"


def _augment_capabilities_for_params(capabilities: list[str], params: dict[str, Any]) -> list[str]:
    result = set(capabilities)
    backend = params.get("backend")
    if isinstance(backend, dict):
        values = [backend.get("prefer"), *(backend.get("fallback") or [])]
    else:
        values = [backend]
    lowered = {str(value).lower() for value in values if value}
    if "hid_mouse" in lowered:
        result.add("desktop.hid.input")
    if "raw_input" in lowered:
        result.add("desktop.raw_input.monitor")
    return sorted(result)


def _admin_execution_enabled() -> bool:
    env_value = os.environ.get("AURA_POLICY_ADMIN_ENABLED")
    if env_value is not None:
        return env_value.strip().lower() in {"1", "true", "yes", "on"}
    try:
        from packages.aura_core.config.loader import get_config_bool

        return bool(get_config_bool("policy.admin.enabled", False))
    except Exception:
        return False

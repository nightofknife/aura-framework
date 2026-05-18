# -*- coding: utf-8 -*-
"""Runtime context objects exposed to package authors."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class EvidenceWriter:
    """Per-action evidence reference buffer."""

    cid: str | None = None
    node_id: str | None = None
    _refs: List[Dict[str, Any]] = field(default_factory=list)

    def add_ref(
        self,
        *,
        kind: str,
        path: str | None = None,
        payload: Dict[str, Any] | None = None,
        label: str | None = None,
    ) -> Dict[str, Any]:
        ref = {
            "id": f"ev-{uuid.uuid4().hex[:12]}",
            "kind": kind,
            "path": path,
            "label": label,
            "cid": self.cid,
            "node_id": self.node_id,
            "payload": payload or {},
            "created_at_ms": int(time.time() * 1000),
        }
        self._refs.append(ref)
        return ref

    def refs(self) -> List[Dict[str, Any]]:
        return list(self._refs)


@dataclass(frozen=True, slots=True)
class PolicyContext:
    profile: str
    decision: str
    reason: str = ""
    capabilities: tuple[str, ...] = ()
    action: str | None = None
    package_id: str | None = None

    @classmethod
    def from_decision(cls, decision: Dict[str, Any]) -> "PolicyContext":
        return cls(
            profile=str(decision.get("profile") or ""),
            decision=str(decision.get("decision") or ""),
            reason=str(decision.get("reason") or ""),
            capabilities=tuple(decision.get("capabilities") or decision.get("capabilities_used") or ()),
            action=decision.get("action"),
            package_id=decision.get("package_id"),
        )


@dataclass(slots=True)
class ActionContext:
    cid: str | None
    node_id: str | None
    inputs: Dict[str, Any]
    loop: Dict[str, Any]
    package_id: str | None
    plan_name: str | None
    plan_path: str | None
    initial: Dict[str, Any]
    action_fqid: str
    policy: PolicyContext
    evidence: EvidenceWriter


class ActionResultBuilder:
    """Small helper for action authors that want consistent result payloads."""

    def __init__(self, *, ok: bool = True) -> None:
        self._payload: Dict[str, Any] = {"ok": bool(ok)}

    def data(self, value: Any) -> "ActionResultBuilder":
        self._payload["data"] = value
        return self

    def message(self, value: str) -> "ActionResultBuilder":
        self._payload["message"] = value
        return self

    def error(self, code: str, message: str) -> "ActionResultBuilder":
        self._payload.update({"ok": False, "error_code": code, "message": message})
        return self

    def evidence(self, refs: List[Dict[str, Any]]) -> "ActionResultBuilder":
        self._payload["evidence"] = list(refs)
        return self

    def build(self) -> Dict[str, Any]:
        return dict(self._payload)

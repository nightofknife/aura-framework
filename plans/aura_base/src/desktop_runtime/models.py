"""Shared desktop runtime models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class BackendDescriptor:
    backend_id: str
    domain: str
    available: bool
    health_status: str
    requires_foreground: bool
    supports_background: bool
    supports_minimized: bool
    requires_admin: bool
    side_effect_level: str
    capabilities: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    last_error: str | None = None
    stability: str = "stable"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BackendSelection:
    domain: str
    profile: str
    requested: Any
    selected_backend: str | None
    fallbacks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DesktopResult:
    ok: bool
    backend: str
    domain: str
    operation: str
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    message: str = ""
    duration_ms: int = 0
    evidence: list[dict[str, Any]] = field(default_factory=list)
    fallbacks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WindowContext:
    window_id: str | None = None
    title: str | None = None
    class_name: str | None = None
    hwnd: int | None = None
    screen_rect: list[int] | None = None
    client_rect: list[int] | None = None
    dpi_scale: float = 1.0
    coordinate_origin: str = "client"
    backend: str | None = None
    foreground: bool | None = None
    minimized: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CaptureResult:
    image_ref: str | None = None
    image_path: str | None = None
    width: int | None = None
    height: int | None = None
    region: list[int] | None = None
    window: WindowContext | dict[str, Any] | None = None
    backend: str = "fake"
    duration_ms: int = 0
    quality_flags: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LocatorResult:
    bbox: list[float] | None = None
    center: list[float] | None = None
    score: float | None = None
    threshold: float | None = None
    source: str | None = None
    method: str | None = None
    backend: str = "fake"
    timestamp_ms: int | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    error_code: str | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.error_code is None and self.center is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"ok": self.ok}


@dataclass(slots=True)
class DesktopActionResult:
    operation: str
    coordinate_space: str = "client"
    target_point: list[float] | None = None
    target_rect: list[float] | None = None
    backend: str = "fake"
    fallback_chain: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def error_result(
    *,
    backend: str,
    domain: str,
    operation: str,
    error_code: str,
    message: str,
    duration_ms: int = 0,
    fallbacks: list[dict[str, Any]] | None = None,
) -> DesktopResult:
    return DesktopResult(
        ok=False,
        backend=backend,
        domain=domain,
        operation=operation,
        error_code=error_code,
        message=message,
        duration_ms=duration_ms,
        fallbacks=fallbacks or [],
    )


def locator_evidence(locator: LocatorResult | dict[str, Any], *, source: str | None = None) -> dict[str, Any]:
    payload = locator.to_dict() if hasattr(locator, "to_dict") else dict(locator)
    return {
        "kind": "locator",
        "source": source or payload.get("source"),
        "payload": payload,
    }

"""Unified desktop facade."""

from __future__ import annotations

from typing import Any

from packages.aura_core.policy import evaluate_capability_policy

from .backends import (
    ClipboardKeyboardBackend,
    DxgiCaptureBackend,
    FakeCaptureBackend,
    FakeKeyboardBackend,
    FakeMouseBackend,
    FakeOcrBackend,
    FakeWindowBackend,
    GdiCaptureBackend,
    MssCaptureBackend,
    PaddleOcrBackend,
    PrintWindowCaptureBackend,
    RawInputBackend,
    UnsupportedBackend,
    UiaKeyboardBackend,
    UiaMouseBackend,
    UiaWindowBackend,
    Win32KeybdEventBackend,
    Win32MouseEventBackend,
    Win32PostMessageKeyboardBackend,
    Win32PostMessageMouseBackend,
    Win32SendInputKeyboardBackend,
    Win32SendInputMouseBackend,
    Win32WindowBackend,
)
from .models import DesktopResult, error_result
from .registry import DesktopCapabilityRegistry, get_desktop_registry


class DesktopFacade:
    """Selects desktop backends and normalizes their operation results."""

    def __init__(self, registry: DesktopCapabilityRegistry | None = None, profile: str = "default") -> None:
        self.registry = registry or get_desktop_registry()
        self.profile = profile
        self._backends: dict[tuple[str, str], Any] = {}

    def list_capabilities(self, domain: str | None = None) -> dict[str, list[dict[str, Any]]]:
        return self.registry.list(domain)

    def self_check(self, domain: str | None = None) -> dict[str, Any]:
        return self.registry.self_check(domain)

    def mouse(self, operation: str, *, backend: Any = None, profile: str | None = None, **params: Any) -> DesktopResult:
        return self._dispatch("mouse", operation, backend=backend, profile=profile, params=params)

    def keyboard(self, operation: str, *, backend: Any = None, profile: str | None = None, **params: Any) -> DesktopResult:
        return self._dispatch("keyboard", operation, backend=backend, profile=profile, params=params)

    def capture(self, operation: str, *, backend: Any = None, profile: str | None = None, **params: Any) -> DesktopResult:
        return self._dispatch("capture", operation, backend=backend, profile=profile, params=params)

    def window(self, operation: str, *, backend: Any = None, profile: str | None = None, **params: Any) -> DesktopResult:
        return self._dispatch("window", operation, backend=backend, profile=profile, params=params)

    def ocr(self, operation: str, *, backend: Any = None, profile: str | None = None, **params: Any) -> DesktopResult:
        return self._dispatch("ocr", operation, backend=backend, profile=profile, params=params)

    def capture_screen(self, **params: Any) -> DesktopResult:
        return self.capture("capture_screen", **params)

    def capture_window(self, **params: Any) -> DesktopResult:
        return self.capture("capture_window", **params)

    def capture_region(self, **params: Any) -> DesktopResult:
        return self.capture("capture_region", **params)

    def _dispatch(
        self,
        domain: str,
        operation: str,
        *,
        backend: Any,
        profile: str | None,
        params: dict[str, Any],
    ) -> DesktopResult:
        params = self._normalize_coordinate_params(domain, operation, params)
        selection = self.registry.select(domain, requested=backend, profile=profile or self.profile)
        if not selection.selected_backend:
            return error_result(
                backend=str(backend or ""),
                domain=domain,
                operation=operation,
                error_code="backend_unavailable",
                message=f"No available backend for {domain}.{operation}.",
                fallbacks=selection.fallbacks,
            )

        descriptor = self.registry.get(domain, selection.selected_backend)
        if descriptor is not None:
            backend_caps = _policy_capabilities_for_backend(domain, selection.selected_backend, operation)
            decision = evaluate_capability_policy(
                subject=f"desktop.backend.{domain}.{selection.selected_backend}",
                capabilities=backend_caps,
                side_effect_level=descriptor.side_effect_level,
                requires_admin=descriptor.requires_admin,
            )
            if decision.decision != "allow":
                result = error_result(
                    backend=selection.selected_backend,
                    domain=domain,
                    operation=operation,
                    error_code="policy_denied",
                    message=decision.reason,
                    fallbacks=selection.fallbacks,
                )
                result.evidence.append({"kind": "policy", "payload": decision.to_dict()})
                return result

        instance = self._get_backend(domain, selection.selected_backend)
        runner = getattr(instance, operation, None)
        if runner is None:
            return error_result(
                backend=selection.selected_backend,
                domain=domain,
                operation=operation,
                error_code="operation_not_supported",
                message=f"Backend '{selection.selected_backend}' does not support {operation}.",
                fallbacks=selection.fallbacks,
            )

        try:
            result = runner(**params)
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=selection.selected_backend,
                domain=domain,
                operation=operation,
                error_code="backend_operation_failed",
                message=str(exc),
                fallbacks=selection.fallbacks,
            )
        if isinstance(result, DesktopResult):
            result.fallbacks = selection.fallbacks
            result.data.setdefault("coordinate_space", params.get("coordinate_space", "client"))
            return result
        return DesktopResult(
            ok=True,
            backend=selection.selected_backend,
            domain=domain,
            operation=operation,
            data={"value": result},
            fallbacks=selection.fallbacks,
        )

    def _normalize_coordinate_params(self, domain: str, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(params)
        coordinate_space = str(normalized.get("coordinate_space") or "client").lower()
        normalized["coordinate_space"] = coordinate_space
        if domain != "mouse":
            return normalized

        if coordinate_space == "normalized":
            width = float(normalized.get("screen_width") or normalized.get("window_width") or 1280)
            height = float(normalized.get("screen_height") or normalized.get("window_height") or 720)
            for x_key, y_key in (("x", "y"), ("start_x", "start_y"), ("end_x", "end_y")):
                if x_key in normalized and y_key in normalized:
                    normalized[x_key] = int(float(normalized[x_key]) * width)
                    normalized[y_key] = int(float(normalized[y_key]) * height)
        # screen/window/client currently share numeric coordinates. The explicit
        # marker is still persisted so diagnostics can show which model was used.
        return normalized

    def _get_backend(self, domain: str, backend_id: str) -> Any:
        key = (domain, backend_id)
        if key not in self._backends:
            self._backends[key] = self._create_backend(domain, backend_id)
        return self._backends[key]

    def _create_backend(self, domain: str, backend_id: str) -> Any:
        if domain == "mouse":
            if backend_id == "win32_sendinput":
                return Win32SendInputMouseBackend()
            if backend_id == "win32_mouse_event":
                return Win32MouseEventBackend()
            if backend_id == "win32_postmessage":
                return Win32PostMessageMouseBackend()
            if backend_id == "raw_input":
                return RawInputBackend()
            if backend_id == "uia":
                return UiaMouseBackend()
            if backend_id == "fake":
                return FakeMouseBackend()
            if backend_id == "hid_mouse":
                return UnsupportedBackend("mouse", "hid_mouse", "hid_mouse requires a configured virtual HID driver.")
            return UnsupportedBackend("mouse", backend_id, f"Mouse backend '{backend_id}' is not implemented yet.")

        if domain == "keyboard":
            if backend_id == "win32_sendinput":
                return Win32SendInputKeyboardBackend()
            if backend_id == "win32_keybd_event":
                return Win32KeybdEventBackend()
            if backend_id == "win32_postmessage":
                return Win32PostMessageKeyboardBackend()
            if backend_id == "clipboard_paste":
                return ClipboardKeyboardBackend()
            if backend_id == "uia":
                return UiaKeyboardBackend()
            if backend_id == "fake":
                return FakeKeyboardBackend()
            return UnsupportedBackend("keyboard", backend_id, f"Keyboard backend '{backend_id}' is not implemented yet.")

        if domain == "capture":
            if backend_id == "gdi":
                return GdiCaptureBackend()
            if backend_id == "mss":
                return MssCaptureBackend()
            if backend_id == "dxgi":
                return DxgiCaptureBackend()
            if backend_id == "printwindow":
                return PrintWindowCaptureBackend()
            if backend_id == "fake":
                return FakeCaptureBackend()
            return UnsupportedBackend("capture", backend_id, f"Capture backend '{backend_id}' is not implemented through facade yet.")

        if domain == "window":
            if backend_id == "win32":
                return Win32WindowBackend()
            if backend_id == "uia":
                return UiaWindowBackend()
            if backend_id == "fake":
                return FakeWindowBackend()
            return UnsupportedBackend("window", backend_id, f"Window backend '{backend_id}' is not implemented through facade yet.")

        if domain == "ocr":
            if backend_id == "paddleocr":
                return PaddleOcrBackend()
            if backend_id == "fake":
                return FakeOcrBackend()
            return UnsupportedBackend("ocr", backend_id, f"OCR backend '{backend_id}' is not implemented through facade yet.")

        return UnsupportedBackend(domain, backend_id, f"Backend '{backend_id}' is not implemented for {domain}.")


def _policy_capabilities_for_backend(domain: str, backend_id: str, operation: str) -> list[str]:
    if domain == "mouse":
        if backend_id == "raw_input":
            return ["desktop.raw_input.monitor"]
        if backend_id == "hid_mouse":
            return ["desktop.hid.input"]
        return ["desktop.mouse.input"]
    if domain == "keyboard":
        return ["desktop.keyboard.input"]
    if domain == "capture":
        return ["desktop.capture.read"]
    if domain == "window":
        return ["desktop.window.focus" if operation == "focus" else "desktop.window.read"]
    if domain == "ocr":
        return ["desktop.ocr.read"]
    return []

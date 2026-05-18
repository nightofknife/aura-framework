"""Desktop capability registry and backend selection policy."""

from __future__ import annotations

import ctypes
import importlib.util
import os
import sys
from typing import Any

from .models import BackendDescriptor, BackendSelection


PROFILE_ORDER: dict[str, dict[str, list[str]]] = {
    "default": {
        "capture": ["gdi", "mss", "dxgi", "printwindow", "fake"],
        "mouse": ["win32_sendinput", "win32_mouse_event", "fake"],
        "keyboard": ["win32_sendinput", "win32_keybd_event", "clipboard_paste", "fake"],
        "window": ["win32", "uia", "fake"],
        "ocr": ["paddleocr", "fake"],
    },
    "safe": {
        "capture": ["gdi", "mss", "fake"],
        "mouse": ["uia", "win32_sendinput", "fake"],
        "keyboard": ["uia", "clipboard_paste", "win32_sendinput", "fake"],
        "window": ["uia", "win32", "fake"],
        "ocr": ["paddleocr", "fake"],
    },
    "fast": {
        "capture": ["dxgi", "mss", "gdi", "fake"],
        "mouse": ["win32_sendinput", "win32_mouse_event", "fake"],
        "keyboard": ["win32_sendinput", "win32_keybd_event", "fake"],
        "window": ["win32", "fake"],
        "ocr": ["paddleocr", "fake"],
    },
    "background": {
        "capture": ["printwindow", "gdi", "fake"],
        "mouse": ["win32_postmessage", "uia", "fake"],
        "keyboard": ["win32_postmessage", "uia", "clipboard_paste", "fake"],
        "window": ["win32", "uia", "fake"],
        "ocr": ["paddleocr", "fake"],
    },
    "raw": {
        "capture": ["dxgi", "gdi", "fake"],
        "mouse": ["hid_mouse", "win32_sendinput", "win32_mouse_event", "fake"],
        "keyboard": ["win32_sendinput", "win32_keybd_event", "fake"],
        "window": ["win32", "fake"],
        "ocr": ["paddleocr", "fake"],
    },
}


class DesktopCapabilityRegistry:
    """Registry for Windows desktop automation backend capabilities."""

    def __init__(self) -> None:
        self._descriptors: dict[str, dict[str, BackendDescriptor]] = {}
        self.refresh()

    def refresh(self) -> None:
        self._descriptors = {}
        for descriptor in _build_default_descriptors():
            self.register(descriptor)

    def register(self, descriptor: BackendDescriptor) -> None:
        self._descriptors.setdefault(descriptor.domain, {})[descriptor.backend_id] = descriptor

    def list_domains(self) -> list[str]:
        return sorted(self._descriptors)

    def list(self, domain: str | None = None) -> dict[str, list[dict[str, Any]]]:
        if domain:
            return {domain: [item.to_dict() for item in self._descriptors.get(domain, {}).values()]}
        return {
            name: [item.to_dict() for item in sorted(items.values(), key=lambda item: item.backend_id)]
            for name, items in sorted(self._descriptors.items())
        }

    def get(self, domain: str, backend_id: str) -> BackendDescriptor | None:
        return self._descriptors.get(domain, {}).get(backend_id)

    def self_check(self, domain: str | None = None) -> dict[str, Any]:
        domains = [domain] if domain else self.list_domains()
        results: dict[str, Any] = {}
        for name in domains:
            results[name] = [
                {
                    "backend_id": descriptor.backend_id,
                    "available": descriptor.available,
                    "health_status": descriptor.health_status,
                    "last_error": descriptor.last_error,
                }
                for descriptor in self._descriptors.get(name, {}).values()
            ]
        return {"status": "ok", "domains": results}

    def select(self, domain: str, requested: Any = None, profile: str = "default") -> BackendSelection:
        candidates = _requested_candidates(requested)
        explicit = bool(candidates)
        if not candidates:
            candidates = PROFILE_ORDER.get(profile, PROFILE_ORDER["default"]).get(domain, [])

        fallbacks: list[dict[str, Any]] = []
        for backend_id in candidates:
            descriptor = self.get(domain, backend_id)
            if descriptor is None:
                fallbacks.append({"backend": backend_id, "reason": "not_registered"})
                continue
            if descriptor.available:
                return BackendSelection(
                    domain=domain,
                    profile=profile,
                    requested=requested,
                    selected_backend=backend_id,
                    fallbacks=fallbacks,
                )
            fallbacks.append(
                {
                    "backend": backend_id,
                    "reason": descriptor.last_error or descriptor.health_status or "unavailable",
                }
            )
            if explicit and len(candidates) == 1:
                break

        return BackendSelection(
            domain=domain,
            profile=profile,
            requested=requested,
            selected_backend=None,
            fallbacks=fallbacks,
        )


def get_desktop_registry() -> DesktopCapabilityRegistry:
    global _REGISTRY
    try:
        return _REGISTRY
    except NameError:
        _REGISTRY = DesktopCapabilityRegistry()
        return _REGISTRY


def _requested_candidates(requested: Any) -> list[str]:
    if requested is None:
        return []
    if isinstance(requested, str):
        return [requested]
    if isinstance(requested, dict):
        prefer = requested.get("prefer")
        fallback = requested.get("fallback") or []
        candidates: list[str] = []
        if prefer:
            candidates.append(str(prefer))
        if isinstance(fallback, list):
            candidates.extend(str(item) for item in fallback)
        return candidates
    return [str(requested)]


def _build_default_descriptors() -> list[BackendDescriptor]:
    is_windows = sys.platform == "win32"
    win32_available, win32_error = _module_available("win32api")
    win32gui_available, win32gui_error = _module_available("win32gui")
    win32ui_available, win32ui_error = _module_available("win32ui")
    mss_available, mss_error = _module_available("mss")
    dxcam_available, dxcam_error = _module_available("dxcam")
    paddle_available, paddle_error = _module_available("paddleocr")
    uia_available, uia_error = _module_available("pywinauto")
    hid_available, hid_error = _hid_mouse_available()

    descriptors = [
        _descriptor("capture", "gdi", is_windows and win32gui_available and win32ui_available, _join_errors(win32gui_error, win32ui_error), False, False, False, False,
                    ["screen_capture", "window_capture", "region_capture"], ["may fail on protected or GPU surfaces"]),
        _descriptor("capture", "mss", mss_available, mss_error, False, False, False, False,
                    ["screen_capture", "region_capture", "multi_monitor"], ["optional dependency"]),
        _descriptor("capture", "dxgi", dxcam_available, dxcam_error, False, False, False, False,
                    ["screen_capture", "region_capture", "high_fps"], ["optional dependency", "may not capture all windows"]),
        _descriptor("capture", "printwindow", is_windows and win32gui_available and win32ui_available, _join_errors(win32gui_error, win32ui_error), False, True, False, False,
                    ["window_capture", "background_window"], ["does not work for all GPU or minimized windows"]),
        _descriptor("capture", "fake", True, None, False, True, True, False,
                    ["screen_capture", "window_capture", "region_capture", "test_fixture"], []),
        _descriptor("mouse", "win32_mouse_event", is_windows and win32_available, win32_error, True, False, False, False,
                    ["move", "click", "drag", "scroll"], ["compat backend"], stability="compat"),
        _descriptor("mouse", "win32_sendinput", is_windows, None if is_windows else "Windows only", True, False, False, False,
                    ["move", "relative_move", "click", "drag", "scroll", "down", "up"], ["foreground input injection"]),
        _descriptor("mouse", "win32_postmessage", is_windows and win32gui_available, win32gui_error, False, True, False, False,
                    ["click", "down", "up", "scroll"], ["target apps may ignore posted messages"], stability="experimental"),
        _descriptor("mouse", "raw_input", is_windows, None if is_windows else "Windows only", False, True, True, False,
                    ["listen", "diagnose", "record", "calibrate"], ["Raw Input receives events; it does not inject events"]),
        _descriptor("mouse", "hid_mouse", hid_available, hid_error, False, True, True, True,
                    ["relative_move", "click", "scroll", "down", "up"], ["requires preinstalled virtual HID or Interception driver"], stability="experimental"),
        _descriptor("mouse", "uia", uia_available, uia_error, False, True, False, False,
                    ["invoke", "semantic_click"], ["optional dependency"], stability="experimental"),
        _descriptor("mouse", "fake", True, None, False, True, True, False,
                    ["move", "click", "drag", "scroll", "test_fixture"], []),
        _descriptor("keyboard", "win32_keybd_event", is_windows and win32_available, win32_error, True, False, False, False,
                    ["key_down", "key_up", "press", "type_text"], ["compat backend"], stability="compat"),
        _descriptor("keyboard", "win32_sendinput", is_windows, None if is_windows else "Windows only", True, False, False, False,
                    ["key_down", "key_up", "press", "hotkey", "type_text"], ["foreground input injection"]),
        _descriptor("keyboard", "win32_postmessage", is_windows and win32gui_available, win32gui_error, False, True, False, False,
                    ["key_down", "key_up", "press", "type_text"], ["target apps may ignore posted messages"], stability="experimental"),
        _descriptor("keyboard", "clipboard_paste", is_windows, None if is_windows else "Windows only", True, False, False, False,
                    ["paste_text"], ["mutates clipboard temporarily"]),
        _descriptor("keyboard", "uia", uia_available, uia_error, False, True, False, False,
                    ["set_value", "invoke"], ["optional dependency"], stability="experimental"),
        _descriptor("keyboard", "fake", True, None, False, True, True, False,
                    ["key_down", "key_up", "press", "hotkey", "type_text", "test_fixture"], []),
        _descriptor("window", "win32", is_windows and win32gui_available, win32gui_error, False, True, False, False,
                    ["list_windows", "find_window", "focus", "rect", "client_rect"], []),
        _descriptor("window", "uia", uia_available, uia_error, False, True, False, False,
                    ["list_windows", "find_window", "semantic_controls"], ["optional dependency"], stability="experimental"),
        _descriptor("window", "fake", True, None, False, True, True, False,
                    ["list_windows", "find_window", "focus", "rect", "test_fixture"], []),
        _descriptor("ocr", "paddleocr", paddle_available, paddle_error, False, True, True, False,
                    ["recognize", "find_text"], ["heavy optional runtime"]),
        _descriptor("ocr", "fake", True, None, False, True, True, False,
                    ["recognize", "find_text", "test_fixture"], []),
    ]
    return descriptors


def _descriptor(
    domain: str,
    backend_id: str,
    available: bool,
    error: str | None,
    requires_foreground: bool,
    supports_background: bool,
    supports_minimized: bool,
    requires_admin: bool,
    capabilities: list[str],
    limitations: list[str],
    *,
    stability: str = "stable",
) -> BackendDescriptor:
    return BackendDescriptor(
        backend_id=backend_id,
        domain=domain,
        available=bool(available),
        health_status="available" if available else "unavailable",
        requires_foreground=requires_foreground,
        supports_background=supports_background,
        supports_minimized=supports_minimized,
        requires_admin=requires_admin,
        side_effect_level="none" if backend_id == "fake" or "listen" in capabilities else "input" if domain in {"mouse", "keyboard"} else "read",
        capabilities=capabilities,
        limitations=limitations,
        last_error=None if available else error,
        stability=stability,
    )


def _module_available(name: str) -> tuple[bool, str | None]:
    if importlib.util.find_spec(name) is None:
        return False, f"Python module '{name}' is not installed."
    return True, None


def _join_errors(*errors: str | None) -> str | None:
    values = [error for error in errors if error]
    return "; ".join(values) if values else None


def _hid_mouse_available() -> tuple[bool, str | None]:
    dll_path = os.environ.get("AURA_HID_MOUSE_DLL")
    if not dll_path:
        return False, "No AURA_HID_MOUSE_DLL configured; virtual HID/Interception driver is not registered."
    try:
        ctypes.WinDLL(dll_path)
    except Exception as exc:  # noqa: BLE001
        return False, f"HID mouse driver DLL is not loadable: {exc}"
    return True, None

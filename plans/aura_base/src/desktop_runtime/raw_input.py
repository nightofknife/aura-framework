"""Raw Input helpers.

Raw Input is modeled as an event monitor. It is intentionally not exposed as an
injection backend because the Windows Raw Input API receives hardware input; it
does not synthesize mouse events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RawMouseEvent:
    device_handle: int | None
    flags: int
    buttons: list[str]
    wheel_delta: int
    dx: int
    dy: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_handle": self.device_handle,
            "flags": self.flags,
            "buttons": list(self.buttons),
            "wheel_delta": self.wheel_delta,
            "dx": self.dx,
            "dy": self.dy,
        }


def normalize_raw_mouse_event(
    *,
    device_handle: int | None = None,
    flags: int = 0,
    button_flags: int = 0,
    button_data: int = 0,
    last_x: int = 0,
    last_y: int = 0,
) -> RawMouseEvent:
    buttons: list[str] = []
    if button_flags & 0x0001:
        buttons.append("left_down")
    if button_flags & 0x0002:
        buttons.append("left_up")
    if button_flags & 0x0004:
        buttons.append("right_down")
    if button_flags & 0x0008:
        buttons.append("right_up")
    if button_flags & 0x0010:
        buttons.append("middle_down")
    if button_flags & 0x0020:
        buttons.append("middle_up")

    wheel_delta = 0
    if button_flags & 0x0400:
        wheel_delta = _signed_short(button_data)

    return RawMouseEvent(
        device_handle=device_handle,
        flags=flags,
        buttons=buttons,
        wheel_delta=wheel_delta,
        dx=last_x,
        dy=last_y,
    )


def _signed_short(value: int) -> int:
    value = int(value) & 0xFFFF
    if value >= 0x8000:
        value -= 0x10000
    return value


class RawInputMonitor:
    """Small event buffer for raw input diagnostics.

    The platform message pump integration is intentionally explicit: callers
    must provide a HWND that owns a Windows message loop before registration.
    Unit tests can still validate event normalization without touching the OS.
    """

    def __init__(self, max_events: int = 200) -> None:
        self.max_events = max_events
        self._events: list[RawMouseEvent] = []
        self.registered_hwnd: int | None = None

    def register(self, hwnd: int) -> bool:
        if hwnd is None:
            raise ValueError("Raw input registration requires a HWND.")
        self.registered_hwnd = int(hwnd)
        try:
            import ctypes
            from ctypes import wintypes

            class RAWINPUTDEVICE(ctypes.Structure):
                _fields_ = [
                    ("usUsagePage", wintypes.USHORT),
                    ("usUsage", wintypes.USHORT),
                    ("dwFlags", wintypes.DWORD),
                    ("hwndTarget", wintypes.HWND),
                ]

            device = RAWINPUTDEVICE(0x01, 0x02, 0x00000100, wintypes.HWND(hwnd))
            return bool(ctypes.windll.user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device)))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"RegisterRawInputDevices failed: {exc}") from exc

    def push_event(self, event: RawMouseEvent) -> None:
        self._events.append(event)
        if len(self._events) > self.max_events:
            del self._events[: len(self._events) - self.max_events]

    def list_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self._events[-limit:]]

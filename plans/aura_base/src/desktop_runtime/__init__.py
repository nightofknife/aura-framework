"""Desktop capability runtime for aura_base."""

from .facade import DesktopFacade
from .models import (
    BackendDescriptor,
    BackendSelection,
    CaptureResult,
    DesktopActionResult,
    DesktopResult,
    LocatorResult,
    WindowContext,
)
from .registry import DesktopCapabilityRegistry, get_desktop_registry

__all__ = [
    "BackendDescriptor",
    "BackendSelection",
    "CaptureResult",
    "DesktopActionResult",
    "DesktopCapabilityRegistry",
    "DesktopFacade",
    "DesktopResult",
    "LocatorResult",
    "WindowContext",
    "get_desktop_registry",
]

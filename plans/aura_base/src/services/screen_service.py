"""Screen/window service backed by the desktop runtime facade."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

import cv2
import numpy as np

from packages.aura_core.api import service_info
from packages.aura_core.observability.logging.core_logger import logger
from ..desktop_runtime import DesktopFacade, get_desktop_registry
from ..desktop_runtime.models import DesktopResult
from .config_service import ConfigService


@dataclass
class CaptureResult:
    success: bool
    image: np.ndarray | None = None
    window_rect: tuple[int, int, int, int] | None = None
    relative_rect: tuple[int, int, int, int] | None = None
    backend: str | None = None
    quality_flags: list[str] = field(default_factory=list)
    error_message: str = field(default="", repr=False)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    @property
    def image_size(self) -> tuple[int, int] | None:
        if self.image is not None:
            return self.image.shape[1], self.image.shape[0]
        return None

    def save(self, filepath: str) -> None:
        if self.success and self.image is not None:
            try:
                image_bgr = cv2.cvtColor(self.image, cv2.COLOR_RGB2BGR)
                cv2.imwrite(filepath, image_bgr)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to save capture '%s': %s", filepath, exc)
        elif not self.success:
            logger.warning("Capture failed; cannot save image: %s", self.error_message)
        else:
            logger.warning("Capture image data is empty; cannot save.")


@service_info(
    alias="screen",
    public=True,
    deps={"config": "core/config"},
    capabilities=["desktop.capture.read", "desktop.window.read"],
    side_effect_level="read",
)
class ScreenService:
    """Synchronous-compatible screen capture and window helper service."""

    _ALL_BACKENDS = ("gdi", "mss", "dxgi", "printwindow", "fake")

    def __init__(self, config: ConfigService):
        self.config = config
        self.desktop = DesktopFacade()
        self.hwnd: int | None = None
        self._desktop_registry = get_desktop_registry()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()
        self._runtime_default_backend: str | None = None
        self._update_hwnd()
        logger.info("Screen service initialized through desktop facade.")

    @property
    def enabled_backends(self) -> list[str]:
        configured = self.config.get("screen.capture.enabled_backends", None)
        if not isinstance(configured, list):
            return list(self._ALL_BACKENDS)
        normalized = [str(item).lower() for item in configured]
        filtered = [item for item in normalized if item in self._ALL_BACKENDS]
        return filtered or list(self._ALL_BACKENDS)

    @property
    def default_backend(self) -> str:
        if self._runtime_default_backend and self._runtime_default_backend in self.enabled_backends:
            return self._runtime_default_backend
        configured = self.config.get("screen.capture.default_backend", None)
        configured = configured.lower() if isinstance(configured, str) else None
        if configured in self.enabled_backends:
            return configured
        return self.enabled_backends[0]

    @property
    def target_title(self) -> Optional[str]:
        return self.config.get("app.target_window_title", None)

    def list_backends(self) -> dict[str, Any]:
        capture_capabilities = self._desktop_registry.list("capture").get("capture", [])
        return {
            "available": list(self._ALL_BACKENDS),
            "enabled": list(self.enabled_backends),
            "default": self.default_backend,
            "capabilities": capture_capabilities,
        }

    def set_default_backend(self, backend: str) -> None:
        backend = (backend or "").lower()
        if backend not in self.enabled_backends:
            raise ValueError(f"Backend '{backend}' is not enabled.")
        self._runtime_default_backend = backend

    def self_check(self) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for backend in self.enabled_backends:
            result = self._capture_backend_sync(backend, None)
            results[backend] = {
                "success": result.success,
                "error": result.error_message,
                "quality_flags": list(result.quality_flags),
                "size": result.image_size,
            }
        return {
            "default": self.default_backend,
            "enabled": list(self.enabled_backends),
            "registry": self._desktop_registry.self_check("capture"),
            "results": results,
        }

    def get_client_rect(self) -> tuple[int, int, int, int] | None:
        if not self.target_title and not self.hwnd:
            return None
        self._update_hwnd()
        result = self.desktop.window("get_client_rect", backend="win32", **self._window_params())
        if not result.ok:
            logger.debug("Failed to get client rect through facade: %s", result.message)
            return None
        rect = result.data.get("rect")
        return tuple(int(v) for v in rect) if rect else None

    def get_pixel_color_at(self, global_x: int, global_y: int) -> tuple[int, int, int]:
        capture = self._capture_with_fallback_sync((int(global_x), int(global_y), 1, 1), None)
        if not capture.success or capture.image is None:
            raise RuntimeError(capture.error_message or "Pixel capture failed.")
        pixel = capture.image[0, 0]
        return int(pixel[0]), int(pixel[1]), int(pixel[2])

    def focus(self) -> bool:
        return self._submit_to_loop_and_wait(self.focus_async())

    def capture(self, rect: tuple[int, int, int, int] | None = None, backend: Optional[str] = None) -> CaptureResult:
        return self._submit_to_loop_and_wait(self.capture_async(rect, backend))

    async def focus_async(self) -> bool:
        return await asyncio.to_thread(self._focus_sync)

    async def capture_async(self, rect: tuple[int, int, int, int] | None = None, backend: Optional[str] = None) -> CaptureResult:
        return await asyncio.to_thread(self._capture_with_fallback_sync, rect, backend)

    def _focus_sync(self) -> bool:
        self._update_hwnd()
        if not self.target_title and not self.hwnd:
            return False
        result = self.desktop.window("focus", backend="win32", **self._window_params())
        if not result.ok:
            logger.warning("Unable to focus window '%s': %s", self.target_title, result.message)
        return bool(result.ok)

    def _capture_with_fallback_sync(
        self,
        rect: tuple[int, int, int, int] | None,
        backend: Optional[str],
    ) -> CaptureResult:
        if backend:
            return self._capture_backend_sync(backend.lower(), rect)
        last_result: CaptureResult | None = None
        for name in self._get_backend_order():
            result = self._capture_backend_sync(name, rect)
            last_result = result
            if result.success:
                self._runtime_default_backend = name
                return result
        return last_result or CaptureResult(success=False, error_message="No capture backends available.")

    def _capture_backend_sync(self, backend: str, rect: tuple[int, int, int, int] | None) -> CaptureResult:
        backend = (backend or "").lower()
        if backend not in self.enabled_backends:
            return CaptureResult(success=False, backend=backend, error_message="Backend not enabled.")

        self._update_hwnd()
        window_params = self._window_params()
        if self.target_title or self.hwnd:
            operation = "capture_window"
            params: dict[str, Any] = {**window_params}
            if rect:
                params["region"] = list(rect)
        elif rect:
            operation = "capture_region"
            params = {"region": list(rect)}
        else:
            operation = "capture_screen"
            params = {}

        result = self.desktop.capture(operation, backend=backend, **params)
        return self._to_capture_result(result)

    def _to_capture_result(self, result: DesktopResult) -> CaptureResult:
        data = result.data or {}
        capture = data.get("capture") if isinstance(data.get("capture"), dict) else {}
        image = data.get("_image")
        width = int(data.get("width") or capture.get("width") or 0)
        height = int(data.get("height") or capture.get("height") or 0)
        if result.ok and image is None and width > 0 and height > 0:
            image = np.full((height, width, 3), 127, dtype=np.uint8)
        window = capture.get("window") if isinstance(capture.get("window"), dict) else None
        window_rect = _tuple4((window or {}).get("screen_rect") or capture.get("region"))
        relative_rect = _tuple4(capture.get("region")) or ((0, 0, width, height) if width and height else None)
        quality_flags = list(capture.get("quality_flags") or [])
        if result.ok and image is not None:
            quality_flags.extend(_evaluate_image_quality(image))
        return CaptureResult(
            success=bool(result.ok and image is not None),
            image=image,
            window_rect=window_rect,
            relative_rect=relative_rect,
            backend=result.backend,
            quality_flags=list(dict.fromkeys(quality_flags)),
            error_message="" if result.ok else result.message,
            evidence=list(result.evidence or []),
        )

    def _get_backend_order(self) -> list[str]:
        enabled = list(self.enabled_backends)
        default = self.default_backend
        if default in enabled:
            enabled.remove(default)
            return [default] + enabled
        return enabled

    def _window_params(self) -> dict[str, Any]:
        if self.hwnd:
            return {"hwnd": self.hwnd}
        if self.target_title:
            return {"title": self.target_title}
        return {}

    def _update_hwnd(self) -> None:
        if not self.target_title:
            self.hwnd = None
            return
        result = self.desktop.window("find_window", backend="win32", title=self.target_title)
        if result.ok:
            window = result.data.get("window") or {}
            self.hwnd = int(window.get("hwnd") or 0) or None
        else:
            self.hwnd = None

    def _get_running_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:
            if self._loop is None or self._loop.is_closed():
                from packages.aura_core.api import service_registry

                scheduler = service_registry.get_service_instance("scheduler")
                if scheduler and scheduler._loop and scheduler._loop.is_running():
                    self._loop = scheduler._loop
                else:
                    raise RuntimeError("ScreenService cannot find running asyncio loop.")
            return self._loop

    def _submit_to_loop_and_wait(self, coro: asyncio.Future) -> Any:
        loop = self._get_running_loop()
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is loop:
            raise RuntimeError("ScreenService sync API called from event loop thread; use *_async to avoid deadlock.")
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()


def _tuple4(value: Any) -> tuple[int, int, int, int] | None:
    if not value or len(value) < 4:
        return None
    return tuple(int(v) for v in value[:4])


def _evaluate_image_quality(image: np.ndarray) -> list[str]:
    flags: list[str] = []
    if image.ndim != 3 or image.shape[2] not in {3, 4}:
        flags.append("unexpected_shape")
        return flags
    gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY if image.shape[2] == 4 else cv2.COLOR_RGB2GRAY)
    if float(np.mean(gray < 5)) >= 0.98:
        flags.append("black_frame")
    if float(gray.std()) < 5.0:
        flags.append("low_variance")
    return flags

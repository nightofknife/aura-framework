# packages/aura_base/services/screen_service.py (async upgraded)

import asyncio
import threading
import time
from ctypes import windll
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import screeninfo
import win32con
import win32gui
import win32ui

from packages.aura_core.api import register_service
from packages.aura_core.logger import logger
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

    @property
    def image_size(self) -> tuple[int, int] | None:
        if self.image is not None:
            return self.image.shape[1], self.image.shape[0]
        return None

    def save(self, filepath: str):
        if self.success and self.image is not None:
            try:
                image_bgr = cv2.cvtColor(self.image, cv2.COLOR_RGB2BGR)
                cv2.imwrite(filepath, image_bgr)
            except Exception as e:
                logger.error("Failed to save capture '%s': %s", filepath, e)
        elif not self.success:
            logger.warning("Capture failed; cannot save image: %s", self.error_message)
        else:
            logger.warning("Capture image data is empty; cannot save.")


@register_service(alias="screen", public=True)
class ScreenService:
    """
    Async screen capture service with sync facade.
    """

    _ALL_BACKENDS = ("dxgi", "gdi", "mss")

    def __init__(self, config: ConfigService):
        self.config = config
        self.target_title = config.get('app.target_window_title', None)
        self.hwnd = None
        self._update_hwnd()
        logger.info(
            "Screen service initialized. Target: %s",
            "fullscreen" if self.target_title is None else f"window<{self.target_title}>",
        )

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()

        self._dxgi_lock = threading.Lock()
        self._dxgi_camera = None

        self._enabled_backends = self._load_enabled_backends()
        self._default_backend = self._load_default_backend()

        self._max_black_ratio = float(config.get('screen.capture.max_black_ratio', 0.98))
        self._min_stddev = float(config.get('screen.capture.min_stddev', 5.0))
        self._min_edge_ratio = float(config.get('screen.capture.min_edge_ratio', 0.001))

    # =========================================================================
    # Section 1: Public sync APIs
    # =========================================================================

    def list_backends(self) -> Dict[str, Any]:
        return {
            "available": list(self._ALL_BACKENDS),
            "enabled": list(self._enabled_backends),
            "default": self._default_backend,
        }

    def set_default_backend(self, backend: str):
        backend = (backend or "").lower()
        if backend not in self._enabled_backends:
            raise ValueError(f"Backend '{backend}' is not enabled.")
        self._default_backend = backend

    def self_check(self) -> Dict[str, Any]:
        results: Dict[str, Any] = {}
        context = self._build_capture_context_sync(rect=None)
        for backend in self._enabled_backends:
            result = self._capture_backend_sync(backend, context)
            results[backend] = {
                "success": result.success,
                "error": result.error_message,
                "quality_flags": list(result.quality_flags),
                "size": result.image_size,
            }
        return {
            "default": self._default_backend,
            "enabled": list(self._enabled_backends),
            "results": results,
        }

    def get_client_rect(self) -> tuple[int, int, int, int] | None:
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            self._update_hwnd()
        if self.hwnd:
            try:
                client_top_left = win32gui.ClientToScreen(self.hwnd, (0, 0))
                left, top, right, bot = win32gui.GetClientRect(self.hwnd)
                return (client_top_left[0], client_top_left[1], right - left, bot - top)
            except Exception as e:
                logger.error("Failed to get client rect: %s", e)
        return None

    def get_pixel_color_at(self, global_x: int, global_y: int) -> tuple[int, int, int]:
        h_win_dc = win32gui.GetWindowDC(0)
        try:
            long_color = win32gui.GetPixel(h_win_dc, global_x, global_y)
            return (long_color & 0xff, (long_color >> 8) & 0xff, (long_color >> 16) & 0xff)
        finally:
            win32gui.ReleaseDC(0, h_win_dc)

    def focus(self) -> bool:
        return self._submit_to_loop_and_wait(self.focus_async())

    def capture(self, rect: tuple[int, int, int, int] | None = None,
                backend: Optional[str] = None) -> CaptureResult:
        return self._submit_to_loop_and_wait(self.capture_async(rect, backend))

    # =========================================================================
    # Section 2: Async core
    # =========================================================================

    async def focus_async(self) -> bool:
        await asyncio.to_thread(self._update_hwnd)
        if self.hwnd:
            try:
                await asyncio.to_thread(win32gui.ShowWindow, self.hwnd, win32con.SW_RESTORE)
                await asyncio.to_thread(win32gui.SetForegroundWindow, self.hwnd)
                return True
            except Exception as e:
                logger.error("Failed to focus window %s: %s", self.hwnd, e)
                return False
        logger.warning("Unable to find window '%s' for focus.", self.target_title)
        return False

    async def capture_async(self, rect: tuple[int, int, int, int] | None = None,
                            backend: Optional[str] = None) -> CaptureResult:
        return await asyncio.to_thread(self._capture_with_fallback_sync, rect, backend)

    # =========================================================================
    # Section 3: Sync capture implementations
    # =========================================================================

    def _capture_with_fallback_sync(self, rect: tuple[int, int, int, int] | None,
                                    backend: Optional[str]) -> CaptureResult:
        context = self._build_capture_context_sync(rect)
        if backend:
            return self._capture_backend_sync(backend.lower(), context)

        backends = self._get_backend_order()
        last_result: Optional[CaptureResult] = None
        for name in backends:
            result = self._capture_backend_sync(name, context)
            last_result = result
            if result.success:
                self._default_backend = name
                return result

        if last_result:
            return last_result
        return CaptureResult(success=False, error_message="No capture backends available.")

    def _capture_backend_sync(self, backend: str, context: Dict[str, Any]) -> CaptureResult:
        backend = (backend or "").lower()
        if backend not in self._enabled_backends:
            return CaptureResult(success=False, backend=backend, error_message="Backend not enabled.")

        if not context:
            return CaptureResult(success=False, backend=backend, error_message="Capture context unavailable.")

        base_rect = context["client_rect"]
        window_rect = context["window_rect"]
        sub_rect = context["sub_rect"]
        hwnd = context.get("hwnd")
        expected_size = (sub_rect[2], sub_rect[3]) if sub_rect else (base_rect[2], base_rect[3])

        if backend == "gdi":
            if context["mode"] == "window" and hwnd:
                result = self._capture_window_sync(hwnd, sub_rect=sub_rect)
                result.backend = backend
                result.window_rect = window_rect
                result = self._finalize_capture_result(result, expected_size)
                if result.success:
                    return result

            image = self._capture_bitblt_region_sync(base_rect)
            if image is None:
                return CaptureResult(success=False, backend=backend, window_rect=window_rect,
                                    error_message="GDI BitBlt capture failed.")
            try:
                image, relative_rect = self._apply_sub_rect(image, sub_rect, base_rect)
            except ValueError as e:
                return CaptureResult(success=False, backend=backend, window_rect=window_rect,
                                    error_message=str(e))
            result = CaptureResult(success=True, image=image, window_rect=window_rect,
                                    relative_rect=relative_rect, backend=backend)
            return self._finalize_capture_result(result, expected_size)

        if backend == "dxgi":
            image = self._capture_dxgi_region_sync(base_rect)
            if image is None:
                return CaptureResult(success=False, backend=backend, window_rect=window_rect,
                                    error_message="DXGI capture failed.")
            try:
                image, relative_rect = self._apply_sub_rect(image, sub_rect, base_rect)
            except ValueError as e:
                return CaptureResult(success=False, backend=backend, window_rect=window_rect,
                                    error_message=str(e))
            result = CaptureResult(success=True, image=image, window_rect=window_rect,
                                    relative_rect=relative_rect, backend=backend)
            return self._finalize_capture_result(result, expected_size)

        if backend == "mss":
            image = self._capture_mss_region_sync(base_rect)
            if image is None:
                return CaptureResult(success=False, backend=backend, window_rect=window_rect,
                                    error_message="MSS capture failed.")
            try:
                image, relative_rect = self._apply_sub_rect(image, sub_rect, base_rect)
            except ValueError as e:
                return CaptureResult(success=False, backend=backend, window_rect=window_rect,
                                    error_message=str(e))
            result = CaptureResult(success=True, image=image, window_rect=window_rect,
                                    relative_rect=relative_rect, backend=backend)
            return self._finalize_capture_result(result, expected_size)

        return CaptureResult(success=False, backend=backend, error_message="Unknown backend.")

    def _build_capture_context_sync(self, rect: tuple[int, int, int, int] | None) -> Dict[str, Any]:
        if self.target_title:
            if not self.hwnd or not win32gui.IsWindow(self.hwnd):
                self._update_hwnd()

            if self.hwnd:
                if win32gui.IsIconic(self.hwnd):
                    try:
                        win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                        win32gui.SetWindowPos(
                            self.hwnd,
                            win32con.HWND_BOTTOM,
                            0,
                            0,
                            0,
                            0,
                            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
                        )
                        time.sleep(0.2)
                    except Exception as e:
                        logger.warning("Failed to restore minimized window: %s", e)

                metrics = self._get_window_metrics_sync(self.hwnd)
                if metrics:
                    window_rect, client_rect = metrics
                    return {
                        "mode": "window",
                        "hwnd": self.hwnd,
                        "window_rect": window_rect,
                        "client_rect": client_rect,
                        "sub_rect": rect,
                    }
            logger.warning("Window '%s' not found; falling back to fullscreen capture.", self.target_title)

        if rect:
            logger.warning("Capture rect ignored in fullscreen mode.")
        screen_rect = self._get_primary_monitor_rect()
        return {
            "mode": "fullscreen",
            "hwnd": None,
            "window_rect": screen_rect,
            "client_rect": screen_rect,
            "sub_rect": None,
        }

    def _get_window_metrics_sync(self, hwnd: int) -> Optional[Tuple[tuple[int, int, int, int], tuple[int, int, int, int]]]:
        try:
            left, top, right, bot = win32gui.GetWindowRect(hwnd)
            window_rect = (left, top, right - left, bot - top)
            client_top_left = win32gui.ClientToScreen(hwnd, (0, 0))
            c_left, c_top, c_right, c_bot = win32gui.GetClientRect(hwnd)
            client_width = c_right - c_left
            client_height = c_bot - c_top
            if client_width <= 0 or client_height <= 0:
                return None
            client_rect = (client_top_left[0], client_top_left[1], client_width, client_height)
            return window_rect, client_rect
        except Exception as e:
            logger.error("Failed to get window metrics: %s", e)
            return None

    def _apply_sub_rect(self, image: np.ndarray, sub_rect: tuple[int, int, int, int] | None,
                        base_rect: tuple[int, int, int, int]) -> Tuple[np.ndarray, tuple[int, int, int, int]]:
        base_width, base_height = base_rect[2], base_rect[3]
        if not sub_rect:
            return image, (0, 0, base_width, base_height)
        x, y, w, h = sub_rect
        if x < 0 or y < 0 or w <= 0 or h <= 0 or (x + w) > base_width or (y + h) > base_height:
            raise ValueError(f"Capture rect {sub_rect} out of bounds ({base_width}x{base_height}).")
        return image[y: y + h, x: x + w], sub_rect

    def _finalize_capture_result(self, result: CaptureResult,
                                 expected_size: tuple[int, int] | None) -> CaptureResult:
        if not result.success or result.image is None:
            return result
        flags = self._evaluate_image_quality(result.image, expected_size)
        result.quality_flags = flags
        if self._has_hard_fail(flags):
            result.success = False
            if not result.error_message:
                result.error_message = "Capture quality check failed."
        return result

    def _evaluate_image_quality(self, image: np.ndarray,
                                expected_size: tuple[int, int] | None) -> list[str]:
        flags: list[str] = []
        if expected_size:
            if (image.shape[1], image.shape[0]) != expected_size:
                flags.append("size_mismatch")

        if image.shape[2] == 4:
            gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        else:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

        black_ratio = float(np.mean(gray < 5))
        if black_ratio >= self._max_black_ratio:
            flags.append("black_frame")

        stddev = float(gray.std())
        if stddev < self._min_stddev:
            flags.append("low_variance")
            edges = cv2.Canny(gray, 50, 150)
            edge_ratio = float(np.mean(edges > 0))
            if edge_ratio < self._min_edge_ratio:
                flags.append("low_edges")

        return flags

    def _has_hard_fail(self, flags: list[str]) -> bool:
        return "size_mismatch" in flags or "black_frame" in flags

    def _get_backend_order(self) -> List[str]:
        enabled = list(self._enabled_backends)
        if self._default_backend in enabled:
            enabled.remove(self._default_backend)
            return [self._default_backend] + enabled
        return enabled

    def _load_enabled_backends(self) -> List[str]:
        configured = self.config.get('screen.capture.enabled_backends', None)
        if not isinstance(configured, list):
            configured = list(self._ALL_BACKENDS)
        normalized = [str(item).lower() for item in configured]
        filtered = [item for item in normalized if item in self._ALL_BACKENDS]
        return filtered or list(self._ALL_BACKENDS)

    def _load_default_backend(self) -> str:
        configured = self.config.get('screen.capture.default_backend', None)
        configured = configured.lower() if isinstance(configured, str) else None
        if configured in self._enabled_backends:
            return configured
        return self._enabled_backends[0]

    def _get_primary_monitor_rect(self) -> tuple[int, int, int, int]:
        primary_screen = screeninfo.get_monitors()[0]
        return (primary_screen.x, primary_screen.y, primary_screen.width, primary_screen.height)

    def _capture_dxgi_region_sync(self, rect: tuple[int, int, int, int]) -> Optional[np.ndarray]:
        try:
            import dxcam
        except Exception as e:
            logger.warning("DXGI backend unavailable: %s", e)
            return None

        with self._dxgi_lock:
            try:
                if self._dxgi_camera is None:
                    self._dxgi_camera = dxcam.create()
            except Exception as e:
                logger.warning("DXGI backend init failed: %s", e)
                self._dxgi_camera = None
                return None

            if self._dxgi_camera is None:
                return None

            left, top, width, height = rect
            region = (left, top, left + width, top + height)
            frame = self._dxgi_camera.grab(region=region)

        if frame is None:
            return None

        if frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def _capture_mss_region_sync(self, rect: tuple[int, int, int, int]) -> Optional[np.ndarray]:
        try:
            import mss
        except Exception as e:
            logger.warning("MSS backend unavailable: %s", e)
            return None

        left, top, width, height = rect
        try:
            with mss.mss() as sct:
                monitor = {"left": left, "top": top, "width": width, "height": height}
                shot = sct.grab(monitor)
                img = np.array(shot, dtype=np.uint8)
                return cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
        except Exception as e:
            logger.warning("MSS capture failed: %s", e)
            return None

    def _capture_bitblt_region_sync(self, rect: tuple[int, int, int, int]) -> Optional[np.ndarray]:
        left, top, width, height = rect
        try:
            h_win_dc = win32gui.GetWindowDC(0)
            src_dc = win32ui.CreateDCFromHandle(h_win_dc)
            mem_dc = src_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(src_dc, width, height)
            mem_dc.SelectObject(bitmap)
            mem_dc.BitBlt((0, 0), (width, height), src_dc, (left, top), win32con.SRCCOPY)
            img = self._bitmap_to_numpy(bitmap)
            src_dc.DeleteDC()
            mem_dc.DeleteDC()
            win32gui.ReleaseDC(0, h_win_dc)
            return img
        except Exception as e:
            logger.warning("GDI BitBlt capture failed: %s", e)
            return None

    @staticmethod
    def _bitmap_to_numpy(bitmap) -> np.ndarray | None:
        try:
            info = bitmap.GetInfo()
            w, h, bpp = info['bmWidth'], info['bmHeight'], info['bmBitsPixel']
            bits = bitmap.GetBitmapBits(True)
            stride = ((w * bpp + 31) // 32) * 4
            arr = np.frombuffer(bits, dtype=np.uint8)
            arr = arr.reshape((h, stride))[:, : (w * (bpp // 8))]
            if bpp == 32:
                img = cv2.cvtColor(arr.reshape((h, w, 4)), cv2.COLOR_BGRA2RGB)
            elif bpp == 24:
                img = cv2.cvtColor(arr.reshape((h, w, 3)), cv2.COLOR_BGR2RGB)
            else:
                raise ValueError(f"Unsupported bpp: {bpp}")
            return img.copy()
        except Exception as e:
            logger.error("Bitmap conversion failed: %s", e)
            return None
        finally:
            if bitmap:
                win32gui.DeleteObject(bitmap.GetHandle())

    def _capture_fullscreen_sync(self) -> CaptureResult:
        try:
            rect = self._get_primary_monitor_rect()
            img = self._capture_bitblt_region_sync(rect)
            if img is not None:
                relative_rect = (0, 0, rect[2], rect[3])
                return CaptureResult(image=img, window_rect=rect, relative_rect=relative_rect, success=True)
            raise Exception("Bitmap conversion failed")
        except Exception as e:
            logger.error("Fullscreen capture failed: %s", e)
            return CaptureResult(success=False, error_message=str(e))

    def _capture_window_sync(self, hwnd: int, sub_rect: tuple[int, int, int, int] | None = None) -> CaptureResult:
        window_rect = None
        try:
            left, top, right, bot = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bot - top
            window_rect = (left, top, width, height)
            c_left, c_top, c_right, c_bot = win32gui.GetClientRect(hwnd)
            client_width = c_right - c_left
            client_height = c_bot - c_top
            if client_width <= 0 or client_height <= 0:
                return CaptureResult(success=False, error_message="Window client size is 0")
            h_win_dc = win32gui.GetWindowDC(hwnd)
            src_dc = win32ui.CreateDCFromHandle(h_win_dc)
            mem_dc = src_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(src_dc, client_width, client_height)
            mem_dc.SelectObject(bitmap)
            result = windll.user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), 3)
            if result != 1:
                logger.warning("PrintWindow returned %s; capture may be partial.", result)
            full_image = self._bitmap_to_numpy(bitmap)
            src_dc.DeleteDC()
            mem_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, h_win_dc)
            if full_image is None:
                raise Exception("Failed to build image from bitmap")
            if sub_rect:
                x, y, w, h = sub_rect
                if x < 0 or y < 0 or w <= 0 or h <= 0 or (x + w) > client_width or (y + h) > client_height:
                    raise ValueError(f"Capture rect {sub_rect} out of client bounds ({client_width}x{client_height})")
                final_image = full_image[y: y + h, x: x + w]
                relative_rect = sub_rect
            else:
                final_image = full_image
                relative_rect = (0, 0, client_width, client_height)
            return CaptureResult(image=final_image, window_rect=window_rect, relative_rect=relative_rect, success=True)
        except Exception as e:
            logger.error("Window capture failed: %s", e, exc_info=False)
            return CaptureResult(success=False, window_rect=window_rect, error_message=str(e))

    def _update_hwnd(self):
        if self.target_title:
            try:
                self.hwnd = win32gui.FindWindow(None, self.target_title)
                if not self.hwnd:
                    logger.trace("Window '%s' not found; will retry when needed.", self.target_title)
            except Exception:
                self.hwnd = None
        else:
            self.hwnd = None

    # =========================================================================
    # Section 4: Sync/Async bridge
    # =========================================================================

    def _get_running_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:
            if self._loop is None or self._loop.is_closed():
                from packages.aura_core.api import service_registry
                scheduler = service_registry.get_service_instance('scheduler')
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

"""Concrete desktop input backends used by the facade."""

from __future__ import annotations

import ctypes
import time
from typing import Any

from .models import CaptureResult, DesktopResult, LocatorResult, WindowContext, error_result, locator_evidence
from .raw_input import RawInputMonitor


class BaseBackend:
    domain = "desktop"
    backend_id = "base"

    def result(self, operation: str, data: dict[str, Any] | None = None, started: float | None = None) -> DesktopResult:
        evidence = list((data or {}).pop("_evidence", []) or [])
        return DesktopResult(
            ok=True,
            backend=self.backend_id,
            domain=self.domain,
            operation=operation,
            data=data or {},
            duration_ms=_elapsed_ms(started),
            evidence=evidence,
        )

    def unsupported(self, operation: str, message: str | None = None) -> DesktopResult:
        return error_result(
            backend=self.backend_id,
            domain=self.domain,
            operation=operation,
            error_code="operation_not_supported",
            message=message or f"{self.backend_id} does not support {operation}.",
        )


class FakeMouseBackend(BaseBackend):
    domain = "mouse"
    backend_id = "fake"

    def __getattr__(self, operation: str):
        def _run(**params: Any) -> DesktopResult:
            started = time.perf_counter()
            return self.result(operation, {"simulated": True, "params": params}, started)

        return _run


class FakeKeyboardBackend(FakeMouseBackend):
    domain = "keyboard"


class FakeCaptureBackend(BaseBackend):
    domain = "capture"
    backend_id = "fake"

    def capture_screen(self, **params: Any) -> DesktopResult:
        started = time.perf_counter()
        width = int(params.get("width") or 100)
        height = int(params.get("height") or 100)
        capture = CaptureResult(
            image_ref=params.get("image") or params.get("image_ref") or "fixture://capture/basic-screen.png",
            image_path=params.get("image_path"),
            width=width,
            height=height,
            region=params.get("region"),
            backend=self.backend_id,
            duration_ms=0,
            quality_flags=["fixture"],
        )
        return self.result(
            "capture_screen",
            {
                "simulated": True,
                "capture": capture.to_dict(),
                "width": width,
                "height": height,
                "params": params,
                "_evidence": [{"kind": "capture", "payload": capture.to_dict()}],
            },
            started,
        )

    def capture_window(self, **params: Any) -> DesktopResult:
        started = time.perf_counter()
        window = _fake_window_context(params)
        capture = CaptureResult(
            image_ref=params.get("image") or "fixture://capture/window.png",
            width=int(params.get("width") or 1280),
            height=int(params.get("height") or 720),
            region=params.get("region"),
            window=window,
            backend=self.backend_id,
            quality_flags=["fixture"],
        )
        return self.result(
            "capture_window",
            {
                "simulated": True,
                "capture": capture.to_dict(),
                "width": capture.width,
                "height": capture.height,
                "params": params,
                "_evidence": [{"kind": "capture", "payload": capture.to_dict()}, {"kind": "window", "payload": window.to_dict()}],
            },
            started,
        )

    def capture_region(self, **params: Any) -> DesktopResult:
        started = time.perf_counter()
        region = params.get("region") or [0, 0, int(params.get("width") or 100), int(params.get("height") or 100)]
        width = int(region[2]) if len(region) >= 4 else 100
        height = int(region[3]) if len(region) >= 4 else 100
        capture = CaptureResult(
            image_ref=params.get("image") or "fixture://capture/region.png",
            width=width,
            height=height,
            region=list(region),
            backend=self.backend_id,
            quality_flags=["fixture"],
        )
        return self.result(
            "capture_region",
            {
                "simulated": True,
                "capture": capture.to_dict(),
                "width": width,
                "height": height,
                "params": params,
                "_evidence": [{"kind": "capture", "payload": capture.to_dict()}],
            },
            started,
        )


class FakeWindowBackend(BaseBackend):
    domain = "window"
    backend_id = "fake"

    def list_windows(self, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        window = _fake_window_context({})
        return self.result("list_windows", {"windows": [window.to_dict()], "_evidence": [{"kind": "window", "payload": window.to_dict()}]}, started)

    def find_window(self, title: str | None = None, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        window = _fake_window_context({"title": title or "Fake Window"})
        return self.result("find_window", {"window": window.to_dict(), "_evidence": [{"kind": "window", "payload": window.to_dict()}]}, started)

    def focus(self, **params: Any) -> DesktopResult:
        started = time.perf_counter()
        return self.result("focus", {"simulated": True, "params": params}, started)

    def get_rect(self, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        return self.result("get_rect", {"rect": [0, 0, 1280, 720]}, started)

    def get_client_rect(self, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        return self.result("get_client_rect", {"rect": [0, 0, 1280, 720]}, started)


class FakeOcrBackend(BaseBackend):
    domain = "ocr"
    backend_id = "fake"

    def recognize(self, **params: Any) -> DesktopResult:
        started = time.perf_counter()
        items = params.get("items")
        if items is None:
            items = [{"text": "Aura", "confidence": 0.99, "bbox": [10, 10, 90, 30]}]
        return self.result(
            "recognize",
            {
                "items": items,
                "simulated": True,
                "params": params,
                "_evidence": [{"kind": "ocr", "payload": {"items": items, "source": params.get("image")}}],
            },
            started,
        )

    def find_text(self, text: str | None = None, **params: Any) -> DesktopResult:
        started = time.perf_counter()
        found = bool(params.get("found", True))
        locator = LocatorResult(
            bbox=[10, 10, 90, 30] if found else None,
            center=[50, 20] if found else None,
            score=0.99 if found else 0.0,
            threshold=float(params.get("threshold") or 0.8),
            source=params.get("image") or "fixture://capture/basic-screen.png",
            method="ocr_text",
            backend=self.backend_id,
            timestamp_ms=int(time.time() * 1000),
            candidates=[{"text": text or "Aura", "confidence": 0.99, "bbox": [10, 10, 90, 30]}],
            error_code=None if found else "locator_not_found",
            message="" if found else f"Text not found: {text}",
        )
        return self.result(
            "find_text",
            {
                "found": found,
                "text": text,
                "locator": locator.to_dict(),
                "simulated": True,
                "params": params,
                "_evidence": [{"kind": "ocr", "payload": {"text": text, "found": found}}, locator_evidence(locator)],
            },
            started,
        )


class GdiCaptureBackend(BaseBackend):
    domain = "capture"
    backend_id = "gdi"

    def capture_screen(self, **params: Any) -> DesktopResult:
        region = params.get("region") or params.get("rect") or _primary_monitor_rect()
        return self.capture_region(region=region, **params)

    def capture_region(self, region: Any = None, **params: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            rect = _normalize_region(region or params.get("rect") or _primary_monitor_rect())
            image = _capture_bitblt_region(rect)
            return _capture_desktop_result(
                backend=self.backend_id,
                operation="capture_region",
                image=image,
                region=rect,
                started=started,
                quality_flags=["gdi"],
            )
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="capture_region",
                error_code="capture_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )

    def capture_window(self, hwnd: int | None = None, title: str | None = None, region: Any = None, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            target_hwnd = _resolve_hwnd(hwnd=hwnd, title=title)
            if not target_hwnd:
                raise RuntimeError(f"Window not found: {title or hwnd}")
            context = _window_context(target_hwnd, backend="win32")
            rect = context.client_rect or context.screen_rect
            if not rect:
                raise RuntimeError("Window rect is unavailable.")
            image = _capture_bitblt_region(rect)
            if region:
                image, rect = _crop_image_to_region(image, _normalize_region(region), rect)
            return _capture_desktop_result(
                backend=self.backend_id,
                operation="capture_window",
                image=image,
                region=rect,
                started=started,
                window=context,
                quality_flags=["gdi"],
            )
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="capture_window",
                error_code="capture_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )


class MssCaptureBackend(BaseBackend):
    domain = "capture"
    backend_id = "mss"

    def capture_screen(self, **params: Any) -> DesktopResult:
        region = params.get("region") or params.get("rect") or _primary_monitor_rect()
        return self.capture_region(region=region, **params)

    def capture_region(self, region: Any = None, **params: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            import cv2
            import mss
            import numpy as np

            rect = _normalize_region(region or params.get("rect") or _primary_monitor_rect())
            left, top, width, height = rect
            with mss.mss() as sct:
                shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
            image = cv2.cvtColor(np.array(shot, dtype=np.uint8), cv2.COLOR_BGRA2RGB)
            return _capture_desktop_result(
                backend=self.backend_id,
                operation="capture_region",
                image=image,
                region=rect,
                started=started,
                quality_flags=["mss"],
            )
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="capture_region",
                error_code="capture_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )

    def capture_window(self, hwnd: int | None = None, title: str | None = None, region: Any = None, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            target_hwnd = _resolve_hwnd(hwnd=hwnd, title=title)
            if not target_hwnd:
                raise RuntimeError(f"Window not found: {title or hwnd}")
            context = _window_context(target_hwnd, backend="win32")
            rect = context.client_rect or context.screen_rect
            if not rect:
                raise RuntimeError("Window rect is unavailable.")
            result = self.capture_region(region=rect)
            result.operation = "capture_window"
            result.data["window"] = context.to_dict()
            result.evidence.append({"kind": "window", "payload": context.to_dict()})
            if region and result.data.get("_image") is not None:
                image, cropped_rect = _crop_image_to_region(result.data["_image"], _normalize_region(region), rect)
                result.data["_image"] = image
                result.data["capture"]["region"] = cropped_rect
            result.duration_ms = _elapsed_ms(started)
            return result
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="capture_window",
                error_code="capture_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )


class DxgiCaptureBackend(BaseBackend):
    domain = "capture"
    backend_id = "dxgi"

    def __init__(self) -> None:
        self._camera = None

    def capture_screen(self, **params: Any) -> DesktopResult:
        region = params.get("region") or params.get("rect") or _primary_monitor_rect()
        return self.capture_region(region=region, **params)

    def capture_region(self, region: Any = None, **params: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            import cv2
            import dxcam

            rect = _normalize_region(region or params.get("rect") or _primary_monitor_rect())
            if self._camera is None:
                self._camera = dxcam.create()
            left, top, width, height = rect
            frame = self._camera.grab(region=(left, top, left + width, top + height))
            if frame is None:
                raise RuntimeError("DXGI returned no frame.")
            image = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB) if frame.shape[2] == 4 else cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return _capture_desktop_result(
                backend=self.backend_id,
                operation="capture_region",
                image=image,
                region=rect,
                started=started,
                quality_flags=["dxgi"],
            )
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="capture_region",
                error_code="capture_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )


class PrintWindowCaptureBackend(BaseBackend):
    domain = "capture"
    backend_id = "printwindow"

    def capture_window(self, hwnd: int | None = None, title: str | None = None, region: Any = None, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            target_hwnd = _resolve_hwnd(hwnd=hwnd, title=title)
            if not target_hwnd:
                raise RuntimeError(f"Window not found: {title or hwnd}")
            context = _window_context(target_hwnd, backend="win32")
            image = _capture_printwindow(target_hwnd)
            rect = context.client_rect or [0, 0, int(image.shape[1]), int(image.shape[0])]
            if region:
                image, rect = _crop_image_to_region(image, _normalize_region(region), rect)
            return _capture_desktop_result(
                backend=self.backend_id,
                operation="capture_window",
                image=image,
                region=rect,
                started=started,
                window=context,
                quality_flags=["printwindow"],
            )
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="capture_window",
                error_code="capture_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )


class Win32WindowBackend(BaseBackend):
    domain = "window"
    backend_id = "win32"

    def list_windows(self, visible_only: bool = True, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            import win32gui

            rows: list[dict[str, Any]] = []

            def _callback(hwnd: int, __: Any) -> None:
                if visible_only and not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd) or ""
                if not title and visible_only:
                    return
                rows.append(_window_context(hwnd, backend=self.backend_id).to_dict())

            win32gui.EnumWindows(_callback, None)
            return self.result("list_windows", {"windows": rows, "_evidence": [{"kind": "window", "payload": {"count": len(rows)}}]}, started)
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="list_windows",
                error_code="window_query_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )

    def find_window(self, title: str | None = None, hwnd: int | None = None, title_contains: str | None = None, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            target_hwnd = _resolve_hwnd(hwnd=hwnd, title=title, title_contains=title_contains)
            if not target_hwnd:
                return error_result(
                    backend=self.backend_id,
                    domain=self.domain,
                    operation="find_window",
                    error_code="window_not_found",
                    message=f"Window not found: {title or title_contains or hwnd}",
                    duration_ms=_elapsed_ms(started),
                )
            window = _window_context(target_hwnd, backend=self.backend_id)
            return self.result("find_window", {"window": window.to_dict(), "_evidence": [{"kind": "window", "payload": window.to_dict()}]}, started)
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="find_window",
                error_code="window_query_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )

    def focus(self, hwnd: int | None = None, title: str | None = None, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            import win32con
            import win32gui

            target_hwnd = _resolve_hwnd(hwnd=hwnd, title=title)
            if not target_hwnd:
                raise RuntimeError(f"Window not found: {title or hwnd}")
            if win32gui.IsIconic(target_hwnd):
                win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(target_hwnd)
            window = _window_context(target_hwnd, backend=self.backend_id)
            return self.result("focus", {"window": window.to_dict(), "_evidence": [{"kind": "window", "payload": window.to_dict()}]}, started)
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="focus",
                error_code="window_focus_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )

    def get_rect(self, hwnd: int | None = None, title: str | None = None, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            target_hwnd = _resolve_hwnd(hwnd=hwnd, title=title)
            if not target_hwnd:
                raise RuntimeError(f"Window not found: {title or hwnd}")
            window = _window_context(target_hwnd, backend=self.backend_id)
            return self.result("get_rect", {"rect": window.screen_rect, "window": window.to_dict()}, started)
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="get_rect",
                error_code="window_query_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )

    def get_client_rect(self, hwnd: int | None = None, title: str | None = None, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            target_hwnd = _resolve_hwnd(hwnd=hwnd, title=title)
            if not target_hwnd:
                raise RuntimeError(f"Window not found: {title or hwnd}")
            window = _window_context(target_hwnd, backend=self.backend_id)
            return self.result("get_client_rect", {"rect": window.client_rect, "window": window.to_dict()}, started)
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="get_client_rect",
                error_code="window_query_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )


class UiaWindowBackend(BaseBackend):
    domain = "window"
    backend_id = "uia"

    def __init__(self) -> None:
        self.message = "UIA window backend is available for capability discovery; operation adapter is not enabled in V7 closure."

    def __getattr__(self, operation: str):
        def _run(**_: Any) -> DesktopResult:
            return self.unsupported(operation, self.message)

        return _run


class UiaMouseBackend(BaseBackend):
    domain = "mouse"
    backend_id = "uia"

    def __init__(self) -> None:
        self.message = "UIA mouse backend is semantic-only and requires a control target adapter."

    def __getattr__(self, operation: str):
        def _run(**_: Any) -> DesktopResult:
            return self.unsupported(operation, self.message)

        return _run


class UiaKeyboardBackend(BaseBackend):
    domain = "keyboard"
    backend_id = "uia"

    def __init__(self) -> None:
        self.message = "UIA keyboard backend is semantic-only and requires a control target adapter."

    def __getattr__(self, operation: str):
        def _run(**_: Any) -> DesktopResult:
            return self.unsupported(operation, self.message)

        return _run


class Win32PostMessageMouseBackend(BaseBackend):
    domain = "mouse"
    backend_id = "win32_postmessage"

    def click(self, hwnd: int | None = None, title: str | None = None, x: int = 0, y: int = 0, button: str = "left", **_: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            target_hwnd = _resolve_hwnd(hwnd=hwnd, title=title)
            if not target_hwnd:
                raise RuntimeError(f"Window not found: {title or hwnd}")
            self.down(hwnd=target_hwnd, x=x, y=y, button=button)
            self.up(hwnd=target_hwnd, x=x, y=y, button=button)
            return self.result("click", {"hwnd": target_hwnd, "x": x, "y": y, "button": button}, started)
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="click",
                error_code="postmessage_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )

    def down(self, hwnd: int | None = None, title: str | None = None, x: int = 0, y: int = 0, button: str = "left", **_: Any) -> DesktopResult:
        return self._button("down", hwnd=hwnd, title=title, x=x, y=y, button=button)

    def up(self, hwnd: int | None = None, title: str | None = None, x: int = 0, y: int = 0, button: str = "left", **_: Any) -> DesktopResult:
        return self._button("up", hwnd=hwnd, title=title, x=x, y=y, button=button)

    def scroll(self, hwnd: int | None = None, title: str | None = None, x: int = 0, y: int = 0, amount: int = 1, direction: str = "down", **_: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            import win32con
            import win32gui

            target_hwnd = _resolve_hwnd(hwnd=hwnd, title=title)
            if not target_hwnd:
                raise RuntimeError(f"Window not found: {title or hwnd}")
            delta = -120 if direction == "down" else 120
            lparam = _make_lparam(x, y)
            for _index in range(abs(int(amount))):
                win32gui.PostMessage(target_hwnd, win32con.WM_MOUSEWHEEL, delta << 16, lparam)
            return self.result("scroll", {"hwnd": target_hwnd, "x": x, "y": y, "amount": amount, "direction": direction}, started)
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="scroll",
                error_code="postmessage_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )

    def _button(self, operation: str, *, hwnd: int | None, title: str | None, x: int, y: int, button: str) -> DesktopResult:
        started = time.perf_counter()
        try:
            import win32con
            import win32gui

            target_hwnd = _resolve_hwnd(hwnd=hwnd, title=title)
            if not target_hwnd:
                raise RuntimeError(f"Window not found: {title or hwnd}")
            message_map = {
                ("left", "down"): win32con.WM_LBUTTONDOWN,
                ("left", "up"): win32con.WM_LBUTTONUP,
                ("right", "down"): win32con.WM_RBUTTONDOWN,
                ("right", "up"): win32con.WM_RBUTTONUP,
                ("middle", "down"): win32con.WM_MBUTTONDOWN,
                ("middle", "up"): win32con.WM_MBUTTONUP,
            }
            message = message_map[(str(button).lower(), operation)]
            win32gui.PostMessage(target_hwnd, message, 0, _make_lparam(x, y))
            return self.result(operation, {"hwnd": target_hwnd, "x": x, "y": y, "button": button}, started)
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation=operation,
                error_code="postmessage_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )


class Win32PostMessageKeyboardBackend(BaseBackend):
    domain = "keyboard"
    backend_id = "win32_postmessage"

    def key_down(self, hwnd: int | None = None, title: str | None = None, key: str = "", **_: Any) -> DesktopResult:
        return self._key("key_down", hwnd=hwnd, title=title, key=key, release=False)

    def key_up(self, hwnd: int | None = None, title: str | None = None, key: str = "", **_: Any) -> DesktopResult:
        return self._key("key_up", hwnd=hwnd, title=title, key=key, release=True)

    def press(self, hwnd: int | None = None, title: str | None = None, key: str = "", presses: int = 1, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        for _index in range(int(presses)):
            self.key_down(hwnd=hwnd, title=title, key=key)
            self.key_up(hwnd=hwnd, title=title, key=key)
        return self.result("press", {"key": key, "presses": presses}, started)

    def type_text(self, hwnd: int | None = None, title: str | None = None, text: str = "", **_: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            import win32con
            import win32gui

            target_hwnd = _resolve_hwnd(hwnd=hwnd, title=title)
            if not target_hwnd:
                raise RuntimeError(f"Window not found: {title or hwnd}")
            for char in str(text):
                win32gui.PostMessage(target_hwnd, win32con.WM_CHAR, ord(char), 0)
            return self.result("type_text", {"hwnd": target_hwnd, "chars": len(str(text))}, started)
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="type_text",
                error_code="postmessage_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )

    def _key(self, operation: str, *, hwnd: int | None, title: str | None, key: str, release: bool) -> DesktopResult:
        started = time.perf_counter()
        try:
            import win32con
            import win32gui

            target_hwnd = _resolve_hwnd(hwnd=hwnd, title=title)
            if not target_hwnd:
                raise RuntimeError(f"Window not found: {title or hwnd}")
            win32gui.PostMessage(target_hwnd, win32con.WM_KEYUP if release else win32con.WM_KEYDOWN, _vk_from_key(key), 0)
            return self.result(operation, {"hwnd": target_hwnd, "key": key}, started)
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation=operation,
                error_code="postmessage_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )


class PaddleOcrBackend(BaseBackend):
    domain = "ocr"
    backend_id = "paddleocr"

    def __init__(self) -> None:
        self._engine = None

    def recognize(self, image: Any = None, **params: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            items = self._recognize_items(image or params.get("image_path"))
            return self.result(
                "recognize",
                {
                    "items": items,
                    "_evidence": [{"kind": "ocr", "payload": {"items": items, "source": params.get("image") or params.get("image_path")}}],
                },
                started,
            )
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="recognize",
                error_code="ocr_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )

    def find_text(self, text: str | None = None, match_mode: str = "contains", threshold: float = 0.8, image: Any = None, **params: Any) -> DesktopResult:
        started = time.perf_counter()
        result = self.recognize(image=image or params.get("image_path"), **params)
        if not result.ok:
            result.operation = "find_text"
            return result
        items = result.data.get("items") or []
        candidates = []
        for item in items:
            candidate_text = str(item.get("text") or "")
            matched = candidate_text == text if match_mode == "exact" else str(text or "") in candidate_text
            candidate = dict(item)
            candidate["matched"] = matched
            candidates.append(candidate)
            if matched and float(item.get("confidence") or 0) >= threshold:
                locator = LocatorResult(
                    bbox=item.get("bbox"),
                    center=_center_from_bbox(item.get("bbox")),
                    score=float(item.get("confidence") or 0),
                    threshold=float(threshold),
                    source=params.get("image") or params.get("image_path"),
                    method="ocr_text",
                    backend=self.backend_id,
                    timestamp_ms=int(time.time() * 1000),
                    candidates=candidates,
                )
                return self.result(
                    "find_text",
                    {"found": True, "text": text, "locator": locator.to_dict(), "_evidence": [locator_evidence(locator)]},
                    started,
                )
        locator = LocatorResult(
            bbox=None,
            center=None,
            score=max([float(item.get("confidence") or 0) for item in candidates], default=0.0),
            threshold=float(threshold),
            source=params.get("image") or params.get("image_path"),
            method="ocr_text",
            backend=self.backend_id,
            timestamp_ms=int(time.time() * 1000),
            candidates=candidates,
            error_code="locator_not_found",
            message=f"Text not found: {text}",
        )
        return self.result(
            "find_text",
            {"found": False, "text": text, "locator": locator.to_dict(), "_evidence": [locator_evidence(locator)]},
            started,
        )

    def _recognize_items(self, image: Any) -> list[dict[str, Any]]:
        import cv2
        import numpy as np
        from paddleocr import PaddleOCR

        if self._engine is None:
            self._engine = PaddleOCR(lang="ch")
        if isinstance(image, str):
            source = cv2.imread(image, cv2.IMREAD_COLOR)
            if source is None:
                raise FileNotFoundError(image)
        elif image is None:
            raise ValueError("PaddleOCR backend requires image or image_path.")
        else:
            source = image
        if isinstance(source, np.ndarray) and source.ndim == 3:
            source = cv2.cvtColor(source, cv2.COLOR_RGB2BGR)
        raw = self._engine.predict(source)
        if not raw:
            return []
        data = raw[0]
        texts = data.get("rec_texts", []) if isinstance(data, dict) else []
        scores = data.get("rec_scores", []) if isinstance(data, dict) else []
        boxes = data.get("rec_polys", []) if isinstance(data, dict) else []
        items = []
        for text, score, box in zip(texts, scores, boxes):
            bbox = _bbox_from_poly(box)
            items.append({"text": text, "confidence": float(score), "bbox": bbox})
        return items


class Win32MouseEventBackend(BaseBackend):
    domain = "mouse"
    backend_id = "win32_mouse_event"

    def __init__(self) -> None:
        import win32api
        import win32con

        self.win32api = win32api
        self.win32con = win32con

    def move(self, x: int, y: int, duration: float = 0.0, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        self.win32api.SetCursorPos((int(x), int(y)))
        if duration:
            time.sleep(float(duration))
        return self.result("move", {"x": int(x), "y": int(y)}, started)

    def down(self, button: str = "left", **_: Any) -> DesktopResult:
        started = time.perf_counter()
        self.win32api.mouse_event(_mouse_event_flag(self.win32con, button, True), 0, 0, 0, 0)
        return self.result("down", {"button": button}, started)

    def up(self, button: str = "left", **_: Any) -> DesktopResult:
        started = time.perf_counter()
        self.win32api.mouse_event(_mouse_event_flag(self.win32con, button, False), 0, 0, 0, 0)
        return self.result("up", {"button": button}, started)

    def click(self, x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1,
              interval: float = 0.1, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        if x is not None and y is not None:
            self.move(int(x), int(y))
        for index in range(int(clicks)):
            self.down(button)
            self.up(button)
            if index < clicks - 1:
                time.sleep(float(interval))
        return self.result("click", {"x": x, "y": y, "button": button, "clicks": clicks}, started)

    def double_click(self, x: int | None = None, y: int | None = None, button: str = "left", **kwargs: Any) -> DesktopResult:
        return self.click(x=x, y=y, button=button, clicks=2, interval=kwargs.get("interval", 0.05))

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, button: str = "left",
             duration: float = 0.0, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        self.move(start_x, start_y)
        self.down(button)
        self.move(end_x, end_y, duration=duration)
        self.up(button)
        return self.result("drag", {"start": [start_x, start_y], "end": [end_x, end_y], "button": button}, started)

    def scroll(self, amount: int, direction: str = "down", **_: Any) -> DesktopResult:
        started = time.perf_counter()
        delta = -120 if direction == "down" else 120
        for _index in range(abs(int(amount))):
            self.win32api.mouse_event(self.win32con.MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
        return self.result("scroll", {"amount": amount, "direction": direction}, started)


class Win32KeybdEventBackend(BaseBackend):
    domain = "keyboard"
    backend_id = "win32_keybd_event"

    def __init__(self) -> None:
        import win32api
        import win32con

        self.win32api = win32api
        self.win32con = win32con

    def key_down(self, key: str, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        vk = _vk_code(self.win32api, key)
        self.win32api.keybd_event(vk, self.win32api.MapVirtualKey(vk, 0), 0, 0)
        return self.result("key_down", {"key": key}, started)

    def key_up(self, key: str, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        vk = _vk_code(self.win32api, key)
        self.win32api.keybd_event(vk, self.win32api.MapVirtualKey(vk, 0), self.win32con.KEYEVENTF_KEYUP, 0)
        return self.result("key_up", {"key": key}, started)

    def press(self, key: str, presses: int = 1, interval: float = 0.1, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        for index in range(int(presses)):
            self.key_down(key)
            self.key_up(key)
            if index < presses - 1:
                time.sleep(float(interval))
        return self.result("press", {"key": key, "presses": presses}, started)


class Win32SendInputBackend(BaseBackend):
    backend_id = "win32_sendinput"

    def _send(self, inputs: Any, count: int) -> None:
        sent = ctypes.windll.user32.SendInput(count, ctypes.byref(inputs), ctypes.sizeof(INPUT))
        if sent != count:
            raise OSError(f"SendInput sent {sent}/{count} events.")


class Win32SendInputMouseBackend(Win32SendInputBackend):
    domain = "mouse"

    def move(self, x: int | None = None, y: int | None = None, dx: int | None = None, dy: int | None = None,
             absolute: bool = True, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        flags = 0x0001
        mx = int(dx or 0)
        my = int(dy or 0)
        if absolute:
            flags |= 0x8000
            mx, my = _normalize_absolute_coords(int(x or 0), int(y or 0))
        event = INPUT(type=0, union=INPUTUNION(mi=MOUSEINPUT(mx, my, 0, flags, 0, None)))
        self._send(event, 1)
        return self.result("move", {"x": x, "y": y, "dx": dx, "dy": dy, "absolute": absolute}, started)

    def down(self, button: str = "left", **_: Any) -> DesktopResult:
        return self._button("down", button, True)

    def up(self, button: str = "left", **_: Any) -> DesktopResult:
        return self._button("up", button, False)

    def click(self, x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1,
              interval: float = 0.1, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        if x is not None and y is not None:
            self.move(x=x, y=y, absolute=True)
        for index in range(int(clicks)):
            self.down(button)
            self.up(button)
            if index < clicks - 1:
                time.sleep(float(interval))
        return self.result("click", {"x": x, "y": y, "button": button, "clicks": clicks}, started)

    def double_click(self, x: int | None = None, y: int | None = None, button: str = "left", **kwargs: Any) -> DesktopResult:
        return self.click(x=x, y=y, button=button, clicks=2, interval=kwargs.get("interval", 0.05))

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, button: str = "left",
             duration: float = 0.0, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        self.move(x=start_x, y=start_y, absolute=True)
        self.down(button)
        self.move(x=end_x, y=end_y, absolute=True)
        if duration:
            time.sleep(float(duration))
        self.up(button)
        return self.result("drag", {"start": [start_x, start_y], "end": [end_x, end_y], "button": button}, started)

    def scroll(self, amount: int, direction: str = "down", **_: Any) -> DesktopResult:
        started = time.perf_counter()
        delta = -120 if direction == "down" else 120
        event = INPUT(type=0, union=INPUTUNION(mi=MOUSEINPUT(0, 0, delta * abs(int(amount)), 0x0800, 0, None)))
        self._send(event, 1)
        return self.result("scroll", {"amount": amount, "direction": direction}, started)

    def _button(self, operation: str, button: str, is_down: bool) -> DesktopResult:
        started = time.perf_counter()
        flags = _sendinput_button_flag(button, is_down)
        event = INPUT(type=0, union=INPUTUNION(mi=MOUSEINPUT(0, 0, 0, flags, 0, None)))
        self._send(event, 1)
        return self.result(operation, {"button": button}, started)


class Win32SendInputKeyboardBackend(Win32SendInputBackend):
    domain = "keyboard"

    def key_down(self, key: str, **_: Any) -> DesktopResult:
        return self._key("key_down", key, False)

    def key_up(self, key: str, **_: Any) -> DesktopResult:
        return self._key("key_up", key, True)

    def press(self, key: str, presses: int = 1, interval: float = 0.1, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        for index in range(int(presses)):
            self.key_down(key)
            self.key_up(key)
            if index < presses - 1:
                time.sleep(float(interval))
        return self.result("press", {"key": key, "presses": presses}, started)

    def hotkey(self, keys: list[str] | tuple[str, ...], **_: Any) -> DesktopResult:
        started = time.perf_counter()
        for key in keys:
            self.key_down(str(key))
        for key in reversed(keys):
            self.key_up(str(key))
        return self.result("hotkey", {"keys": list(keys)}, started)

    def type_text(self, text: str, interval: float = 0.01, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        for index, char in enumerate(str(text)):
            self.press(char)
            if interval and index < len(str(text)) - 1:
                time.sleep(float(interval))
        return self.result("type_text", {"chars": len(str(text))}, started)

    def _key(self, operation: str, key: str, release: bool) -> DesktopResult:
        started = time.perf_counter()
        vk = _vk_from_key(key)
        flags = 0x0002 if release else 0
        event = INPUT(type=1, union=INPUTUNION(ki=KEYBDINPUT(vk, 0, flags, 0, None)))
        self._send(event, 1)
        return self.result(operation, {"key": key}, started)


class UnsupportedBackend(BaseBackend):
    def __init__(self, domain: str, backend_id: str, message: str) -> None:
        self.domain = domain
        self.backend_id = backend_id
        self.message = message

    def __getattr__(self, operation: str):
        def _run(**_: Any) -> DesktopResult:
            return self.unsupported(operation, self.message)

        return _run


class RawInputBackend(UnsupportedBackend):
    def __init__(self) -> None:
        super().__init__(
            "mouse",
            "raw_input",
            "Raw Input is an event monitor and does not inject mouse events.",
        )
        self.monitor = RawInputMonitor()


class ClipboardKeyboardBackend(BaseBackend):
    domain = "keyboard"
    backend_id = "clipboard_paste"

    def paste_text(self, text: str, **_: Any) -> DesktopResult:
        started = time.perf_counter()
        try:
            import win32clipboard
            import win32con

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, str(text))
            finally:
                win32clipboard.CloseClipboard()
        except Exception as exc:  # noqa: BLE001
            return error_result(
                backend=self.backend_id,
                domain=self.domain,
                operation="paste_text",
                error_code="clipboard_write_failed",
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )
        return self.result("paste_text", {"chars": len(str(text))}, started)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", INPUTUNION)]


def _capture_desktop_result(
    *,
    backend: str,
    operation: str,
    image: Any,
    region: list[int],
    started: float,
    window: WindowContext | None = None,
    quality_flags: list[str] | None = None,
) -> DesktopResult:
    height = int(getattr(image, "shape", [0, 0])[0])
    width = int(getattr(image, "shape", [0, 0])[1])
    capture = CaptureResult(
        width=width,
        height=height,
        region=list(region),
        window=window,
        backend=backend,
        duration_ms=_elapsed_ms(started),
        quality_flags=quality_flags or [],
    )
    evidence = [{"kind": "capture", "payload": capture.to_dict()}]
    if window is not None:
        evidence.append({"kind": "window", "payload": window.to_dict()})
    return DesktopResult(
        ok=True,
        backend=backend,
        domain="capture",
        operation=operation,
        data={
            "_image": image,
            "capture": capture.to_dict(),
            "width": width,
            "height": height,
            "region": list(region),
        },
        duration_ms=_elapsed_ms(started),
        evidence=evidence,
    )


def _normalize_region(region: Any) -> list[int]:
    if isinstance(region, dict):
        return [
            int(region.get("left", region.get("x", 0))),
            int(region.get("top", region.get("y", 0))),
            int(region.get("width", region.get("w", 0))),
            int(region.get("height", region.get("h", 0))),
        ]
    if not isinstance(region, (list, tuple)) or len(region) < 4:
        raise ValueError(f"Invalid region: {region!r}")
    left, top, width, height = region[:4]
    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0:
        raise ValueError(f"Region width/height must be positive: {region!r}")
    return [int(left), int(top), width, height]


def _primary_monitor_rect() -> list[int]:
    width = int(ctypes.windll.user32.GetSystemMetrics(0))
    height = int(ctypes.windll.user32.GetSystemMetrics(1))
    if width <= 0 or height <= 0:
        raise RuntimeError("Primary monitor size is unavailable.")
    return [0, 0, width, height]


def _capture_bitblt_region(rect: list[int]) -> Any:
    import win32con
    import win32gui
    import win32ui

    left, top, width, height = rect
    h_win_dc = None
    src_dc = None
    mem_dc = None
    bitmap = None
    try:
        h_win_dc = win32gui.GetWindowDC(0)
        src_dc = win32ui.CreateDCFromHandle(h_win_dc)
        mem_dc = src_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(src_dc, width, height)
        mem_dc.SelectObject(bitmap)
        mem_dc.BitBlt((0, 0), (width, height), src_dc, (left, top), win32con.SRCCOPY)
        return _bitmap_to_numpy(bitmap)
    finally:
        if src_dc is not None:
            with _suppress_exceptions():
                src_dc.DeleteDC()
        if mem_dc is not None:
            with _suppress_exceptions():
                mem_dc.DeleteDC()
        if h_win_dc is not None:
            with _suppress_exceptions():
                win32gui.ReleaseDC(0, h_win_dc)
        if bitmap is not None:
            with _suppress_exceptions():
                win32gui.DeleteObject(bitmap.GetHandle())


def _capture_printwindow(hwnd: int) -> Any:
    import win32gui
    import win32ui

    client_rect = _client_rect_to_screen(hwnd)
    _left, _top, width, height = client_rect
    h_win_dc = None
    src_dc = None
    mem_dc = None
    bitmap = None
    try:
        h_win_dc = win32gui.GetWindowDC(hwnd)
        src_dc = win32ui.CreateDCFromHandle(h_win_dc)
        mem_dc = src_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(src_dc, width, height)
        mem_dc.SelectObject(bitmap)
        result = ctypes.windll.user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), 3)
        if result != 1:
            # Some GPU-backed windows still return partial content; callers can
            # inspect quality flags/evidence to decide whether to accept it.
            pass
        return _bitmap_to_numpy(bitmap)
    finally:
        if src_dc is not None:
            with _suppress_exceptions():
                src_dc.DeleteDC()
        if mem_dc is not None:
            with _suppress_exceptions():
                mem_dc.DeleteDC()
        if h_win_dc is not None:
            with _suppress_exceptions():
                win32gui.ReleaseDC(hwnd, h_win_dc)
        if bitmap is not None:
            with _suppress_exceptions():
                win32gui.DeleteObject(bitmap.GetHandle())


def _bitmap_to_numpy(bitmap: Any) -> Any:
    import cv2
    import numpy as np

    info = bitmap.GetInfo()
    width, height, bpp = info["bmWidth"], info["bmHeight"], info["bmBitsPixel"]
    bits = bitmap.GetBitmapBits(True)
    stride = ((width * bpp + 31) // 32) * 4
    arr = np.frombuffer(bits, dtype=np.uint8).reshape((height, stride))[:, : (width * (bpp // 8))]
    if bpp == 32:
        return cv2.cvtColor(arr.reshape((height, width, 4)), cv2.COLOR_BGRA2RGB).copy()
    if bpp == 24:
        return cv2.cvtColor(arr.reshape((height, width, 3)), cv2.COLOR_BGR2RGB).copy()
    raise ValueError(f"Unsupported bitmap bpp: {bpp}")


def _resolve_hwnd(hwnd: int | None = None, title: str | None = None, title_contains: str | None = None) -> int | None:
    import win32gui

    if hwnd:
        hwnd_int = int(hwnd)
        return hwnd_int if win32gui.IsWindow(hwnd_int) else None
    if title:
        found = win32gui.FindWindow(None, title)
        if found:
            return int(found)
    if title_contains:
        needle = str(title_contains).lower()
        match: list[int] = []

        def _callback(candidate: int, __: Any) -> None:
            if match:
                return
            text = (win32gui.GetWindowText(candidate) or "").lower()
            if needle in text:
                match.append(int(candidate))

        win32gui.EnumWindows(_callback, None)
        return match[0] if match else None
    return None


def _window_context(hwnd: int, *, backend: str) -> WindowContext:
    import win32gui

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    client_rect = _client_rect_to_screen(hwnd)
    return WindowContext(
        window_id=str(hwnd),
        title=win32gui.GetWindowText(hwnd) or "",
        class_name=win32gui.GetClassName(hwnd) or "",
        hwnd=int(hwnd),
        screen_rect=[int(left), int(top), int(right - left), int(bottom - top)],
        client_rect=client_rect,
        dpi_scale=1.0,
        coordinate_origin="client",
        backend=backend,
        foreground=win32gui.GetForegroundWindow() == hwnd,
        minimized=bool(win32gui.IsIconic(hwnd)),
    )


def _client_rect_to_screen(hwnd: int) -> list[int]:
    import win32gui

    x, y = win32gui.ClientToScreen(hwnd, (0, 0))
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    width = int(right - left)
    height = int(bottom - top)
    if width <= 0 or height <= 0:
        raise RuntimeError("Window client rect is empty.")
    return [int(x), int(y), width, height]


def _crop_image_to_region(image: Any, region: list[int], base_rect: list[int]) -> tuple[Any, list[int]]:
    _base_left, _base_top, base_width, base_height = base_rect
    x, y, width, height = region
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > base_width or y + height > base_height:
        raise ValueError(f"Region {region} is outside base rect {base_rect}.")
    return image[y : y + height, x : x + width], [x, y, width, height]


def _make_lparam(x: int, y: int) -> int:
    return (int(y) << 16) | (int(x) & 0xFFFF)


def _bbox_from_poly(poly: Any) -> list[float] | None:
    try:
        import numpy as np

        arr = np.asarray(poly)
        if arr.ndim != 2 or arr.shape[0] < 1:
            return None
        x0 = float(arr[:, 0].min())
        y0 = float(arr[:, 1].min())
        x1 = float(arr[:, 0].max())
        y1 = float(arr[:, 1].max())
        return [x0, y0, x1 - x0, y1 - y0]
    except Exception:
        return None


def _center_from_bbox(bbox: Any) -> list[float] | None:
    if not bbox or len(bbox) < 4:
        return None
    return [float(bbox[0]) + float(bbox[2]) / 2.0, float(bbox[1]) + float(bbox[3]) / 2.0]


class _suppress_exceptions:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_exc: Any) -> bool:
        return True


def _elapsed_ms(started: float | None) -> int:
    if started is None:
        return 0
    return int((time.perf_counter() - started) * 1000)


def _fake_window_context(params: dict[str, Any]) -> WindowContext:
    return WindowContext(
        window_id=str(params.get("window_id") or "fake-window"),
        title=str(params.get("title") or "Fake Window"),
        class_name=str(params.get("class_name") or "AuraFakeWindow"),
        hwnd=int(params.get("hwnd") or 1),
        screen_rect=list(params.get("screen_rect") or [0, 0, 1280, 720]),
        client_rect=list(params.get("client_rect") or [0, 0, 1280, 720]),
        dpi_scale=float(params.get("dpi_scale") or 1.0),
        coordinate_origin=str(params.get("coordinate_origin") or "client"),
        backend="fake",
        foreground=bool(params.get("foreground", True)),
        minimized=bool(params.get("minimized", False)),
    )


def _mouse_event_flag(win32con: Any, button: str, is_down: bool) -> int:
    button = str(button).lower()
    if button == "left":
        return win32con.MOUSEEVENTF_LEFTDOWN if is_down else win32con.MOUSEEVENTF_LEFTUP
    if button == "right":
        return win32con.MOUSEEVENTF_RIGHTDOWN if is_down else win32con.MOUSEEVENTF_RIGHTUP
    if button == "middle":
        return win32con.MOUSEEVENTF_MIDDLEDOWN if is_down else win32con.MOUSEEVENTF_MIDDLEUP
    raise ValueError(f"Unsupported mouse button: {button}")


def _sendinput_button_flag(button: str, is_down: bool) -> int:
    button = str(button).lower()
    flags = {
        ("left", True): 0x0002,
        ("left", False): 0x0004,
        ("right", True): 0x0008,
        ("right", False): 0x0010,
        ("middle", True): 0x0020,
        ("middle", False): 0x0040,
    }
    try:
        return flags[(button, is_down)]
    except KeyError as exc:
        raise ValueError(f"Unsupported mouse button: {button}") from exc


def _normalize_absolute_coords(x: int, y: int) -> tuple[int, int]:
    width = max(int(ctypes.windll.user32.GetSystemMetrics(0)), 1)
    height = max(int(ctypes.windll.user32.GetSystemMetrics(1)), 1)
    return int(x * 65535 / (width - 1)), int(y * 65535 / (height - 1))


def _vk_code(win32api: Any, key: str) -> int:
    return _vk_from_key(key, vk_key_scan=win32api.VkKeyScan)


def _vk_from_key(key: str, vk_key_scan: Any | None = None) -> int:
    mapping = {
        "esc": 0x1B, "enter": 0x0D, "tab": 0x09, "space": 0x20,
        "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
        "backspace": 0x08,
    }
    value = str(key).lower()
    if value in mapping:
        return mapping[value]
    if len(value) == 1:
        if vk_key_scan:
            return vk_key_scan(value) & 0xFF
        return ord(value.upper())
    if value.startswith("f") and value[1:].isdigit():
        number = int(value[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    raise ValueError(f"Unknown key: {key}")

# src/hardware/controller_service.py

from __future__ import annotations

import asyncio
import sys
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from packages.aura_core.api import service_info
from packages.aura_core.observability.logging.core_logger import logger
from ..desktop_runtime import DesktopFacade


KEY_MAP = {
    "esc": 0x1B,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
    "`": 0xC0,
    "1": 0x31,
    "2": 0x32,
    "3": 0x33,
    "4": 0x34,
    "5": 0x35,
    "6": 0x36,
    "7": 0x37,
    "8": 0x38,
    "9": 0x39,
    "0": 0x30,
    "-": 0xBD,
    "=": 0xBB,
    "backspace": 0x08,
    "tab": 0x09,
    "q": 0x51,
    "w": 0x57,
    "e": 0x45,
    "r": 0x52,
    "t": 0x54,
    "y": 0x59,
    "u": 0x55,
    "i": 0x49,
    "o": 0x4F,
    "p": 0x50,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    "capslock": 0x14,
    "a": 0x41,
    "s": 0x53,
    "d": 0x44,
    "f": 0x46,
    "g": 0x47,
    "h": 0x48,
    "j": 0x4A,
    "k": 0x4B,
    "l": 0x4C,
    ";": 0xBA,
    "'": 0xDE,
    "enter": 0x0D,
    "shift": 0x10,
    "lshift": 0xA0,
    "rshift": 0xA1,
    "z": 0x5A,
    "x": 0x58,
    "c": 0x43,
    "v": 0x56,
    "b": 0x42,
    "n": 0x4E,
    "m": 0x4D,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
    "ctrl": 0x11,
    "lctrl": 0xA2,
    "rctrl": 0xA3,
    "alt": 0x12,
    "lalt": 0xA4,
    "ralt": 0xA5,
    "space": 0x20,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}


@service_info(
    alias="controller",
    public=True,
    capabilities=["desktop.mouse.input", "desktop.keyboard.input"],
    side_effect_level="input",
)
class ControllerService:
    """Synchronous-compatible mouse and keyboard controller."""

    def __init__(self):
        self._held_keys: set[str] = set()
        self._held_mouse_buttons: set[str] = set()
        self.desktop = DesktopFacade()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()

    def __del__(self):
        try:
            if sys.is_finalizing() or sys.meta_path is None:
                self._release_all_best_effort()
                return
            self.release_all()
        except Exception:
            self._release_all_best_effort()

    def release_all(self):
        return self._submit_to_loop_and_wait(self.release_all_async())

    def release_key(self):
        return self._submit_to_loop_and_wait(self.release_key_async())

    def release_mouse(self):
        return self._submit_to_loop_and_wait(self.release_mouse_async())

    def move_to(self, x: int, y: int, duration: float = 0.25):
        return self._submit_to_loop_and_wait(self.move_to_async(x, y, duration))

    def move_relative(self, dx: int, dy: int, duration: float = 0.2):
        return self._submit_to_loop_and_wait(self.move_relative_async(dx, dy, duration))

    def list_capabilities(self):
        return self.desktop.list_capabilities()

    def self_check(self):
        return self.desktop.self_check()

    def mouse_down(self, button: str = "left"):
        button = button.lower()
        result = self.desktop.mouse("down", button=button)
        if not result.ok:
            raise RuntimeError(result.message)
        self._held_mouse_buttons.add(button)

    def mouse_up(self, button: str = "left"):
        button = button.lower()
        result = self.desktop.mouse("up", button=button)
        if not result.ok:
            raise RuntimeError(result.message)
        self._held_mouse_buttons.discard(button)

    def click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.1,
    ):
        return self._submit_to_loop_and_wait(self.click_async(x, y, button, clicks, interval))

    def drag_to(self, x: int, y: int, button: str = "left", duration: float = 0.5):
        return self._submit_to_loop_and_wait(self.drag_to_async(x, y, button, duration))

    def scroll(self, amount: int, direction: str = "down"):
        return self._submit_to_loop_and_wait(self.scroll_async(amount, direction))

    def key_down(self, key: str):
        result = self.desktop.keyboard("key_down", key=key)
        if not result.ok:
            raise RuntimeError(result.message)
        self._held_keys.add(key.lower())

    def key_up(self, key: str):
        result = self.desktop.keyboard("key_up", key=key)
        if not result.ok:
            raise RuntimeError(result.message)
        self._held_keys.discard(key.lower())

    def press_key(self, key: str, presses: int = 1, interval: float = 0.1):
        return self._submit_to_loop_and_wait(self.press_key_async(key, presses, interval))

    def type_text(self, text: str, interval: float = 0.01):
        return self._submit_to_loop_and_wait(self.type_text_async(text, interval))

    @contextmanager
    def hold_key(self, key: str):
        try:
            self.key_down(key)
            yield
        finally:
            self.key_up(key)

    async def release_all_async(self):
        if self._held_keys or self._held_mouse_buttons:
            logger.info("Releasing all held keyboard and mouse inputs.")
        tasks = [self.key_up_async(key) for key in list(self._held_keys)]
        tasks.extend([self.mouse_up_async(button) for button in list(self._held_mouse_buttons)])
        await asyncio.gather(*tasks)

    async def release_key_async(self):
        if self._held_keys:
            logger.info("Releasing all held keys.")
        tasks = [self.key_up_async(key) for key in list(self._held_keys)]
        await asyncio.gather(*tasks)

    async def release_mouse_async(self):
        if self._held_mouse_buttons:
            logger.info("Releasing all held mouse buttons.")
        tasks = [self.mouse_up_async(button) for button in list(self._held_mouse_buttons)]
        await asyncio.gather(*tasks)

    async def move_to_async(self, x: int, y: int, duration: float = 0.25):
        result = self.desktop.mouse("move", x=int(x), y=int(y), duration=duration)
        if not result.ok:
            raise RuntimeError(result.message)

    async def move_relative_async(self, dx: int, dy: int, duration: float = 0.2):
        result = self.desktop.mouse("move", dx=int(dx), dy=int(dy), absolute=False, duration=duration)
        if not result.ok:
            raise RuntimeError(result.message)

    async def mouse_down_async(self, button: str = "left"):
        await asyncio.to_thread(self.mouse_down, button)

    async def mouse_up_async(self, button: str = "left"):
        await asyncio.to_thread(self.mouse_up, button)

    async def click_async(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.1,
    ):
        if x is not None and y is not None:
            await self.move_to_async(x, y)
        for index in range(clicks):
            await self.mouse_down_async(button)
            await asyncio.sleep(max(0.0, min(interval, 0.02)))
            await self.mouse_up_async(button)
            if index < clicks - 1:
                await asyncio.sleep(max(0.0, interval))

    async def drag_to_async(self, x: int, y: int, button: str = "left", duration: float = 0.5):
        await self.mouse_down_async(button)
        await self.move_to_async(x, y, duration)
        await self.mouse_up_async(button)

    async def scroll_async(self, amount: int, direction: str = "down"):
        result = self.desktop.mouse("scroll", amount=int(abs(amount)), direction=direction)
        if not result.ok:
            raise RuntimeError(result.message)

    async def key_down_async(self, key: str):
        await asyncio.to_thread(self.key_down, key)

    async def key_up_async(self, key: str):
        await asyncio.to_thread(self.key_up, key)

    async def press_key_async(self, key: str, presses: int = 1, interval: float = 0.1):
        result = self.desktop.keyboard("press", key=key, presses=presses, interval=interval)
        if not result.ok:
            raise RuntimeError(result.message)

    async def type_text_async(self, text: str, interval: float = 0.01):
        result = self.desktop.keyboard("type_text", text=text, interval=interval)
        if not result.ok:
            raise RuntimeError(result.message)

    @asynccontextmanager
    async def hold_key_async(self, key: str):
        try:
            await self.key_down_async(key)
            yield
        finally:
            await self.key_up_async(key)

    def _get_vk(self, key: str) -> int:
        key = key.lower()
        if key in KEY_MAP:
            return KEY_MAP[key]
        if len(key) == 1:
            return ord(key.upper())
        raise ValueError(f"Unknown key: '{key}'")

    def _get_running_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:
            if self._loop is None or self._loop.is_closed():
                from packages.aura_core.api import service_registry

                scheduler = service_registry.get_service_instance("scheduler")
                if scheduler and scheduler._loop and scheduler._loop.is_running():
                    self._loop = scheduler._loop
                else:
                    raise RuntimeError("ControllerService cannot find running asyncio loop.")
            return self._loop

    def _submit_to_loop_and_wait(self, coro: asyncio.Future) -> Any:
        loop = self._get_running_loop()
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is loop:
            raise RuntimeError("ControllerService sync API called from event loop thread; use *_async.")
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()

    def _release_all_best_effort(self):
        for key in list(self._held_keys):
            try:
                self.key_up(key)
            except Exception:
                pass
        for button in list(self._held_mouse_buttons):
            try:
                self.mouse_up(button)
            except Exception:
                pass

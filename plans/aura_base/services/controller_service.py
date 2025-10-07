"""
提供一个底层的、统一的键鼠控制服务。

该模块的核心是 `ControllerService`，它封装了对 `win32api` 的直接调用，
为上层服务提供了一个与平台无关（理论上，当前为Windows实现）的、
可靠的键鼠模拟接口。

与 `AppProviderService` 类似，它采用了同步接口、异步核心的设计模式，
使得自动化脚本可以方便地以同步方式调用，而所有涉及延迟的操作
（如平滑移动、按键间隔）都在内部以非阻塞方式实现。
"""
import asyncio
import threading
from contextlib import contextmanager, asynccontextmanager
from typing import Any, Optional, Generator, AsyncGenerator

import win32api
import win32con

from packages.aura_core.api import register_service
from packages.aura_core.logger import logger

# --- 虚拟键码映射 ---
KEY_MAP = {
    'esc': 0x1B, 'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
    'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
    '`': 0xC0, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34, '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    '0': 0x30, '-': 0xBD, '=': 0xBB,
    'backspace': 0x08, 'tab': 0x09, 'q': 0x51, 'w': 0x57, 'e': 0x45, 'r': 0x52, 't': 0x54, 'y': 0x59, 'u': 0x55,
    'i': 0x49, 'o': 0x4F, 'p': 0x50, '[': 0xDB, ']': 0xDD, '\\': 0xDC,
    'capslock': 0x14, 'a': 0x41, 's': 0x53, 'd': 0x44, 'f': 0x46, 'g': 0x47, 'h': 0x48, 'j': 0x4A, 'k': 0x4B, 'l': 0x4C,
    ';': 0xBA, "'": 0xDE, 'enter': 0x0D,
    'shift': 0x10, 'lshift': 0xA0, 'rshift': 0xA1, 'z': 0x5A, 'x': 0x58, 'c': 0x43, 'v': 0x56, 'b': 0x42, 'n': 0x4E,
    'm': 0x4D, ',': 0xBC, '.': 0xBE, '/': 0xBF,
    'ctrl': 0x11, 'lctrl': 0xA2, 'rctrl': 0xA3, 'alt': 0x12, 'lalt': 0xA4, 'ralt': 0xA5, 'space': 0x20,
    'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27
}


@register_service(alias="controller", public=True)
class ControllerService:
    """
    一个统一的、高级的键鼠控制器。

    它对外提供一套与平台无关的同步接口来模拟鼠标和键盘操作，同时其
    内部实现是完全异步的，以确保在Aura框架中不会阻塞事件循环。
    服务会跟踪当前按下的键和鼠标按钮，以确保在程序退出时能够可靠地释放它们。
    """

    def __init__(self):
        """初始化控制器服务，清空按键状态。"""
        self._held_keys: set[str] = set()
        self._held_mouse_buttons: set[str] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_lock = threading.Lock()

    def __del__(self):
        """在对象销毁时确保释放所有按键。"""
        self.release_all()

    # =========================================================================
    # Section 1: 公共同步接口
    # =========================================================================

    def release_all(self):
        """释放所有当前被模拟按下的按键和鼠标按钮。"""
        return self._submit_to_loop_and_wait(self.release_all_async())

    def release_key(self):
        """释放所有当前被模拟按下的键盘按键。"""
        return self._submit_to_loop_and_wait(self.release_key_async())

    def release_mouse(self):
        """释放所有当前被模拟按下的鼠标按钮。"""
        return self._submit_to_loop_and_wait(self.release_mouse_async())

    def move_to(self, x: int, y: int, duration: float = 0.25):
        """
        将鼠标平滑移动到指定的屏幕绝对坐标。

        Args:
            x (int): 目标位置的屏幕 x 坐标。
            y (int): 目标位置的屏幕 y 坐标。
            duration (float): 移动过程的持续时间（秒）。
        """
        return self._submit_to_loop_and_wait(self.move_to_async(x, y, duration))

    def move_relative(self, dx: int, dy: int, duration: float = 0.2):
        """
        相对于当前鼠标位置平滑移动鼠标。

        Args:
            dx (int): 在 x 轴上的移动距离。
            dy (int): 在 y 轴上的移动距离。
            duration (float): 移动过程的持续时间（秒）。
        """
        return self._submit_to_loop_and_wait(self.move_relative_async(dx, dy, duration))

    def mouse_down(self, button: str = 'left'):
        """
        模拟按下指定的鼠标按钮。

        Args:
            button (str): 要按下的按钮 ('left', 'right', 'middle')。
        """
        button = button.lower()
        if button == 'left':
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        elif button == 'right':
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        elif button == 'middle':
            win32api.mouse_event(win32con.MOUSEEVENTF_MIDDLEDOWN, 0, 0, 0, 0)
        else:
            raise ValueError(f"不支持的鼠标按钮: {button}")
        self._held_mouse_buttons.add(button)

    def mouse_up(self, button: str = 'left'):
        """
        模拟松开指定的鼠标按钮。

        Args:
            button (str): 要松开的按钮 ('left', 'right', 'middle')。
        """
        button = button.lower()
        if button == 'left':
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        elif button == 'right':
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        elif button == 'middle':
            win32api.mouse_event(win32con.MOUSEEVENTF_MIDDLEUP, 0, 0, 0, 0)
        else:
            raise ValueError(f"不支持的鼠标按钮: {button}")
        self._held_mouse_buttons.discard(button)

    def click(self, x: Optional[int] = None, y: Optional[int] = None, button: str = 'left', clicks: int = 1,
              interval: float = 0.1):
        """
        模拟鼠标点击。如果提供了坐标，会先将鼠标移动到该位置。

        Args:
            x (Optional[int]): 点击位置的屏幕 x 坐标。
            y (Optional[int]): 点击位置的屏幕 y 坐标。
            button (str): 要点击的按钮。
            clicks (int): 点击次数。
            interval (float): 多次点击之间的间隔时间（秒）。
        """
        return self._submit_to_loop_and_wait(self.click_async(x, y, button, clicks, interval))

    def drag_to(self, x: int, y: int, button: str = 'left', duration: float = 0.5):
        """
        按住指定的鼠标按钮，从当前位置拖拽到目标坐标。

        Args:
            x (int): 拖拽终点的屏幕 x 坐标。
            y (int): 拖拽终点的屏幕 y 坐标。
            button (str): 用于拖拽的鼠标按钮。
            duration (float): 拖拽过程的持续时间（秒）。
        """
        return self._submit_to_loop_and_wait(self.drag_to_async(x, y, button, duration))

    def scroll(self, amount: int, direction: str = 'down'):
        """
        模拟鼠标滚轮滚动。

        Args:
            amount (int): 滚动的量（单位通常是滚轮的“咔哒”声次数）。
            direction (str): 'up' 或 'down'。
        """
        return self._submit_to_loop_and_wait(self.scroll_async(amount, direction))

    def key_down(self, key: str):
        """
        模拟按下指定的键盘按键。

        Args:
            key (str): 要按下的键的名称（例如 'enter', 'a', 'ctrl'）。
        """
        vk = self._get_vk(key)
        scan_code = win32api.MapVirtualKey(vk, 0)
        win32api.keybd_event(vk, scan_code, 0, 0)
        self._held_keys.add(key.lower())

    def key_up(self, key: str):
        """
        模拟松开指定的键盘按键。

        Args:
            key (str): 要松开的键的名称。
        """
        vk = self._get_vk(key)
        scan_code = win32api.MapVirtualKey(vk, 0)
        win32api.keybd_event(vk, scan_code, win32con.KEYEVENTF_KEYUP, 0)
        self._held_keys.discard(key.lower())

    def press_key(self, key: str, presses: int = 1, interval: float = 0.1):
        """
        完整地模拟一次或多次按键（按下然后松开）。

        Args:
            key (str): 要按下的键。
            presses (int): 按键次数。
            interval (float): 多次按键之间的间隔时间（秒）。
        """
        return self._submit_to_loop_and_wait(self.press_key_async(key, presses, interval))

    def type_text(self, text: str, interval: float = 0.01):
        """
        模拟输入一段文本。

        Args:
            text (str): 要输入的文本。
            interval (float): 每个字符之间的输入间隔时间（秒）。
        """
        return self._submit_to_loop_and_wait(self.type_text_async(text, interval))

    @contextmanager
    def hold_key(self, key: str) -> Generator[None, None, None]:
        """
        一个上下文管理器，用于在代码块执行期间按住一个键。

        Args:
            key (str): 要按住的键。
        """
        try:
            self.key_down(key)
            yield
        finally:
            self.key_up(key)

    # =========================================================================
    # Section 2: 内部异步核心实现
    # =========================================================================

    async def release_all_async(self):
        """异步地释放所有按下的键和鼠标按钮。"""
        if self._held_keys or self._held_mouse_buttons:
            logger.info("正在异步释放所有按下的键鼠...")
        tasks = [self.key_up_async(key) for key in list(self._held_keys)]
        tasks.extend([self.mouse_up_async(button) for button in list(self._held_mouse_buttons)])
        await asyncio.gather(*tasks)

    async def release_key_async(self):
        """异步地释放所有按下的键盘按键。"""
        if self._held_keys:
            logger.info("正在异步释放所有按下的按键...")
        tasks = [self.key_up_async(key) for key in list(self._held_keys)]
        await asyncio.gather(*tasks)

    async def release_mouse_async(self):
        """异步地释放所有按下的鼠标按钮。"""
        if self._held_mouse_buttons:
            logger.info("正在异步释放所有按下的鼠标...")
        tasks = [self.mouse_up_async(button) for button in list(self._held_mouse_buttons)]
        await asyncio.gather(*tasks)

    async def move_to_async(self, x: int, y: int, duration: float = 0.25):
        """异步地、平滑地将鼠标移动到屏幕绝对坐标。"""
        start_x, start_y = await asyncio.to_thread(win32api.GetCursorPos)
        steps = max(int(duration / 0.01), 1)
        if steps <= 0: return

        for i in range(1, steps + 1):
            progress = i / steps
            inter_x = int(start_x + (x - start_x) * progress)
            inter_y = int(start_y + (y - start_y) * progress)
            await asyncio.to_thread(win32api.SetCursorPos, (inter_x, inter_y))
            await asyncio.sleep(duration / steps)

    async def move_relative_async(self, dx: int, dy: int, duration: float = 0.2):
        """异步地、平滑地相对移动鼠标。"""
        start_x, start_y = await asyncio.to_thread(win32api.GetCursorPos)
        target_x, target_y = start_x + dx, start_y + dy
        await self.move_to_async(target_x, target_y, duration)

    async def mouse_down_async(self, button: str = 'left'):
        """异步地模拟鼠标按下。"""
        await asyncio.to_thread(self.mouse_down, button)

    async def mouse_up_async(self, button: str = 'left'):
        """异步地模拟鼠标松开。"""
        await asyncio.to_thread(self.mouse_up, button)

    async def click_async(self, x: Optional[int] = None, y: Optional[int] = None, button: str = 'left', clicks: int = 1,
                          interval: float = 0.1):
        """异步地模拟鼠标点击。"""
        if x is not None and y is not None:
            await self.move_to_async(x, y)
        for i in range(clicks):
            await self.mouse_down_async(button)
            await asyncio.sleep(0.02 + (interval - 0.02) * 0.5)
            await self.mouse_up_async(button)
            if i < clicks - 1:
                await asyncio.sleep(interval * 0.5)

    async def drag_to_async(self, x: int, y: int, button: str = 'left', duration: float = 0.5):
        """异步地模拟鼠标拖拽。"""
        await self.mouse_down_async(button)
        await self.move_to_async(x, y, duration)
        await self.mouse_up_async(button)

    async def scroll_async(self, amount: int, direction: str = 'down'):
        """异步地模拟鼠标滚动。"""
        scroll_amount = -120 if direction == 'down' else 120
        for _ in range(abs(amount)):
            await asyncio.to_thread(win32api.mouse_event, win32con.MOUSEEVENTF_WHEEL, 0, 0, scroll_amount, 0)
            await asyncio.sleep(0.05)

    async def key_down_async(self, key: str):
        """异步地模拟键盘按下。"""
        await asyncio.to_thread(self.key_down, key)

    async def key_up_async(self, key: str):
        """异步地模拟键盘松开。"""
        await asyncio.to_thread(self.key_up, key)

    async def press_key_async(self, key: str, presses: int = 1, interval: float = 0.1):
        """异步地模拟按键。"""
        for i in range(presses):
            await self.key_down_async(key)
            await asyncio.sleep(0.02 + (interval - 0.02) * 0.5)
            await self.key_up_async(key)
            if i < presses - 1:
                await asyncio.sleep(interval * 0.5)

    async def type_text_async(self, text: str, interval: float = 0.01):
        """异步地模拟文本输入，能自动处理 Shift 键。"""
        for char in text:
            vk_scan_result = await asyncio.to_thread(win32api.VkKeyScan, char)
            is_shift_needed = (vk_scan_result >> 8) & 1
            if is_shift_needed:
                async with self.hold_key_async('shift'):
                    await self.press_key_async(char)
            else:
                await self.press_key_async(char)
            await asyncio.sleep(interval)

    @asynccontextmanager
    async def hold_key_async(self, key: str) -> AsyncGenerator[None, None]:
        """一个异步上下文管理器，用于在异步代码块执行期间按住一个键。"""
        try:
            await self.key_down_async(key)
            yield
        finally:
            await self.key_up_async(key)

    # =========================================================================
    # Section 3: 内部辅助工具
    # =========================================================================

    def _get_vk(self, key: str) -> int:
        """内部同步方法，将字符串键名转换为 Windows 虚拟键码。"""
        key = key.lower()
        if key not in KEY_MAP:
            if len(key) == 1:
                return win32api.VkKeyScan(key) & 0xff
            raise ValueError(f"未知的按键: '{key}'")
        return KEY_MAP[key]

    # =========================================================================
    # Section 4: 同步/异步桥接器
    # =========================================================================

    def _get_running_loop(self) -> asyncio.AbstractEventLoop:
        """线程安全地获取正在运行的 asyncio 事件循环。"""
        with self._loop_lock:
            if self._loop is None or self._loop.is_closed():
                from packages.aura_core.api import service_registry
                scheduler = service_registry.get_service_instance('scheduler')
                if scheduler and scheduler._loop and scheduler._loop.is_running():
                    self._loop = scheduler._loop
                else:
                    raise RuntimeError("ControllerService 无法找到正在运行的 asyncio 事件循环。")
            return self._loop

    def _submit_to_loop_and_wait(self, coro: asyncio.Future) -> Any:
        """
        将一个协程从同步代码提交到事件循环，并阻塞地等待其结果。

        这是实现同步接口、异步核心的关键桥接方法。
        """
        loop = self._get_running_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()
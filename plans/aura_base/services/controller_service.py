# src/hardware/controller_service.py

import time
import win32api
import win32con
from contextlib import contextmanager
from packages.aura_shared_utils.utils.logger import logger
from packages.aura_core.api import register_service
# --- 虚拟键码映射 (保持不变) ---
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
    【精简版】现在只使用标准的 Windows API，移除了罗技驱动的依赖。
    """

    def __init__(self):
        self._held_keys = set()
        self._held_mouse_buttons = set()

    def __del__(self):
        # 确保在对象销毁时释放所有按键
        self.release_all()

    def release_all(self):
        """在脚本结束或异常时，释放所有被按下的按键和鼠标按钮，防止卡键。"""
        for key in list(self._held_keys):
            self.key_up(key)
        for button in list(self._held_mouse_buttons):
            self.mouse_up(button)
        # 只有在确实有按键被释放时才打印日志
        if self._held_keys or self._held_mouse_buttons:
            logger.info("所有按下的键鼠已被释放。")

    # --- 鼠标方法 ---

    def move_to(self, x: int, y: int, duration: float = 0.25):
        """
        平滑地将鼠标移动到屏幕上的绝对坐标。
        """
        start_x, start_y = win32api.GetCursorPos()
        steps = max(int(duration / 0.01), 1)  # 每10毫秒移动一次

        for i in range(1, steps + 1):
            progress = i / steps
            inter_x = int(start_x + (x - start_x) * progress)
            inter_y = int(start_y + (y - start_y) * progress)
            win32api.SetCursorPos((inter_x, inter_y))
            time.sleep(duration / steps)

    def move_relative(self, dx: int, dy: int, duration: float = 0.2):
        """
        【新增】平滑地从当前位置相对移动鼠标。
        """
        # 1. 获取鼠标当前位置作为起点
        start_x, start_y = win32api.GetCursorPos()

        # 2. 计算目标位置
        target_x = start_x + dx
        target_y = start_y + dy

        # 3. 复用 move_to 的平滑移动逻辑
        steps = max(int(duration / 0.01), 1)  # 每10毫秒移动一次
        for i in range(1, steps + 1):
            progress = i / steps
            # 从起点到目标点进行插值
            inter_x = int(start_x + (target_x - start_x) * progress)
            inter_y = int(start_y + (target_y - start_y) * progress)
            win32api.SetCursorPos((inter_x, inter_y))
            time.sleep(duration / steps)

    def mouse_down(self, button: str = 'left'):
        """按下指定的鼠标按钮。"""
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
        """释放指定的鼠标按钮。"""
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

    def click(self, x: int = None, y: int = None, button: str = 'left', clicks: int = 1, interval: float = 0.1):
        if x is not None and y is not None:
            self.move_to(x, y)
        for _ in range(clicks):
            self.mouse_down(button)
            time.sleep(0.02 + (interval - 0.02) * 0.5)
            self.mouse_up(button)
            if clicks > 1:
                time.sleep(interval * 0.5)

    def drag_to(self, x: int, y: int, button: str = 'left', duration: float = 0.5):
        self.mouse_down(button)
        self.move_to(x, y, duration)
        self.mouse_up(button)

    def scroll(self, amount: int, direction: str = 'down'):
        scroll_amount = -120 if direction == 'down' else 120
        for _ in range(abs(amount)):
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, scroll_amount, 0)
            time.sleep(0.05)

    # --- 键盘方法 ---

    def _get_vk(self, key: str) -> int:
        """内部方法，将字符串键转换为虚拟键码。"""
        key = key.lower()
        if key not in KEY_MAP:
            if len(key) == 1:
                return win32api.VkKeyScan(key) & 0xff
            raise ValueError(f"未知的按键: '{key}'")
        return KEY_MAP[key]

    def key_down(self, key: str):
        """按下指定的键盘按键。"""
        vk = self._get_vk(key)
        scan_code = win32api.MapVirtualKey(vk, 0)
        win32api.keybd_event(vk, scan_code, 0, 0)
        self._held_keys.add(key.lower())

    def key_up(self, key: str):
        """释放指定的键盘按键。"""
        vk = self._get_vk(key)
        scan_code = win32api.MapVirtualKey(vk, 0)
        win32api.keybd_event(vk, scan_code, win32con.KEYEVENTF_KEYUP, 0)
        self._held_keys.discard(key.lower())

    def press_key(self, key: str, presses: int = 1, interval: float = 0.1):
        """模拟一次完整的按键（按下并释放）。"""
        for _ in range(presses):
            self.key_down(key)
            time.sleep(0.02 + (interval - 0.02) * 0.5)
            self.key_up(key)
            if presses > 1:
                time.sleep(interval * 0.5)

    def type_text(self, text: str, interval: float = 0.01):
        """模拟键盘输入一段字符串，并能自动处理Shift键。"""
        for char in text:
            vk_scan_result = win32api.VkKeyScan(char)
            is_shift_needed = (vk_scan_result >> 8) & 1
            if is_shift_needed:
                with self.hold_key('shift'):
                    self.press_key(char)
            else:
                self.press_key(char)
            time.sleep(interval)

    @contextmanager
    def hold_key(self, key: str):
        """一个上下文管理器，用于在代码块执行期间按住一个键。"""
        try:
            self.key_down(key)
            yield
        finally:
            self.key_up(key)




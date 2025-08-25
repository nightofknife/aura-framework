# plans/window_controller/window_controller_services/window_controller_service.py

import time
from typing import Tuple, Optional

import win32api
import win32con
import win32gui

from packages.aura_core.api import register_service
from packages.aura_core.logger import logger

# 复用你的KEY_MAP，它在这里同样适用
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


@register_service(alias="window_controller", public=True)
class WindowControllerService:
    """
    后台窗口控制器服务。
    使用win32api的PostMessage和SendMessage与窗口进行交互，不影响前台用户操作。
    """

    def find_window(self, class_name: Optional[str] = None, window_title: Optional[str] = None) -> int:
        """
        查找窗口句柄 (HWND)。
        :param class_name: 窗口类名 (可选)。
        :param window_title: 窗口标题 (可选)。
        :return: 窗口句柄 (整数)，如果找不到则返回0。
        """
        hwnd = win32gui.FindWindow(class_name, window_title)
        if hwnd == 0:
            logger.debug(f"未找到窗口: class='{class_name}', title='{window_title}'")
        else:
            logger.debug(f"找到窗口: HWND={hwnd}")
        return hwnd

    def get_window_rect(self, hwnd: int) -> Optional[Tuple[int, int, int, int]]:
        """
        获取窗口的屏幕坐标 (left, top, right, bottom)。
        """
        if not self._is_valid_hwnd(hwnd):
            return None
        try:
            return win32gui.GetWindowRect(hwnd)
        except win32gui.error:
            logger.warning(f"获取窗口 {hwnd} 坐标失败，窗口可能已关闭。")
            return None

    def get_window_text(self, hwnd: int) -> str:
        """获取窗口标题。"""
        if not self._is_valid_hwnd(hwnd):
            return ""
        return win32gui.GetWindowText(hwnd)

    def send_click(self, hwnd: int, x: int, y: int, button: str = 'left'):
        """
        向窗口的指定客户端坐标发送后台点击事件。
        :param hwnd: 目标窗口句柄。
        :param x: 窗口内的X坐标。
        :param y: 窗口内的Y坐标。
        :param button: 'left', 'right', 'middle'。
        """
        if not self._is_valid_hwnd(hwnd):
            return

        lparam = win32api.MAKELONG(x, y)

        button_map = {
            'left': (win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP, win32con.MK_LBUTTON),
            'right': (win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP, win32con.MK_RBUTTON),
            'middle': (win32con.WM_MBUTTONDOWN, win32con.WM_MBUTTONUP, win32con.MK_MBUTTON),
        }

        if button.lower() not in button_map:
            raise ValueError(f"不支持的鼠标按钮: {button}")

        down_msg, up_msg, wparam = button_map[button.lower()]

        win32api.PostMessage(hwnd, down_msg, wparam, lparam)
        time.sleep(0.05)  # 模拟点击延迟
        win32api.PostMessage(hwnd, up_msg, wparam, lparam)
        logger.debug(f"向窗口 {hwnd} 的 ({x},{y}) 发送了后台 '{button}' 点击")

    def send_keystroke(self, hwnd: int, key: str):
        """
        向窗口发送后台按键事件。
        """
        if not self._is_valid_hwnd(hwnd):
            return

        vk_code = self._get_vk(key)

        # PostMessage通常lParam可以为0，系统会填充
        win32api.PostMessage(hwnd, win32con.WM_KEYDOWN, vk_code, 0)
        time.sleep(0.05)
        win32api.PostMessage(hwnd, win32con.WM_KEYUP, vk_code, 0)
        logger.debug(f"向窗口 {hwnd} 发送了后台按键 '{key}'")

    def type_text(self, hwnd: int, text: str, interval: float = 0.01):
        """
        向窗口发送后台文本输入。这是最可靠的文本输入方式。
        """
        if not self._is_valid_hwnd(hwnd):
            return

        for char in text:
            win32api.PostMessage(hwnd, win32con.WM_CHAR, ord(char), 0)
            time.sleep(interval)
        logger.debug(f"向窗口 {hwnd} 发送了后台文本: '{text}'")

    def _get_vk(self, key: str) -> int:
        """内部方法，将字符串键转换为虚拟键码。"""
        key = key.lower()
        if key not in KEY_MAP:
            if len(key) == 1:
                # VkKeyScan返回一个短整型，低位字节是虚拟键码，高位字节是Shift状态
                return win32api.VkKeyScan(key) & 0xff
            raise ValueError(f"未知的按键: '{key}'")
        return KEY_MAP[key]

    def _is_valid_hwnd(self, hwnd: int) -> bool:
        """检查句柄是否是一个有效的、存在的窗口。"""
        if not isinstance(hwnd, int) or hwnd == 0:
            logger.error("提供的句柄无效 (0 或非整数)。")
            return False
        if not win32gui.IsWindow(hwnd):
            logger.error(f"句柄 {hwnd} 对应的窗口不存在或已销毁。")
            return False
        return True

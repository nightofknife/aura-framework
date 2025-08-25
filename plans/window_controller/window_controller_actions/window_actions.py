# plans/window_controller/window_controller_actions/window_actions.py

from typing import Optional, Tuple

from packages.aura_core.api import register_action, requires_services
from packages.aura_core.logger import logger


@register_action(name="find_window", public=True, read_only=True)
@requires_services(wc='window_controller')
def find_window(wc, class_name: Optional[str] = None, window_title: Optional[str] = None) -> int:
    """
    查找窗口并返回其句柄 (HWND)。

    参数:
        class_name: 窗口的类名 (例如 "Notepad")。
        window_title: 窗口的标题 (例如 "无标题 - 记事本")。

    返回:
        找到的窗口句柄 (一个整数)，如果找不到则返回 0。
    """
    return wc.find_window(class_name, window_title)


@register_action(name="get_window_rect", public=True, read_only=True)
@requires_services(wc='window_controller')
def get_window_rect(wc, hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """
    获取窗口的屏幕坐标矩形 (left, top, right, bottom)。
    """
    return wc.get_window_rect(hwnd)


@register_action(name="get_window_text", public=True, read_only=True)
@requires_services(wc='window_controller')
def get_window_text(wc, hwnd: int) -> str:
    """
    获取窗口的标题文本。
    """
    return wc.get_window_text(hwnd)


@register_action(name="send_click_to_window", public=True)
@requires_services(wc='window_controller')
def send_click_to_window(wc, hwnd: int, x: int, y: int, button: str = 'left'):
    """
    向指定窗口的内部坐标发送后台鼠标点击。

    参数:
        hwnd: 目标窗口的句柄。
        x: 窗口内部的X坐标。
        y: 窗口内部的Y坐标。
        button: "left", "right", 或 "middle"。
    """
    try:
        wc.send_click(hwnd, x, y, button)
        return True
    except Exception as e:
        logger.error(f"发送后台点击失败: {e}")
        return False


@register_action(name="send_key_to_window", public=True)
@requires_services(wc='window_controller')
def send_key_to_window(wc, hwnd: int, key: str):
    """
    向指定窗口发送后台按键。

    参数:
        hwnd: 目标窗口的句柄。
        key: 要发送的按键 (例如 "a", "enter", "f5")。
    """
    try:
        wc.send_keystroke(hwnd, key)
        return True
    except Exception as e:
        logger.error(f"发送后台按键失败: {e}")
        return False


@register_action(name="type_text_in_window", public=True)
@requires_services(wc='window_controller')
def type_text_in_window(wc, hwnd: int, text: str, interval: float = 0.01):
    """
    向指定窗口发送后台文本输入。

    参数:
        hwnd: 目标窗口的句柄。
        text: 要输入的文本。
        interval: 每个字符之间的输入间隔(秒)。
    """
    try:
        wc.type_text(hwnd, text, interval)
        return True
    except Exception as e:
        logger.error(f"发送后台文本失败: {e}")
        return False

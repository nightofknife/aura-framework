# packages/aura_base/services/screen_service.py (最终修正版)

import time
from ctypes import windll
from dataclasses import dataclass, field

import cv2
import numpy as np
import screeninfo
import win32con
import win32gui
import win32ui
from PIL import Image

from packages.aura_core.api import register_service
from packages.aura_shared_utils.utils.logger import logger
# 【【【核心修正 1/3：导入 ConfigService】】】
from .config_service import ConfigService


@dataclass
class CaptureResult:
    success: bool
    image: np.ndarray | None = None
    window_rect: tuple[int, int, int, int] | None = None
    relative_rect: tuple[int, int, int, int] | None = None
    error_message: str = field(default="", repr=False)

    @property
    def image_size(self) -> tuple[int, int] | None:
        if self.image is not None:
            return self.image.shape[:2]
        return None

    def save(self, filepath: str):
        if self.success and self.image is not None:
            try:
                if self.image.shape[2] == 4:
                    image_bgr = cv2.cvtColor(self.image, cv2.COLOR_RGBA2BGR)
                else:
                    image_bgr = cv2.cvtColor(self.image, cv2.COLOR_RGB2BGR)
                cv2.imwrite(filepath, image_bgr)
            except Exception as e:
                logger.error(f"保存截图 '{filepath}' 时发生OpenCV错误: {e}")
        elif not self.success:
            logger.warning(f"无法保存截图, 因为截图操作未成功: {self.error_message}")
        else:
            logger.warning("无法保存截图, 因为图像数据为空。")


@register_service(alias="screen", public=True)
class ScreenService:
    """
    屏幕截图服务。
    通过依赖注入ConfigService来获取目标窗口标题，实现配置驱动。
    """

    # 【【【核心修正 2/3：修改构造函数，依赖ConfigService】】】
    def __init__(self, config: ConfigService):
        """
        初始化 ScreenService。
        它不再直接接收 target_title，而是接收 ConfigService 实例。

        :param config: 注入的配置服务实例。
        """
        # 从配置服务中获取目标窗口标题。
        # 'app.target_window_title' 是一个推荐的配置路径，你可以在config.yaml中定义。
        # 如果配置中不存在，则默认为 None，表示截取全屏。
        self.target_title = config.get('app.target_window_title', None)

        self.hwnd = None
        self._update_hwnd()
        logger.info(
            f"截图服务已初始化。当前目标: {'全屏' if self.target_title is None else f'窗口<{self.target_title}>'}")

    # 【【【核心修正 3/3：移除 set_target 方法】】】
    # 移除 set_target 方法，强制所有配置通过 config.yaml 管理，这使得服务行为更可预测。
    # def set_target(self, target_title: str = None): ...

    def _update_hwnd(self):
        if self.target_title:
            try:
                self.hwnd = win32gui.FindWindow(None, self.target_title)
                if not self.hwnd:
                    logger.trace(f"未能立即找到窗口 '{self.target_title}'，将在需要时重试。")
            except Exception:
                self.hwnd = None
        else:
            self.hwnd = None

    # ... (从 get_client_rect 到文件末尾的所有其他方法都保持不变) ...
    def get_client_rect(self) -> tuple[int, int, int, int] | None:
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            self._update_hwnd()
        if self.hwnd:
            try:
                client_top_left = win32gui.ClientToScreen(self.hwnd, (0, 0))
                left, top, right, bot = win32gui.GetClientRect(self.hwnd)
                width = right - left
                height = bot - top
                return (client_top_left[0], client_top_left[1], width, height)
            except Exception as e:
                logger.error(f"获取窗口客户区矩形时出错: {e}")
                return None
        return None

    def get_pixel_color_at(self, global_x: int, global_y: int) -> tuple[int, int, int]:
        h_win_dc = win32gui.GetWindowDC(0)
        try:
            long_color = win32gui.GetPixel(h_win_dc, global_x, global_y)
            r = long_color & 0xff
            g = (long_color >> 8) & 0xff
            b = (long_color >> 16) & 0xff
            return (r, g, b)
        finally:
            win32gui.ReleaseDC(0, h_win_dc)

    def focus(self) -> bool:
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            self._update_hwnd()
        if self.hwnd:
            try:
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(self.hwnd)
                return True
            except Exception as e:
                logger.error(f"激活窗口句柄 {self.hwnd} 时出错: {e}")
                return False
        logger.warning(f"无法找到窗口 '{self.target_title}' 来进行聚焦。")
        return False

    @staticmethod
    def _bitmap_to_numpy(bitmap) -> np.ndarray | None:
        try:
            bmp_info = bitmap.GetInfo()
            bmp_str = bitmap.GetBitmapBits(True)
            img = Image.frombuffer(
                'RGB',
                (bmp_info['bmWidth'], bmp_info['bmHeight']),
                bmp_str, 'raw', 'BGRX', 0, 1
            )
            return np.array(img)
        except Exception as e:
            logger.error(f"错误: 位图转换失败 - {e}")
            return None
        finally:
            if bitmap:
                win32gui.DeleteObject(bitmap.GetHandle())

    def _capture_fullscreen(self) -> CaptureResult:
        try:
            primary_screen = screeninfo.get_monitors()[0]
            rect = (primary_screen.x, primary_screen.y, primary_screen.width, primary_screen.height)
            h_win_dc = win32gui.GetWindowDC(0)
            src_dc = win32ui.CreateDCFromHandle(h_win_dc)
            mem_dc = src_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(src_dc, rect[2], rect[3])
            mem_dc.SelectObject(bitmap)
            mem_dc.BitBlt((0, 0), (rect[2], rect[3]), src_dc, (rect[0], rect[1]), win32con.SRCCOPY)
            img = self._bitmap_to_numpy(bitmap)
            src_dc.DeleteDC()
            mem_dc.DeleteDC()
            win32gui.ReleaseDC(0, h_win_dc)
            if img is not None:
                relative_rect = (0, 0, rect[2], rect[3])
                return CaptureResult(image=img, window_rect=rect, relative_rect=relative_rect, success=True)
        except Exception as e:
            logger.error(f"错误: 全屏截图失败 - {e}")
            return CaptureResult(success=False, error_message=str(e))

    def _capture_window(self, hwnd: int, sub_rect: tuple[int, int, int, int] | None = None) -> CaptureResult:
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
                return CaptureResult(success=False, error_message="窗口客户区尺寸为0")
            h_win_dc = win32gui.GetWindowDC(hwnd)
            src_dc = win32ui.CreateDCFromHandle(h_win_dc)
            mem_dc = src_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(src_dc, client_width, client_height)
            mem_dc.SelectObject(bitmap)
            windll.user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), 3)
            full_image = self._bitmap_to_numpy(bitmap)
            src_dc.DeleteDC()
            mem_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, h_win_dc)
            if full_image is None:
                raise Exception("无法从位图创建图像")
            if sub_rect:
                x, y, w, h = sub_rect
                if x < 0 or y < 0 or w <= 0 or h <= 0 or (x + w) > client_width or (y + h) > client_height:
                    raise ValueError(f"截图区域 {sub_rect} 超出客户区 ({client_width}x{client_height})")
                final_image = full_image[y: y + h, x: x + w]
                relative_rect = sub_rect
            else:
                final_image = full_image
                relative_rect = (0, 0, client_width, client_height)
            return CaptureResult(image=final_image, window_rect=window_rect, relative_rect=relative_rect, success=True)
        except Exception as e:
            logger.error(f"错误: 窗口截图失败 - {e}")
            return CaptureResult(success=False, window_rect=window_rect, error_message=str(e))

    def capture(self, rect: tuple[int, int, int, int] | None = None) -> CaptureResult:
        if not self.target_title:
            if rect:
                logger.warning("提供了截图区域 rect，但在全屏模式下将被忽略。")
            return self._capture_fullscreen()
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            logger.trace(f"缓存的句柄无效或窗口已关闭，尝试重新查找 '{self.target_title}'...")
            self._update_hwnd()
        if self.hwnd:
            if win32gui.IsIconic(self.hwnd):
                logger.info(f"窗口 '{self.target_title}' 已最小化，尝试后台恢复...")
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                win32gui.SetWindowPos(self.hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                                      win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
                time.sleep(0.2)
            return self._capture_window(self.hwnd, sub_rect=rect)
        else:
            logger.warning(f"找不到标题为 '{self.target_title}' 的窗口，将进行全屏截图。")
            return self._capture_fullscreen()

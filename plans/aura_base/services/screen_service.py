"""
提供一个用于屏幕和窗口交互的底层服务。

该模块的核心是 `ScreenService`，它封装了与操作系统桌面环境交互的
功能，主要包括：
- 捕获全屏或特定窗口的图像。
- 获取窗口的位置和尺寸信息。
- 激活（聚焦）指定窗口。
- 获取屏幕上任意点的像素颜色。

`CaptureResult` 是一个用于封装截图结果的数据类。

此服务同样采用了同步接口、异步核心的设计模式，将所有可能阻塞的
`win32api` 调用都放在后台线程中执行，以保证主事件循环的流畅运行。
"""
import asyncio
import threading
from ctypes import windll
from dataclasses import dataclass, field
from typing import Any, Optional

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
    """
    封装一次屏幕捕获操作的结果。

    Attributes:
        success (bool): 操作是否成功。
        image (Optional[np.ndarray]): 捕获到的图像，格式为 NumPy 数组 (RGB)。
            如果操作失败，则为 None。
        window_rect (Optional[Tuple[int, int, int, int]]): 目标窗口在屏幕上的
            绝对位置和尺寸 `(x, y, width, height)`。
        relative_rect (Optional[Tuple[int, int, int, int]]): 捕获区域相对于
            目标窗口客户区的相对位置和尺寸 `(x, y, width, height)`。
        error_message (str): 如果操作失败，则包含错误信息。
    """
    success: bool
    image: Optional[np.ndarray] = None
    window_rect: Optional[tuple[int, int, int, int]] = None
    relative_rect: Optional[tuple[int, int, int, int]] = None
    error_message: str = field(default="", repr=False)

    @property
    def image_size(self) -> Optional[tuple[int, int]]:
        """
        返回捕获图像的尺寸（宽度, 高度）。

        Returns:
            Optional[tuple[int, int]]: 如果图像存在，则返回尺寸元组，否则返回 None。
        """
        if self.image is not None:
            # shape is (height, width, channels)
            return self.image.shape[1], self.image.shape[0]
        return None

    def save(self, filepath: str):
        """
        将捕获的图像保存到指定的文件路径。

        Args:
            filepath (str): 要保存到的文件路径。
        """
        if self.success and self.image is not None:
            try:
                # OpenCV expects BGR format for imwrite
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
    屏幕服务，负责处理屏幕和窗口的截图及信息获取。

    它通过 `ConfigService` 获取目标窗口标题，并提供捕获全屏或
    特定窗口客户区的功能。
    """

    def __init__(self, config: ConfigService):
        """
        初始化屏幕服务。

        Args:
            config (ConfigService): 注入的配置服务实例。
        """
        self.target_title = config.get('app.target_window_title', None)
        self.hwnd = None
        self._update_hwnd()
        logger.info(
            f"截图服务已初始化。当前目标: {'全屏' if self.target_title is None else f'窗口<{self.target_title}>'}")

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_lock = threading.Lock()

    # =========================================================================
    # Section 1: 公共同步接口
    # =========================================================================

    def get_client_rect(self) -> Optional[tuple[int, int, int, int]]:
        """
        获取目标窗口的客户区矩形。

        这是一个快速的同步调用，因为它不涉及耗时操作。

        Returns:
            Optional[tuple[int, int, int, int]]: 一个包含窗口客户区在屏幕上的
                绝对坐标 `(x, y)` 及其 `(width, height)` 的元组。如果找不到窗口，
                则返回 None。
        """
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            self._update_hwnd()
        if self.hwnd:
            try:
                client_top_left = win32gui.ClientToScreen(self.hwnd, (0, 0))
                left, top, right, bot = win32gui.GetClientRect(self.hwnd)
                return (client_top_left[0], client_top_left[1], right - left, bot - top)
            except Exception as e:
                logger.error(f"获取窗口客户区矩形时出错: {e}")
        return None

    def get_pixel_color_at(self, global_x: int, global_y: int) -> tuple[int, int, int]:
        """
        获取屏幕上指定全局坐标点的像素颜色。

        Args:
            global_x (int): 屏幕的 x 坐标。
            global_y (int): 屏幕的 y 坐标。

        Returns:
            tuple[int, int, int]: 一个包含 `(R, G, B)` 颜色值的元组。
        """
        h_win_dc = win32gui.GetWindowDC(0)
        try:
            long_color = win32gui.GetPixel(h_win_dc, global_x, global_y)
            return (long_color & 0xff, (long_color >> 8) & 0xff, (long_color >> 16) & 0xff)
        finally:
            win32gui.ReleaseDC(0, h_win_dc)

    def focus(self) -> bool:
        """
        尝试将目标窗口带到前台并设置为焦点。

        Returns:
            bool: 如果成功，则返回 True。
        """
        return self._submit_to_loop_and_wait(self.focus_async())

    def capture(self, rect: Optional[tuple[int, int, int, int]] = None) -> CaptureResult:
        """
        捕获屏幕或目标窗口的图像。

        如果设置了目标窗口，则捕获该窗口的客户区。如果提供了 `rect` 参数，
        则从客户区中裁剪出指定区域。如果未设置目标窗口，则进行全屏截图。

        Args:
            rect (Optional[tuple[int, int, int, int]]): 要从窗口客户区中裁剪的
                相对区域 `(x, y, width, height)`。

        Returns:
            CaptureResult: 包含截图结果的对象。
        """
        return self._submit_to_loop_and_wait(self.capture_async(rect))

    # =========================================================================
    # Section 2: 内部异步核心实现
    # =========================================================================

    async def focus_async(self) -> bool:
        """异步地激活目标窗口。"""
        await asyncio.to_thread(self._update_hwnd)
        if self.hwnd:
            try:
                await asyncio.to_thread(win32gui.ShowWindow, self.hwnd, win32con.SW_RESTORE)
                await asyncio.to_thread(win32gui.SetForegroundWindow, self.hwnd)
                return True
            except Exception as e:
                logger.error(f"激活窗口句柄 {self.hwnd} 时出错: {e}")
                return False
        logger.warning(f"无法找到窗口 '{self.target_title}' 来进行聚焦。")
        return False

    async def capture_async(self, rect: Optional[tuple[int, int, int, int]] = None) -> CaptureResult:
        """异步地执行截图的核心逻辑。"""
        if not self.target_title:
            if rect:
                logger.warning("提供了截图区域 rect，但在全屏模式下将被忽略。")
            return await asyncio.to_thread(self._capture_fullscreen_sync)

        await asyncio.to_thread(self._update_hwnd)

        if self.hwnd:
            is_iconic = await asyncio.to_thread(win32gui.IsIconic, self.hwnd)
            if is_iconic:
                logger.info(f"窗口 '{self.target_title}' 已最小化，尝试后台恢复...")
                await asyncio.to_thread(win32gui.ShowWindow, self.hwnd, win32con.SW_RESTORE)
                await asyncio.to_thread(win32gui.SetWindowPos, self.hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
                await asyncio.sleep(0.2)

            result = await asyncio.to_thread(self._capture_window_sync, self.hwnd, sub_rect=rect)

            if not result.success:
                await asyncio.to_thread(self._update_hwnd)
                if self.hwnd:
                    result = await asyncio.to_thread(self._capture_window_sync, self.hwnd, sub_rect=rect)
            return result
        else:
            logger.warning(f"找不到标题为 '{self.target_title}' 的窗口，将进行全屏截图。")
            return await asyncio.to_thread(self._capture_fullscreen_sync)

    # =========================================================================
    # Section 3: 内部同步实现 (用于在线程池中执行)
    # =========================================================================

    def _update_hwnd(self):
        """更新目标窗口的句柄（HWND）。这是一个同步方法，因为它会被 `to_thread` 调用。"""
        if self.target_title:
            try:
                self.hwnd = win32gui.FindWindow(None, self.target_title)
                if not self.hwnd:
                    logger.trace(f"未能立即找到窗口 '{self.target_title}'，将在需要时重试。")
            except Exception:
                self.hwnd = None
        else:
            self.hwnd = None

    @staticmethod
    def _bitmap_to_numpy(bitmap: Any) -> Optional[np.ndarray]:
        """将 Windows GDI 位图对象转换为 NumPy 数组 (RGB格式)。"""
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
                raise ValueError(f"不支持的像素深度: {bpp}")
            return img.copy()
        except Exception as e:
            logger.error(f"错误: 位图转换失败 - {e}")
            return None
        finally:
            if bitmap:
                win32gui.DeleteObject(bitmap.GetHandle())

    def _capture_fullscreen_sync(self) -> CaptureResult:
        """执行全屏截图的同步阻塞操作。"""
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
            else:
                raise Exception("位图转换失败")
        except Exception as e:
            logger.error(f"错误: 全屏截图失败 - {e}")
            return CaptureResult(success=False, error_message=str(e))

    def _capture_window_sync(self, hwnd: int, sub_rect: Optional[tuple[int, int, int, int]] = None) -> CaptureResult:
        """执行窗口截图的同步阻塞操作。"""
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
            result = windll.user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), 3)
            if result != 1:
                logger.warning(f"PrintWindow (hwnd: {hwnd}) 返回 {result}, 可能导致截图不完整。")

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
            logger.error(f"错误: 窗口截图失败 - {e}", exc_info=False)
            return CaptureResult(success=False, window_rect=window_rect, error_message=str(e))

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
                    raise RuntimeError("ScreenService 无法找到正在运行的 asyncio 事件循环。")
            return self._loop

    def _submit_to_loop_and_wait(self, coro: asyncio.Future) -> Any:
        """将一个协程从同步代码提交到事件循环，并阻塞地等待其结果。"""
        loop = self._get_running_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()




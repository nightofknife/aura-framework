# src/hardware/screen_service.py

# --- 依赖 ---
# 需要安装: pip install pywin32 numpy Pillow screeninfo
import win32gui
import win32ui
import win32con
import numpy as np
import screeninfo
from PIL import Image
from ctypes import windll
import time
from dataclasses import dataclass, field
import cv2

from packages.aura_shared_utils.utils.logger import logger

# --- 截图结果的数据结构 ---
@dataclass
class CaptureResult:
    """
    一个结构体，用于封装截图操作的完整结果。
    """
    success: bool
    image: np.ndarray | None = None
    window_rect: tuple[int, int, int, int] | None = None
    relative_rect: tuple[int, int, int, int] | None = None
    # 为 error_message 添加一个默认值，这样就不需要在每次成功时都传递它
    error_message: str = field(default="", repr=False)

    @property
    def image_size(self) -> tuple[int, int] | None:
        """
        以 (height, width) 格式返回捕获图像的尺寸。
        """
        if self.image is not None:
            return self.image.shape[:2]
        return None

    def save(self, filepath: str):
        """
        【已修复】将截图结果中的NumPy图像数组保存到文件。
        """
        if self.success and self.image is not None:
            try:
                # 将截图的RGB(A)格式转换为OpenCV保存时需要的BGR格式
                # 检查图像是否有Alpha通道（第4个通道）
                if self.image.shape[2] == 4:
                    # 如果有Alpha通道，从 RGBA 转换为 BGR
                    image_bgr = cv2.cvtColor(self.image, cv2.COLOR_RGBA2BGR)
                else:
                    # 如果没有，从 RGB 转换为 BGR
                    image_bgr = cv2.cvtColor(self.image, cv2.COLOR_RGB2BGR)

                # 使用OpenCV写入文件
                success = cv2.imwrite(filepath, image_bgr)
                if not success:
                    print(f"OpenCV failed to save image to {filepath}")

            except cv2.error as e:
                print(f"OpenCV error while saving image to {filepath}: {e}")
            except Exception as e:
                print(f"An unexpected error occurred while saving image to {filepath}: {e}")

        elif not self.success:
            print(f"Cannot save image, capture was not successful: {self.error_message}")
        else:
            print("Cannot save image, because image data is None.")

class ScreenService:
    """
    屏幕截图模块，作为一个有状态的服务。
    - 【优化】通过缓存窗口句柄(HWND)来提升重复截图的性能。
    - 支持全窗口截图和窗口内指定区域截图。
    - 支持抗遮挡、自动处理最小化窗口。
    - 返回包含详细坐标元数据的 CaptureResult 对象。
    """

    def __init__(self, target_title: str = None):
        """
        初始化 ScreenService 服务。

        :param target_title: (可选) 目标应用程序的窗口标题。如果为 None，则默认截取主显示器全屏。
        """
        self.target_title = target_title
        self.hwnd = None  # 【优化】新增窗口句柄缓存
        self._update_hwnd()  # 【优化】初始化时查找一次句柄
        print(f"截图服务已初始化。当前目标: {'全屏' if target_title is None else target_title}")

    def set_target(self, target_title: str = None):
        """
        更改截图的目标窗口。

        :param target_title: (可选) 新的目标窗口标题。如果为 None，将切换到全屏截图模式。
        """
        self.target_title = target_title
        self._update_hwnd()  # 【优化】目标更新时重新查找句柄
        print(f"截图目标已更新。新目标: {'全屏' if target_title is None else target_title}")

    def _update_hwnd(self):
        """
        【优化】【内部辅助方法】根据 target_title 查找并更新窗口句柄。
        """
        if self.target_title:
            try:
                self.hwnd = win32gui.FindWindow(None, self.target_title)
            except Exception:
                self.hwnd = None
        else:
            self.hwnd = None


    def get_client_rect(self) -> tuple[int, int, int, int] | None:
        """
        【修正后核心方法】获取并返回目标窗口客户区(Client Area)的全局坐标。
        返回 (left, top, width, height) 元组，这是所有截图和坐标转换的基准。
        """
        # 检查缓存的句柄是否仍然有效
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            self._update_hwnd()

        if self.hwnd:
            try:
                # 1. 获取客户区的左上角在屏幕上的全局坐标
                client_top_left = win32gui.ClientToScreen(self.hwnd, (0, 0))

                # 2. 获取客户区的尺寸 (宽度和高度)
                # GetClientRect 返回的坐标是相对于窗口客户区本身的，所以 left, top 总是 0
                left, top, right, bot = win32gui.GetClientRect(self.hwnd)

                width = right - left
                height = bot - top

                # 3. 组合成屏幕上的绝对矩形
                return (client_top_left[0], client_top_left[1], width, height)
            except Exception as e:
                logger.error(f"获取窗口客户区矩形时出错: {e}")
                return None
        return None
    def get_pixel_color_at(self, global_x: int, global_y: int) -> tuple[int, int, int]:
        """
        获取屏幕上指定全局坐标的像素颜色。
        这个方法不依赖于目标窗口，直接从屏幕设备上下文获取。

        :param global_x: 屏幕全局x坐标。
        :param global_y: 屏幕全局y坐标。
        :return: (R, G, B) 颜色元组。
        """
        h_win_dc = win32gui.GetWindowDC(0)  # 0代表整个屏幕
        try:
            long_color = win32gui.GetPixel(h_win_dc, global_x, global_y)
            r = long_color & 0xff
            g = (long_color >> 8) & 0xff
            b = (long_color >> 16) & 0xff
            return (r, g, b)
        finally:
            win32gui.ReleaseDC(0, h_win_dc)

    def focus(self) -> bool:
        """
        尝试找到目标窗口并将其置于前台，使其获得输入焦点。

        :return: 如果成功找到并激活窗口，返回 True，否则返回 False。
        """
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            self._update_hwnd()

        if self.hwnd:
            try:
                # 使用 win32gui 将窗口带到前台
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)  # 如果窗口最小化，先恢复
                win32gui.SetForegroundWindow(self.hwnd)
                return True
            except Exception as e:
                logger.error(f"激活窗口句柄 {self.hwnd} 时出错: {e}")
                return False

        logger.warning(f"无法找到窗口 '{self.target_title}' 来进行聚焦。")
        return False

    @staticmethod
    def _bitmap_to_numpy(bitmap) -> np.ndarray | None:
        """
        [内部辅助方法] 将 pywin32 的位图对象转换为 NumPy 数组 (BGR格式)。
        """
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
            print(f"错误: 位图转换失败 - {e}")
            return None
        finally:
            if bitmap:
                win32gui.DeleteObject(bitmap.GetHandle())

    def _capture_fullscreen(self) -> CaptureResult:
        """
        [内部方法] 截取主显示器的全屏图像。
        """
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
            print(f"错误: 全屏截图失败 - {e}")

        return CaptureResult(image=None, window_rect=None, relative_rect=None, success=False)

    def _capture_window(self, hwnd: int, sub_rect: tuple[int, int, int, int] | None = None) -> CaptureResult:
        """
        [内部方法] 截取指定句柄的窗口图像，支持截取窗口内的子区域。
        """
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
                return CaptureResult(image=None, window_rect=window_rect, relative_rect=None, success=False)

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
                    raise ValueError(f"提供的截图区域 {sub_rect} 超出窗口客户区范围 ({client_width}x{client_height})")
                final_image = full_image[y: y + h, x: x + w]
                relative_rect = sub_rect
            else:
                final_image = full_image
                relative_rect = (0, 0, client_width, client_height)

            return CaptureResult(image=final_image, window_rect=window_rect, relative_rect=relative_rect, success=True)

        except Exception as e:
            print(f"错误: 窗口截图失败 - {e}")
            return CaptureResult(image=None, window_rect=window_rect, relative_rect=None, success=False)

    def capture(self, rect: tuple[int, int, int, int] | None = None) -> CaptureResult:
        """
        执行截图操作。

        :param rect: (可选) 一个元组 (x, y, width, height)，定义了在目标窗口客户区内要截取的子区域。
                     如果为 None，则截取整个窗口或全屏。
        :return: 一个包含详细截图信息的 CaptureResult 对象。
        """
        # --- 【优化】重构截图主逻辑 ---
        # 1. 如果没有目标标题，直接全屏截图
        if not self.target_title:
            if rect:
                print("警告: 提供了截图区域 rect，但在全屏模式下将被忽略。")
            return self._capture_fullscreen()

        # 2. 检查缓存的句柄是否仍然有效
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            # 如果句柄无效（例如窗口已关闭），则尝试重新查找一次
            print(f"信息: 缓存的句柄无效或窗口已关闭，尝试重新查找 '{self.target_title}'...")
            self._update_hwnd()

        # 3. 如果句柄有效，则执行窗口截图
        if self.hwnd:
            if win32gui.IsIconic(self.hwnd):
                print(f"信息: 窗口 '{self.target_title}' 已最小化。正在后台恢复...")
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                win32gui.SetWindowPos(self.hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                                      win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
                time.sleep(0.2)

            return self._capture_window(self.hwnd, sub_rect=rect)

        # 4. 如果最终还是没有有效句柄，则降级为全屏截图
        else:
            print(f"警告: 找不到标题为 '{self.target_title}' 的窗口，将进行全屏截图。")
            return self._capture_fullscreen()



# src/core/app_provider_service.py

from contextlib import contextmanager

from packages.aura_system_services.services.config_service import ConfigService
# 从我们的硬件抽象层导入必要的类
from packages.aura_system_services.services.screen_service import ScreenService, CaptureResult
from packages.aura_system_services.services.controller_service import ControllerService
from packages.aura_shared_utils.utils.logger import logger

class AppProviderService:
    """
    一个高级的应用窗口交互器 (Interactor)。
    它封装了针对单个目标窗口的 ScreenService 和 ControllerService 操作，
    并自动处理窗口相对坐标到屏幕全局坐标的转换，
    为上层行为和插件提供一个稳定、简洁的API。
    """

    def __init__(self, config: 'ConfigService'):
        """
        初始化一个与特定窗口绑定的交互器。

        :param window_title: 目标应用程序的窗口标题。
        """
        self.window_title = config.get('target_window', None)
        if not self.window_title:
            raise ValueError("AppProvider初始化失败：在配置中找不到 'target_window'。")

        self.screen = ScreenService(self.window_title)
        self.controller = ControllerService()
        logger.info(f"AppProviderService 服务已为窗口 '{self.window_title}' 准备就绪。")

    def _to_global_coords(self, relative_x: int, relative_y: int) -> tuple[int, int] | None:
        """
        [核心] 将窗口内的相对坐标转换为屏幕全局坐标。

        :param relative_x: 窗口内的相对x坐标。
        :param relative_y: 窗口内的相对y坐标。
        :return: (全局x, 全局y) 元组，如果窗口找不到则返回 None。
        """
        # 使用我们为Screen类新增的轻量级方法
        client_rect = self.screen.get_client_rect()
        if client_rect:
            # client_rect 返回的是 (客户区左上角x, 客户区左上角y, 宽度, 高度)
            client_x, client_y, _, _ = client_rect

            # 直接将相对坐标加到客户区的左上角全局坐标上
            return client_x + relative_x, client_y + relative_y

        logger.warning("无法转换到全局坐标，因为找不到窗口客户区。")
        return None

    # --- 封装后的高级API ---

    def capture(self, rect: tuple[int, int, int, int] | None = None) -> CaptureResult:
        """
        截取窗口内的图像。坐标系已经是相对的。
        这个方法可以直接委托给 self.screen。

        :param rect: (可选) 一个元组 (x, y, w, h)，定义在窗口客户区内要截取的子区域。
        :return: 一个 CaptureResult 对象。
        """
        return self.screen.capture(rect)

    def move_to(self, x: int, y: int, duration: float = 0.25):
        """平滑移动到窗口内的指定相对坐标。"""
        global_coords = self._to_global_coords(x, y)
        if global_coords:
            self.controller.move_to(global_coords[0], global_coords[1], duration)
        else:
            raise RuntimeError(f"无法定位窗口 '{self.window_title}'，移动失败。")

    def click(self, x: int, y: int, button: str = 'left', clicks: int = 1, interval: float = 0.1):
        """
        在窗口内的指定相对坐标进行点击。
        """
        global_coords = self._to_global_coords(x, y)
        if global_coords:
            self.controller.click(global_coords[0], global_coords[1], button, clicks, interval)
        else:
            raise RuntimeError(f"无法定位窗口 '{self.window_title}'，点击失败。")

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, button: str = 'left', duration: float = 0.5):
        """
        在窗口内从一个相对坐标拖拽到另一个相对坐标。
        """
        global_start = self._to_global_coords(start_x, start_y)
        global_end = self._to_global_coords(end_x, end_y)

        if global_start and global_end:
            # 先移动到起点
            self.controller.move_to(global_start[0], global_start[1], duration=0.1)
            # 再执行拖拽
            self.controller.drag_to(global_end[0], global_end[1], button, duration)
        else:
            raise RuntimeError(f"无法定位窗口 '{self.window_title}'，拖拽失败。")

    def scroll(self, amount: int, direction: str = 'down'):
        """
        在当前鼠标位置滚动鼠标滚轮（此操作通常是全局的，但为方便统一API而放在这里）。
        """
        self.controller.scroll(amount, direction)

    def press_key(self, key: str, presses: int = 1, interval: float = 0.1):
        """
        模拟一次按键（按下并释放）。
        注意：键盘事件通常发送给当前拥有焦点的窗口。
        """
        self.controller.press_key(key, presses, interval)

    def move_relative(self, dx: int, dy: int, duration: float = 0.2):
        """
        从当前鼠标位置相对移动鼠标。
        这个操作不依赖于窗口位置，直接委托给控制器。
        """
        # 注意：相对移动不需要坐标转换，它基于鼠标当前位置
        self.controller.move_relative(dx, dy, duration)

    def key_down(self, key: str):
        """
        按下并保持一个键盘按键。
        键盘事件通常发送给当前拥有焦点的窗口。
        """
        # 确保窗口焦点 (如果可能)
        if not self.screen.focus():
            logger.warning(f"无法自动激活窗口 '{self.window_title}'。将尝试直接按下按键，请确保窗口已手动置顶。")
        self.controller.key_down(key)

    def key_up(self, key: str):
        """
        松开一个之前被按下的键盘按键。
        """
        # 确保窗口焦点 (如果可能)
        if not self.screen.focus():
            logger.warning(f"无法自动激活窗口 '{self.window_title}'。将尝试直接松开按键，请确保窗口已手动置顶。")
        self.controller.key_up(key)

    @contextmanager
    def hold_key(self, key: str):
        """
        一个上下文管理器，用于在代码块执行期间按住一个键。
        """
        try:
            self.controller.key_down(key)
            yield
        finally:
            self.controller.key_up(key)

    def release_all_keys(self):
        """安全地释放所有被控制器按下的键鼠。"""
        self.controller.release_all()

    def get_pixel_color(self, x: int, y: int) -> tuple[int, int, int]:
        """
        获取窗口内指定相对坐标的像素颜色。

        :param x: 窗口内的相对x坐标。
        :param y: 窗口内的相对y坐标。
        :return: (R, G, B) 颜色元组。
        """
        global_coords = self._to_global_coords(x, y)
        if global_coords:
            # 委托给 ScreenService 服务来执行实际的像素获取
            # 我们假设 ScreenService 类将有一个 get_pixel_color_at 方法
            return self.screen.get_pixel_color_at(global_coords[0], global_coords[1])
        else:
            raise RuntimeError(f"无法定位窗口 '{self.window_title}'，获取像素颜色失败。")

    def type_text(self, text: str, interval: float = 0.01):
        """
        在目标窗口中模拟真实的键盘输入。
        此方法会先尝试将窗口置顶，以确保输入焦点。

        :param text: 要输入的字符串。
        :param interval: 每个按键之间的延迟（秒）。
        """
        logger.info(f"准备向窗口 '{self.window_title}' 输入文本...")
        # 1. 关键步骤：确保窗口是活动的
        if not self.screen.focus():
            # 如果无法激活窗口，只记录一个警告而不是抛出异常
            # 因为有时窗口可能已经处于激活状态
            logger.warning(f"无法自动激活窗口 '{self.window_title}'。将尝试直接输入，请确保窗口已手动置顶。")

        # 2. 委托给 ControllerService 来执行实际的打字操作
        # 我们假设 ControllerService 类将有一个 type_text 方法
        self.controller.type_text(text, interval)
        logger.info(f"文本输入完成: '{text[:30]}...'")


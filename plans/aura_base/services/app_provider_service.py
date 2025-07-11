# plans/aura_base/services/app_provider_service.py (最终修正版)

from contextlib import contextmanager

from packages.aura_core.api import register_service
from packages.aura_shared_utils.utils.logger import logger
from .config_service import ConfigService
from .controller_service import ControllerService
from .screen_service import ScreenService, CaptureResult


@register_service(alias="app", public=True)
class AppProviderService:
    """
    一个高级的应用交互器 (Interactor)。
    它封装了针对单个目标窗口的 ScreenService 和 ControllerService 操作，
    并自动处理窗口相对坐标到屏幕全局坐标的转换。
    """

    # 【【【核心修正 1/2：简化构造函数】】】
    def __init__(self, config: ConfigService, screen: ScreenService, controller: ControllerService):
        """
        初始化一个与特定窗口绑定的交互器。
        它不再负责配置ScreenService，因为ScreenService在被注入时已经通过依赖注入自行配置完毕。
        """
        self.config = config
        self.screen = screen
        self.controller = controller

        # 【关键】AppProviderService 也从统一的配置路径获取窗口标题，用于日志和错误信息。
        # 它不再需要手动设置 ScreenService 的目标。
        self.window_title = self.config.get('app.target_window_title', None)

        if self.window_title:
            logger.info(f"AppProviderService 服务已为窗口 '{self.window_title}' 准备就绪。")
        else:
            logger.info("AppProviderService 服务已在无目标（全屏）模式下准备就绪。")

    def _to_global_coords(self, relative_x: int, relative_y: int) -> tuple[int, int] | None:
        client_rect = self.screen.get_client_rect()
        if client_rect:
            client_x, client_y, _, _ = client_rect
            return client_x + relative_x, client_y + relative_y
        logger.warning("无法转换到全局坐标，因为找不到窗口客户区。")
        return None

    # --- 封装后的高级API ---
    # 【【【核心修正 2/2：所有方法中的错误信息都使用 self.window_title】】】

    def capture(self, rect: tuple[int, int, int, int] | None = None) -> CaptureResult:
        return self.screen.capture(rect)

    def move_to(self, x: int, y: int, duration: float = 0.25):
        global_coords = self._to_global_coords(x, y)
        if global_coords:
            self.controller.move_to(global_coords[0], global_coords[1], duration)
        else:
            raise RuntimeError(f"无法定位窗口 '{self.window_title or '未指定'}'，移动失败。")

    def click(self, x: int, y: int, button: str = 'left', clicks: int = 1, interval: float = 0.1):
        global_coords = self._to_global_coords(x, y)
        if global_coords:
            self.controller.click(global_coords[0], global_coords[1], button, clicks, interval)
        else:
            raise RuntimeError(f"无法定位窗口 '{self.window_title or '未指定'}'，点击失败。")

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, button: str = 'left', duration: float = 0.5):
        global_start = self._to_global_coords(start_x, start_y)
        global_end = self._to_global_coords(end_x, end_y)
        if global_start and global_end:
            self.controller.move_to(global_start[0], global_start[1], duration=0.1)
            self.controller.drag_to(global_end[0], global_end[1], button, duration)
        else:
            raise RuntimeError(f"无法定位窗口 '{self.window_title or '未指定'}'，拖拽失败。")

    # ... (从 scroll 到文件末尾的其他方法，除了错误信息外，基本不变) ...
    def scroll(self, amount: int, direction: str = 'down'):
        self.controller.scroll(amount, direction)

    def press_key(self, key: str, presses: int = 1, interval: float = 0.1):
        self.controller.press_key(key, presses, interval)

    def move_relative(self, dx: int, dy: int, duration: float = 0.2):
        self.controller.move_relative(dx, dy, duration)

    def key_down(self, key: str):
        if not self.screen.focus():
            logger.warning(f"无法自动激活窗口 '{self.window_title or '未指定'}'。将尝试直接按下按键。")
        self.controller.key_down(key)

    def key_up(self, key: str):
        if not self.screen.focus():
            logger.warning(f"无法自动激活窗口 '{self.window_title or '未指定'}'。将尝试直接松开按键。")
        self.controller.key_up(key)

    @contextmanager
    def hold_key(self, key: str):
        try:
            self.controller.key_down(key)
            yield
        finally:
            self.controller.key_up(key)

    def release_all_keys(self):
        self.controller.release_all()

    def get_pixel_color(self, x: int, y: int) -> tuple[int, int, int]:
        global_coords = self._to_global_coords(x, y)
        if global_coords:
            return self.screen.get_pixel_color_at(global_coords[0], global_coords[1])
        else:
            raise RuntimeError(f"无法定位窗口 '{self.window_title or '未指定'}'，获取像素颜色失败。")

    def type_text(self, text: str, interval: float = 0.01):
        logger.info(f"准备向窗口 '{self.window_title or '未知'}' 输入文本...")
        if not self.screen.focus():
            logger.warning(f"无法自动激活窗口 '{self.window_title or '未指定'}'。将尝试直接输入。")
        self.controller.type_text(text, interval)
        logger.info(f"文本输入完成: '{text[:30]}...'")

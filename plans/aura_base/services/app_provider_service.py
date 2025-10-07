"""
提供一个高级的应用交互服务 `AppProviderService`。

该服务作为与特定目标应用程序交互的高级门面（Facade），它组合了底层的
`ScreenService` 和 `ControllerService`，提供了更贴近用户操作的接口
（如点击窗口内的相对坐标、输入文本等）。

此服务的一个关键特性是它提供了一套完全同步的公共接口，使得在编写
自动化脚本时可以采用更简单直观的同步方式。而在其内部，所有操作都
被桥接到异步核心实现，确保了在 Aura 框架的异步环境中不会产生阻塞。
"""
import asyncio
import threading
from contextlib import contextmanager, asynccontextmanager
from typing import Optional, Tuple, Any, Generator

from packages.aura_core.api import register_service
from packages.aura_core.logger import logger
from .config_service import ConfigService
from .controller_service import ControllerService
from .screen_service import ScreenService, CaptureResult


@register_service(alias="app", public=True)
class AppProviderService:
    """
    一个高级的应用交互器 (Interactor)。

    此类服务对外提供一套简洁的同步接口，用于与目标应用程序进行交互。
    它负责处理窗口坐标转换、组合低级服务等复杂逻辑。其内部实现是
    完全异步的，通过一个桥接器来确保与框架的异步核心兼容。

    Attributes:
        config (ConfigService): 配置服务实例，用于获取目标窗口标题等设置。
        screen (ScreenService): 屏幕服务实例，用于截图和窗口信息获取。
        controller (ControllerService): 控制器服务实例，用于模拟鼠标和键盘操作。
        window_title (Optional[str]): 缓存的目标窗口标题。
    """

    def __init__(self, config: ConfigService, screen: ScreenService, controller: ControllerService):
        """
        初始化应用提供者服务。

        Args:
            config: 注入的配置服务。
            screen: 注入的屏幕服务。
            controller: 注入的控制器服务。
        """
        self.config = config
        self.screen = screen
        self.controller = controller
        self.window_title: Optional[str] = None


        # --- 桥接器组件 ---
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_lock = threading.Lock()

    # =========================================================================
    # Section 1: 公共同步接口
    # =========================================================================

    def _get_window_title(self) -> Optional[str]:
        """从配置中获取并缓存目标窗口的标题。"""
        self.window_title = self.config.get('app.target_window_title')
        return self.window_title


    def capture(self, rect: Optional[Tuple[int, int, int, int]] = None) -> CaptureResult:
        """
        捕获屏幕截图。

        Args:
            rect: 一个可选的元组 (x, y, width, height)，定义了要捕获的区域。
                  如果为 None，则捕获整个目标窗口的客户区。

        Returns:
            一个包含截图图像和元数据的 `CaptureResult` 对象。
        """
        return self.screen.capture(rect)

    def get_window_size(self) -> Optional[Tuple[int, int]]:
        """
        获取目标窗口的客户区尺寸。

        Returns:
            一个包含 (宽度, 高度) 的元组，如果找不到窗口则返回 None。
        """
        rect = self.screen.get_client_rect()
        return (rect[2], rect[3]) if rect else None

    def move_to(self, x: int, y: int, duration: float = 0.25):
        """
        将鼠标平滑移动到目标窗口内的指定相对坐标。

        Args:
            x: 目标点的窗口内 x 坐标。
            y: 目标点的窗口内 y 坐标。
            duration: 移动过程的持续时间（秒）。
        """
        return self._submit_to_loop_and_wait(self.move_to_async(x, y, duration))

    def click(self, x: int, y: int, button: str = 'left', clicks: int = 1, interval: float = 0.1):
        """
        在目标窗口内的指定相对坐标处执行鼠标点击。

        Args:
            x: 点击点的窗口内 x 坐标。
            y: 点击点的窗口内 y 坐标。
            button: 'left', 'right', 或 'middle'。
            clicks: 点击次数。
            interval: 多次点击之间的间隔时间（秒）。
        """
        return self._submit_to_loop_and_wait(self.click_async(x, y, button, clicks, interval))

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, button: str = 'left', duration: float = 0.5):
        """
        在目标窗口内执行拖拽操作。

        Args:
            start_x: 拖拽起点的 x 坐标。
            start_y: 拖拽起点的 y 坐标。
            end_x: 拖拽终点的 x 坐标。
            end_y: 拖拽终点的 y 坐标。
            button: 用于拖拽的鼠标按键。
            duration: 拖拽过程的持续时间（秒）。
        """
        return self._submit_to_loop_and_wait(self.drag_async(start_x, start_y, end_x, end_y, button, duration))

    def scroll(self, amount: int, direction: str = 'down'):
        """
        在目标窗口中执行鼠标滚轮滚动。

        Args:
            amount: 滚动的量（单位通常是滚轮的“咔哒”声次数）。
            direction: 'up' 或 'down'。
        """
        return self.controller.scroll(amount, direction)

    def press_key(self, key: str, presses: int = 1, interval: float = 0.1):
        """
        在目标窗口中模拟按键。

        Args:
            key: 要按下的键的名称（例如 'enter', 'a', 'ctrl'）。
            presses: 按键次数。
            interval: 多次按键之间的间隔时间（秒）。
        """
        return self.controller.press_key(key, presses, interval)

    def move_relative(self, dx: int, dy: int, duration: float = 0.2):
        """
        相对于当前鼠标位置移动鼠标。

        Args:
            dx: x 方向的移动距离。
            dy: y 方向的移动距离。
            duration: 移动过程的持续时间（秒）。
        """
        return self.controller.move_relative(dx, dy, duration)

    def key_down(self, key: str):
        """
        模拟按下某个按键并保持。

        Args:
            key: 要按下的键的名称。
        """
        return self._submit_to_loop_and_wait(self.key_down_async(key))

    def key_up(self, key: str):
        """
        模拟松开某个按键。

        Args:
            key: 要松开的键的名称。
        """
        return self._submit_to_loop_and_wait(self.key_up_async(key))

    @contextmanager
    def hold_key(self, key: str) -> Generator[None, None, None]:
        """
        一个上下文管理器，用于在代码块执行期间按住一个键。

        示例:
            with app.hold_key('shift'):
                app.click(100, 100)  # 此点击将伴随着 Shift 键按下

        Args:
            key: 要按住的键。
        """
        try:
            self.key_down(key)
            yield
        finally:
            self.key_up(key)

    def release_all_keys(self):
        """释放所有当前被模拟按下的按键。"""
        return self.controller.release_all()

    def get_pixel_color(self, x: int, y: int) -> Tuple[int, int, int]:
        """
        获取目标窗口内指定相对坐标的像素颜色。

        Args:
            x: 目标点的窗口内 x 坐标。
            y: 目标点的窗口内 y 坐标。

        Returns:
            一个包含 (R, G, B) 值的元组。
        """
        return self._submit_to_loop_and_wait(self.get_pixel_color_async(x, y))

    def type_text(self, text: str, interval: float = 0.01):
        """
        在目标窗口中模拟输入一段文本。

        Args:
            text: 要输入的文本。
            interval: 每个字符之间的输入间隔时间（秒）。
        """
        return self._submit_to_loop_and_wait(self.type_text_async(text, interval))

    # =========================================================================
    # Section 2: 内部异步核心实现
    # =========================================================================

    async def _to_global_coords_async(self, relative_x: int, relative_y: int) -> Optional[Tuple[int, int]]:
        """将窗口内的相对坐标异步转换为屏幕全局坐标。"""
        client_rect = await asyncio.to_thread(self.screen.get_client_rect)
        if client_rect:
            client_x, client_y, _, _ = client_rect
            return client_x + relative_x, client_y + relative_y
        logger.warning("无法转换到全局坐标，因为找不到窗口客户区。")
        return None

    async def move_to_async(self, x: int, y: int, duration: float = 0.25):
        """异步地将鼠标移动到目标窗口内的指定相对坐标。"""
        window_title = self._get_window_title()
        global_coords = await self._to_global_coords_async(x, y)
        if global_coords:
            await self.controller.move_to_async(global_coords[0], global_coords[1], duration)
        else:
            raise RuntimeError(f"无法定位窗口 '{window_title or '未指定'}'，移动失败。")

    async def click_async(self, x: int, y: int, button: str = 'left', clicks: int = 1, interval: float = 0.1):
        """异步地在目标窗口内的指定相对坐标处执行点击。"""
        global_coords = await self._to_global_coords_async(x, y)
        if global_coords:
            await self.controller.click_async(global_coords[0], global_coords[1], button, clicks, interval)
        else:
            raise RuntimeError(f"无法定位窗口 '{self._get_window_title() or '未指定'}'，点击失败。")

    async def drag_async(self, start_x: int, start_y: int, end_x: int, end_y: int, button: str = 'left',
                         duration: float = 0.5):
        """异步地在目标窗口内执行拖拽。"""
        global_start, global_end = await asyncio.gather(
            self._to_global_coords_async(start_x, start_y),
            self._to_global_coords_async(end_x, end_y)
        )
        if global_start and global_end:
            await self.controller.move_to_async(global_start[0], global_start[1], duration=0.1)
            await self.controller.drag_to_async(global_end[0], global_end[1], button, duration)
        else:
            raise RuntimeError(f"无法定位窗口 '{self._get_window_title() or '未指定'}'，拖拽失败。")

    async def key_down_async(self, key: str):
        """异步地模拟按下按键，会先尝试激活目标窗口。"""
        focused = await self.screen.focus_async()
        if not focused:
            logger.warning(f"无法自动激活窗口 '{self._get_window_title() or '未指定'}'。将尝试直接按下按键。")
        await self.controller.key_down_async(key)

    async def key_up_async(self, key: str):
        """异步地模拟松开按键，会先尝试激活目标窗口。"""
        focused = await self.screen.focus_async()
        if not focused:
            logger.warning(f"无法自动激活窗口 '{self._get_window_title() or '未指定'}'。将尝试直接松开按键。")
        await self.controller.key_up_async(key)

    @asynccontextmanager
    async def hold_key_async(self, key: str) -> AsyncGenerator[None, None]:
        """一个异步上下文管理器，用于在异步代码块执行期间按住一个键。"""
        try:
            await self.key_down_async(key)
            yield
        finally:
            await self.key_up_async(key)

    async def get_pixel_color_async(self, x: int, y: int) -> Tuple[int, int, int]:
        """异步地获取窗口内指定点的像素颜色。"""
        global_coords = await self._to_global_coords_async(x, y)
        if global_coords:
            return await asyncio.to_thread(self.screen.get_pixel_color_at, global_coords[0], global_coords[1])
        else:
            raise RuntimeError(f"无法定位窗口 '{self._get_window_title() or '未指定'}'，获取像素颜色失败。")

    async def type_text_async(self, text: str, interval: float = 0.01):
        """异步地模拟输入文本，会先尝试激活目标窗口。"""
        logger.info(f"准备向窗口 '{self._get_window_title() or '未知'}' 异步输入文本...")
        focused = await self.screen.focus_async()
        if not focused:
            logger.warning(f"无法自动激活窗口 '{self._get_window_title() or '未指定'}'。将尝试直接输入。")
        await self.controller.type_text_async(text, interval)
        logger.info(f"异步文本输入完成: '{text[:30]}...'")

    # =========================================================================
    # Section 3: 同步/异步桥接器
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
                    raise RuntimeError("AppProviderService 无法找到正在运行的 asyncio 事件循环。")
            return self._loop

    def _submit_to_loop_and_wait(self, coro: asyncio.Future) -> Any:
        """
        将一个协程从同步代码提交到事件循环，并阻塞地等待其结果。

        这是实现同步接口、异步核心的关键桥接方法。

        Args:
            coro: 要在事件循环中执行的协程。

        Returns:
            协程的执行结果。
        """
        loop = self._get_running_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()

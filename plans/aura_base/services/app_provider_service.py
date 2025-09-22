# plans/aura_base/services/app_provider_service.py (异步升级版)

import asyncio
import threading
from contextlib import contextmanager, asynccontextmanager
from typing import Optional, Tuple, Any

from packages.aura_core.api import register_service
from packages.aura_core.logger import logger
from .config_service import ConfigService
from .controller_service import ControllerService
from .screen_service import ScreenService, CaptureResult


@register_service(alias="app", public=True)
class AppProviderService:
    """
    【异步升级版】一个高级的应用交互器 (Interactor)。
    - 对外保持100%兼容的同步接口。
    - 内部调用底层服务的异步核心，实现完全的非阻塞操作。
    """

    def __init__(self, config: ConfigService, screen: ScreenService, controller: ControllerService):
        self.config = config
        self.screen = screen
        self.controller = controller
        self.window_title = None


        # --- 桥接器组件 ---
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()

    # =========================================================================
    # Section 1: 公共同步接口
    # =========================================================================

    def _get_window_title(self) -> Optional[str]:
        self.window_title = self.config.get('app.target_window_title')
        return self.window_title


    def capture(self, rect: Optional[Tuple[int, int, int, int]] = None) -> CaptureResult:
        # ScreenService 已经有桥接器，直接调用即可
        return self.screen.capture(rect)

    def get_window_size(self) -> Optional[Tuple[int, int]]:
        # 快速同步调用
        rect = self.screen.get_client_rect()
        return (rect[2], rect[3]) if rect else None

    def move_to(self, x: int, y: int, duration: float = 0.25):
        return self._submit_to_loop_and_wait(self.move_to_async(x, y, duration))

    def click(self, x: int, y: int, button: str = 'left', clicks: int = 1, interval: float = 0.1):
        return self._submit_to_loop_and_wait(self.click_async(x, y, button, clicks, interval))

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, button: str = 'left', duration: float = 0.5):
        return self._submit_to_loop_and_wait(self.drag_async(start_x, start_y, end_x, end_y, button, duration))

    def scroll(self, amount: int, direction: str = 'down'):
        # ControllerService 已经有桥接器
        return self.controller.scroll(amount, direction)

    def press_key(self, key: str, presses: int = 1, interval: float = 0.1):
        # ControllerService 已经有桥接器
        return self.controller.press_key(key, presses, interval)

    def move_relative(self, dx: int, dy: int, duration: float = 0.2):
        # ControllerService 已经有桥接器
        return self.controller.move_relative(dx, dy, duration)

    def key_down(self, key: str):
        return self._submit_to_loop_and_wait(self.key_down_async(key))

    def key_up(self, key: str):
        return self._submit_to_loop_and_wait(self.key_up_async(key))

    @contextmanager
    def hold_key(self, key: str):
        # 同步上下文管理器需要特殊处理
        try:
            self.key_down(key)
            yield
        finally:
            self.key_up(key)

    def release_all_keys(self):
        return self.controller.release_all()

    def get_pixel_color(self, x: int, y: int) -> tuple[int, int, int]:
        return self._submit_to_loop_and_wait(self.get_pixel_color_async(x, y))

    def type_text(self, text: str, interval: float = 0.01):
        return self._submit_to_loop_and_wait(self.type_text_async(text, interval))

    # =========================================================================
    # Section 2: 内部异步核心实现
    # =========================================================================

    async def _to_global_coords_async(self, relative_x: int, relative_y: int) -> tuple[int, int] | None:
        client_rect = await asyncio.to_thread(self.screen.get_client_rect)
        if client_rect:
            client_x, client_y, _, _ = client_rect
            return client_x + relative_x, client_y + relative_y
        logger.warning("无法转换到全局坐标，因为找不到窗口客户区。")
        return None

    async def move_to_async(self, x: int, y: int, duration: float = 0.25):
        window_title = self._get_window_title()
        global_coords = await self._to_global_coords_async(x, y)
        if global_coords:
            await self.controller.move_to_async(global_coords[0], global_coords[1], duration)
        else:
            raise RuntimeError(f"无法定位窗口 '{window_title or '未指定'}'，移动失败。")

    async def click_async(self, x: int, y: int, button: str = 'left', clicks: int = 1, interval: float = 0.1):
        global_coords = await self._to_global_coords_async(x, y)
        if global_coords:
            await self.controller.click_async(global_coords[0], global_coords[1], button, clicks, interval)
        else:
            raise RuntimeError(f"无法定位窗口 '{self._get_window_title() or '未指定'}'，点击失败。")

    async def drag_async(self, start_x: int, start_y: int, end_x: int, end_y: int, button: str = 'left',
                         duration: float = 0.5):
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
        focused = await self.screen.focus_async()
        if not focused:
            logger.warning(f"无法自动激活窗口 '{self._get_window_title() or '未指定'}'。将尝试直接按下按键。")
        await self.controller.key_down_async(key)

    async def key_up_async(self, key: str):
        focused = await self.screen.focus_async()
        if not focused:
            logger.warning(f"无法自动激活窗口 '{self._get_window_title() or '未指定'}'。将尝试直接松开按键。")
        await self.controller.key_up_async(key)

    @asynccontextmanager
    async def hold_key_async(self, key: str):
        try:
            await self.key_down_async(key)
            yield
        finally:
            await self.key_up_async(key)

    async def get_pixel_color_async(self, x: int, y: int) -> tuple[int, int, int]:
        global_coords = await self._to_global_coords_async(x, y)
        if global_coords:
            return await asyncio.to_thread(self.screen.get_pixel_color_at, global_coords[0], global_coords[1])
        else:
            raise RuntimeError(f"无法定位窗口 '{self._get_window_title() or '未指定'}'，获取像素颜色失败。")

    async def type_text_async(self, text: str, interval: float = 0.01):
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
        """线程安全地获取正在运行的事件循环。"""
        with self._loop_lock:
            if self._loop is None or self._loop.is_closed():
                from packages.aura_core.api import service_registry
                scheduler = service_registry.get_service_instance('scheduler')
                if scheduler and scheduler._loop and scheduler._loop.is_running():
                    self._loop = scheduler._loop
                else:
                    raise RuntimeError("AppProviderService无法找到正在运行的asyncio事件循环。")
            return self._loop

    def _submit_to_loop_and_wait(self, coro: asyncio.Future) -> Any:
        """将一个协程从同步代码提交到事件循环，并阻塞等待其结果。"""
        loop = self._get_running_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()

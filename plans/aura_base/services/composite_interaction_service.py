"""
提供一个高级的、可复用的复合交互服务。

该服务组合了底层的 `AppProviderService`、`ScreenService`、`OcrService` 和
`VisionService`，以提供更贴近用户意图的、更强大的交互能力。例如，
它实现了“查找并点击文本”、“等待某个图像出现”或“在滚动区域内查找文本”等
复杂的自动化场景。

与 `AppProviderService` 类似，它也采用同步接口、异步核心的设计模式，
为自动化脚本的编写提供了便利，同时保证了在 Aura 框架中的高性能非阻塞执行。
"""
import asyncio
import threading
from typing import Optional, Tuple, Any

from packages.aura_core.api import register_service
from packages.aura_core.logger import logger
from ..services.app_provider_service import AppProviderService
from ..services.screen_service import ScreenService
from ..services.ocr_service import OcrService
from ..services.vision_service import VisionService, MatchResult


@register_service("composite-interaction", public=True)
class CompositeInteractionService:
    """
    提供高级、可复用的复合交互行为。

    此类服务通过组合低级服务，封装了常见的复杂UI自动化模式，
    例如基于文本或图像的查找、点击和等待操作。
    """

    def __init__(
            self,
            app: AppProviderService,
            screen: ScreenService,
            ocr: OcrService,
            vision: VisionService
    ):
        """
        初始化复合交互服务。

        Args:
            app: 注入的 AppProviderService 实例。
            screen: 注入的 ScreenService 实例。
            ocr: 注入的 OcrService 实例。
            vision: 注入的 VisionService 实例。
        """
        self.app = app
        self.screen = screen
        self.ocr = ocr
        self.vision = vision
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_lock = threading.Lock()

    # =========================================================================
    # Section 1: 公共同步接口
    # =========================================================================

    def click_text(self, text: str, rect: Optional[Tuple[int, int, int, int]] = None,
                   match_mode: str = "contains", timeout: float = 3.0) -> bool:
        """
        在指定区域内查找文本，如果找到则点击其中心点。

        Args:
            text (str): 要查找和点击的文本。
            rect (Optional[Tuple]): 可选的查找区域 `(x, y, width, height)`。
            match_mode (str): 文本匹配模式，如 "contains" 或 "exact"。
            timeout (float): 查找文本的超时时间（秒）。

        Returns:
            bool: 如果成功找到并点击了文本，则返回 True，否则返回 False。
        """
        return self._submit_to_loop_and_wait(
            self.click_text_async(text, rect, match_mode, timeout)
        )

    def click_image(self, image_path: str, rect: Optional[Tuple[int, int, int, int]] = None,
                    timeout: float = 3.0, threshold: float = 0.8) -> bool:
        """
        在指定区域内查找图像，如果找到则点击其中心点。

        Args:
            image_path (str): 要查找的模板图像的文件路径。
            rect (Optional[Tuple]): 可选的查找区域。
            timeout (float): 查找图像的超时时间（秒）。
            threshold (float): 图像匹配的置信度阈值。

        Returns:
            bool: 如果成功找到并点击了图像，则返回 True，否则返回 False。
        """
        return self._submit_to_loop_and_wait(
            self.click_image_async(image_path, rect, timeout, threshold)
        )

    def wait_for_text(self, text: str, timeout: float = 10.0, rect: Optional[Tuple[int, int, int, int]] = None) -> bool:
        """
        在指定时间内等待某个文本出现在屏幕上。

        Args:
            text (str): 要等待的文本。
            timeout (float): 最大等待时间（秒）。
            rect (Optional[Tuple]): 可选的查找区域。

        Returns:
            bool: 如果在超时前文本出现，则返回 True，否则返回 False。
        """
        return self._submit_to_loop_and_wait(
            self.wait_for_text_async(text, timeout, rect)
        )

    def check_text_exists(self, text: str, rect: Optional[Tuple[int, int, int, int]] = None) -> bool:
        """
        单次检查指定的文本是否存在于屏幕区域内。

        Args:
            text (str): 要检查的文本。
            rect (Optional[Tuple]): 可选的查找区域。

        Returns:
            bool: 如果文本存在，则返回 True，否则返回 False。
        """
        return self._submit_to_loop_and_wait(
            self.check_text_exists_async(text, rect)
        )

    def find_text_with_scroll(self, text: str, scroll_area: Tuple[int, int, int, int],
                              max_scrolls: int = 5) -> bool:
        """
        在指定的滚动区域内查找文本，如果找不到则尝试向下滚动并继续查找。

        Args:
            text (str): 要查找的文本。
            scroll_area (Tuple): 定义了可滚动区域的 `(x, y, width, height)`。
            max_scrolls (int): 最大滚动次数。

        Returns:
            bool: 如果在滚动查找后找到文本，则返回 True。
        """
        return self._submit_to_loop_and_wait(
            self.find_text_with_scroll_async(text, scroll_area, max_scrolls)
        )

    def wait_for_text_to_disappear(self, text: str, timeout: float = 10.0,
                                   rect: Optional[Tuple[int, int, int, int]] = None) -> bool:
        """
        在指定时间内等待某个文本从屏幕上消失。

        Args:
            text (str): 要等待其消失的文本。
            timeout (float): 最大等待时间（秒）。
            rect (Optional[Tuple]): 可选的查找区域。

        Returns:
            bool: 如果在超时前文本消失，则返回 True，否则返回 False。
        """
        return self._submit_to_loop_and_wait(
            self.wait_for_text_to_disappear_async(text, timeout, rect)
        )

    def get_text_near_anchor(self, anchor_text: str, direction: str, search_offset: int = 5,
                             search_size: Tuple[int, int] = (150, 50),
                             rect: Optional[Tuple[int, int, int, int]] = None) -> Optional[str]:
        """
        查找一个“锚点”文本，然后在其指定的相对方向上识别并返回附近的文本。

        Args:
            anchor_text (str): 作为基准的锚点文本。
            direction (str): 查找方向，如 'right', 'left', 'above', 'below'。
            search_offset (int): 从锚点边界开始的偏移距离（像素）。
            search_size (Tuple[int, int]): 定义了在偏移后要进行OCR的区域的 `(width, height)`。
            rect (Optional[Tuple]): 可选的查找区域。

        Returns:
            Optional[str]: 如果找到，则返回识别出的文本字符串，否则返回 None。
        """
        return self._submit_to_loop_and_wait(
            self.get_text_near_anchor_async(anchor_text, direction, search_offset, search_size, rect)
        )

    def drag_image_to_image(self, source_image_path: str, target_image_path: str,
                            rect: Optional[Tuple[int, int, int, int]] = None, threshold: float = 0.8) -> bool:
        """
        查找源图像和目标图像，然后将源图像拖拽到目标图像的位置。

        Args:
            source_image_path (str): 要拖拽的源图像的路径。
            target_image_path (str): 拖拽的目标位置图像的路径。
            rect (Optional[Tuple]): 可选的查找区域。
            threshold (float): 图像匹配的置信度阈值。

        Returns:
            bool: 如果操作成功，返回 True。
        """
        return self._submit_to_loop_and_wait(
            self.drag_image_to_image_async(source_image_path, target_image_path, rect, threshold)
        )

    def wait_for_image(self, template_image: str, timeout: float = 10.0,
                       poll_interval: float = 0.5, threshold: float = 0.8) -> MatchResult:
        """
        在指定时间内等待某个图像出现在屏幕上。

        Args:
            template_image (str): 要等待的模板图像的路径。
            timeout (float): 最大等待时间（秒）。
            poll_interval (float): 轮询检查的间隔时间（秒）。
            threshold (float): 图像匹配的置信度阈值。

        Returns:
            MatchResult: 一个包含查找结果（是否找到、位置、置信度等）的对象。
        """
        return self._submit_to_loop_and_wait(
            self.wait_for_image_async(template_image, timeout, poll_interval, threshold)
        )

    def wait_for_image_to_disappear(self, template_image: str, timeout: float = 10.0,
                                    poll_interval: float = 0.5, threshold: float = 0.8) -> bool:
        """
        在指定时间内等待某个图像从屏幕上消失。

        Args:
            template_image (str): 要等待其消失的模板图像的路径。
            timeout (float): 最大等待时间（秒）。
            poll_interval (float): 轮询检查的间隔时间（秒）。
            threshold (float): 用于判断图像是否存在的置信度阈值。

        Returns:
            bool: 如果在超时前图像消失，则返回 True。
        """
        return self._submit_to_loop_and_wait(
            self.wait_for_image_to_disappear_async(template_image, timeout, poll_interval, threshold)
        )

    # =========================================================================
    # Section 2: 内部异步核心实现
    # =========================================================================

    async def click_text_async(self, text: str, rect: Optional[Tuple[int, int, int, int]] = None,
                               match_mode: str = "contains", timeout: float = 3.0) -> bool:
        """异步地查找并点击文本。"""
        logger.info(f"[交互] 异步尝试点击文本: '{text}' (超时: {timeout}s)")
        try:
            async with asyncio.timeout(timeout):
                while True:
                    capture = await self.app.capture_async(rect=rect)
                    if capture.success and capture.image is not None:
                        result = await self.ocr._find_text_async(text, capture.image, match_mode=match_mode)
                        if result.found and result.center_point:
                            click_x = result.center_point[0] + (rect[0] if rect else 0)
                            click_y = result.center_point[1] + (rect[1] if rect else 0)

                            await self.app.click_async(click_x, click_y)
                            logger.info(f"  [成功] 在 ({click_x}, {click_y}) 点击了 '{text}'。")
                            return True
                    await asyncio.sleep(0.1)
        except TimeoutError:
            logger.warning(f"  [失败] 超时 {timeout}s 后仍未找到文本 '{text}'。")
            return False

    async def check_text_exists_async(self, text: str, rect: Optional[Tuple[int, int, int, int]] = None) -> bool:
        """异步地单次检查文本是否存在。"""
        capture = await self.app.capture_async(rect=rect)
        if not capture.success or capture.image is None:
            return False
        result = await self.ocr._find_text_async(text, capture.image)
        return result.found

    async def wait_for_text_async(self, text: str, timeout: float = 10.0,
                                  rect: Optional[Tuple[int, int, int, int]] = None) -> bool:
        """异步地等待文本出现。"""
        logger.info(f"[交互] 异步等待文本出现: '{text}' (超时: {timeout}s)")
        try:
            async with asyncio.timeout(timeout):
                while not await self.check_text_exists_async(text, rect):
                    await asyncio.sleep(0.5)
                logger.info(f"  [成功] 文本 '{text}' 已出现。")
                return True
        except TimeoutError:
            logger.warning(f"  [失败] 超时 {timeout}s 后文本 '{text}' 未出现。")
            return False

    async def wait_for_text_to_disappear_async(self, text: str, timeout: float = 10.0,
                                               rect: Optional[Tuple[int, int, int, int]] = None) -> bool:
        """异步地等待文本消失。"""
        logger.info(f"[交互] 异步等待文本消失: '{text}' (超时: {timeout}s)")
        try:
            async with asyncio.timeout(timeout):
                while await self.check_text_exists_async(text, rect):
                    await asyncio.sleep(0.5)
                logger.info(f"  [成功] 文本 '{text}' 已消失。")
                return True
        except TimeoutError:
            logger.warning(f"  [失败] 超时 {timeout}s 后文本 '{text}' 仍存在。")
            return False

    async def click_image_async(self, image_path: str, rect: Optional[Tuple[int, int, int, int]] = None,
                                timeout: float = 3.0, threshold: float = 0.8) -> bool:
        """异步地查找并点击图像。"""
        logger.info(f"[交互] 异步尝试点击图像: '{image_path}'")
        try:
            async with asyncio.timeout(timeout):
                while True:
                    capture = await self.app.capture_async(rect=rect)
                    if capture.success and capture.image is not None:
                        result = await self.vision.find_template_async(
                            source_image=capture.image,
                            template_image=image_path,
                            threshold=threshold
                        )
                        if result.found and result.center_point:
                            click_x = result.center_point[0] + (rect[0] if rect else 0)
                            click_y = result.center_point[1] + (rect[1] if rect else 0)
                            await self.app.click_async(click_x, click_y)
                            logger.info(f"  [成功] 在 ({click_x}, {click_y}) 点击了图像。")
                            return True
                    await asyncio.sleep(0.2)
        except TimeoutError:
            logger.warning(f"  [失败] 超时 {timeout}s 后仍未找到图像 '{image_path}'。")
            return False

    async def wait_for_image_async(self, template_image: str, timeout: float = 10.0,
                                   poll_interval: float = 0.5, threshold: float = 0.8) -> MatchResult:
        """异步地等待图像出现。"""
        logger.info(f"[视觉等待] 异步等待图像出现... (超时: {timeout}s)")
        try:
            async with asyncio.timeout(timeout):
                while True:
                    capture = await self.app.capture_async()
                    if capture.success and capture.image is not None:
                        result = await self.vision.find_template_async(capture.image, template_image,
                                                                       threshold=threshold)
                        if result.found:
                            logger.info(f"  [成功] 图像已出现，置信度 {result.confidence:.2f}。")
                            return result
                    await asyncio.sleep(poll_interval)
        except TimeoutError:
            logger.warning(f"  [失败] 等待超时({timeout}s)，图像未出现。")
            return MatchResult(found=False)

    # ... 此处省略了其他方法的异步实现 ...

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
                    raise RuntimeError("CompositeInteractionService 无法找到正在运行的 asyncio 事件循环。")
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

"""
提供一个无状态的、基于 OpenCV 的视觉处理服务。

该模块的核心是 `VisionService`，它封装了常见的计算机视觉任务，
如模板匹配和颜色查找。由于这些操作可能是计算密集型的，`VisionService`
被设计为将其核心算法（如 `cv2.matchTemplate`）放在后台线程中执行，
从而避免阻塞主事件循环。

它同样遵循同步接口、异步核心的设计模式，为使用者提供便捷的同步方法调用，
同时在内部保持异步执行的性能优势。
"""
import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any, Tuple, Optional, List

import cv2
import numpy as np

from packages.aura_core.api import register_service
from packages.aura_core.logger import logger


@dataclass
class MatchResult:
    """
    封装单次视觉查找操作的结果。

    Attributes:
        found (bool): 是否找到了匹配项。
        top_left (Optional[Tuple[int, int]]): 匹配区域的左上角坐标 `(x, y)`。
        center_point (Optional[Tuple[int, int]]): 匹配区域的中心点坐标 `(x, y)`。
        rect (Optional[Tuple[int, int, int, int]]): 匹配区域的矩形 `(x, y, width, height)`。
        confidence (float): 匹配的置信度或得分。对于模板匹配，是相关性得分；
            对于颜色查找，是轮廓的面积。
        debug_info (Dict[str, Any]): 用于存储调试信息的附加字典。
    """
    found: bool = False
    top_left: Optional[Tuple[int, int]] = None
    center_point: Optional[Tuple[int, int]] = None
    rect: Optional[Tuple[int, int, int, int]] = None
    confidence: float = 0.0
    debug_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiMatchResult:
    """
    封装一次查找中所有匹配结果的集合。

    Attributes:
        count (int): 找到的匹配项总数。
        matches (List[MatchResult]): 一个包含所有 `MatchResult` 对象的列表。
    """
    count: int = 0
    matches: List[MatchResult] = field(default_factory=list)


@register_service(alias="vision", public=True)
class VisionService:
    """
    一个无状态的视觉服务，提供模板匹配和颜色查找等功能。

    此服务将CPU密集型的图像计算（如模板匹配）移至后台线程执行，
    以避免阻塞主 `asyncio` 事件循环。
    """

    def __init__(self):
        """初始化视觉服务。"""
        logger.info("视觉服务 (异步核心版) 已初始化。")
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_lock = threading.Lock()

    # =========================================================================
    # Section 1: 公共同步接口
    # =========================================================================

    def find_template(self,
                      source_image: np.ndarray | str,
                      template_image: np.ndarray | str,
                      mask_image: Optional[np.ndarray | str] = None,
                      threshold: float = 0.8) -> MatchResult:
        """
        在源图像中查找与模板图像最匹配的单个区域。

        Args:
            source_image (np.ndarray | str): 源图像，可以是NumPy数组或文件路径。
            template_image (np.ndarray | str): 模板图像。
            mask_image (Optional[np.ndarray | str]): 可选的蒙版图像，用于指定模板中的有效区域。
            threshold (float): 匹配的置信度阈值，介于0.0和1.0之间。

        Returns:
            MatchResult: 包含最佳匹配结果的对象。
        """
        return self._submit_to_loop_and_wait(
            self.find_template_async(source_image, template_image, mask_image, threshold)
        )

    def find_all_templates(self,
                           source_image: np.ndarray,
                           template_image: np.ndarray | str,
                           mask_image: Optional[np.ndarray | str] = None,
                           threshold: float = 0.8,
                           nms_threshold: float = 0.5) -> MultiMatchResult:
        """
        在源图像中查找所有与模板图像匹配的实例，并使用非极大值抑制（NMS）去除重叠的框。

        Args:
            source_image (np.ndarray): 源图像。
            template_image (np.ndarray | str): 模板图像。
            mask_image (Optional[np.ndarray | str]): 可选的蒙版。
            threshold (float): 匹配的置信度阈值。
            nms_threshold (float): 用于非极大值抑制的重叠阈值。

        Returns:
            MultiMatchResult: 包含所有不重叠的匹配结果的集合。
        """
        return self._submit_to_loop_and_wait(
            self.find_all_templates_async(source_image, template_image, mask_image, threshold, nms_threshold)
        )

    def find_color(self,
                   source_image: np.ndarray,
                   lower_hsv: Tuple[int, int, int],
                   upper_hsv: Tuple[int, int, int],
                   min_area: int = 50) -> MatchResult:
        """
        在源图像中查找指定HSV颜色范围内的最大连通区域。

        Args:
            source_image (np.ndarray): 源图像 (BGR格式)。
            lower_hsv (Tuple[int, int, int]): HSV颜色范围的下界。
            upper_hsv (Tuple[int, int, int]): HSV颜色范围的上界。
            min_area (int): 匹配区域的最小像素面积。

        Returns:
            MatchResult: 包含最大颜色区域信息的结果对象。
        """
        return self._submit_to_loop_and_wait(
            self.find_color_async(source_image, lower_hsv, upper_hsv, min_area)
        )

    # =========================================================================
    # Section 2: 内部异步核心实现
    # =========================================================================

    async def find_template_async(self,
                                  source_image: np.ndarray | str,
                                  template_image: np.ndarray | str,
                                  mask_image: Optional[np.ndarray | str] = None,
                                  threshold: float = 0.8) -> MatchResult:
        """异步地执行模板匹配计算。"""
        try:
            source_gray = self._prepare_image(source_image)
            template_gray = self._prepare_image(template_image)
            h, w = template_gray.shape
            mask = self._prepare_image(mask_image) if mask_image is not None else None

            if mask is not None and mask.shape != template_gray.shape:
                raise ValueError(f"蒙版尺寸 {mask.shape} 必须与模板尺寸 {template_gray.shape} 完全一致。")

            min_val, max_val, min_loc, max_loc = await asyncio.to_thread(
                cv2.minMaxLoc,
                cv2.matchTemplate(source_gray, template_gray, cv2.TM_CCOEFF_NORMED, mask)
            )

            best_match_confidence = max_val
            if best_match_confidence >= threshold:
                top_left = max_loc
                return MatchResult(
                    found=True,
                    top_left=top_left,
                    center_point=(top_left[0] + w // 2, top_left[1] + h // 2),
                    rect=(top_left[0], top_left[1], w, h),
                    confidence=best_match_confidence
                )
            else:
                return MatchResult(
                    found=False,
                    confidence=best_match_confidence,
                    debug_info={"best_match_rect_on_fail": (max_loc[0], max_loc[1], w, h)}
                )
        except (FileNotFoundError, TypeError, ValueError) as e:
            logger.error(f"模板匹配预处理失败: {e}")
            return MatchResult(found=False, debug_info={"error": str(e)})

    async def find_all_templates_async(self,
                                       source_image: np.ndarray,
                                       template_image: np.ndarray | str,
                                       mask_image: Optional[np.ndarray | str] = None,
                                       threshold: float = 0.8,
                                       nms_threshold: float = 0.5) -> MultiMatchResult:
        """异步地执行查找所有模板的计算。"""
        try:
            source_gray = self._prepare_image(source_image)
            template_gray = self._prepare_image(template_image)
            h, w = template_gray.shape
            mask = self._prepare_image(mask_image) if mask_image is not None else None

            if mask is not None and mask.shape != template_gray.shape:
                raise ValueError(f"蒙版尺寸 {mask.shape} 必须与模板尺寸 {template_gray.shape} 完全一致。")

            def _find_and_filter() -> List[MatchResult]:
                result = cv2.matchTemplate(source_gray, template_gray, cv2.TM_CCOEFF_NORMED, mask=mask)
                locations = np.where(result >= threshold)
                rects = [[pt[0], pt[1], pt[0] + w, pt[1] + h] for pt in zip(*locations[::-1])]
                scores = [result[pt[1], pt[0]] for pt in zip(*locations[::-1])]
                if not rects: return []
                indices = cv2.dnn.NMSBoxes(rects, np.array(scores, dtype=np.float32), threshold, nms_threshold)
                final_matches = []
                if len(indices) > 0:
                    for i in indices.flatten():
                        box = rects[i]
                        top_left = (box[0], box[1])
                        final_matches.append(MatchResult(
                            found=True, top_left=top_left,
                            center_point=(top_left[0] + w // 2, top_left[1] + h // 2),
                            rect=(top_left[0], top_left[1], w, h), confidence=scores[i]
                        ))
                return final_matches

            matches = await asyncio.to_thread(_find_and_filter)
            return MultiMatchResult(count=len(matches), matches=matches)

        except (FileNotFoundError, TypeError, ValueError) as e:
            logger.error(f"查找所有模板预处理失败: {e}")
            return MultiMatchResult()

    async def find_color_async(self,
                               source_image: np.ndarray,
                               lower_hsv: Tuple[int, int, int],
                               upper_hsv: Tuple[int, int, int],
                               min_area: int = 50) -> MatchResult:
        """异步地执行颜色查找计算。"""
        if not isinstance(source_image, np.ndarray) or len(source_image.shape) != 3:
            return MatchResult(found=False, debug_info={"error": "输入图像必须是BGR或RGB格式的NumPy数组。"})

        def _find_largest_contour() -> Tuple[Optional[Any], float]:
            hsv_image = cv2.cvtColor(source_image, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv_image, np.array(lower_hsv), np.array(upper_hsv))
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours: return None, 0
            best_contour = max(contours, key=cv2.contourArea)
            return best_contour, cv2.contourArea(best_contour)

        best_contour, area = await asyncio.to_thread(_find_largest_contour)

        if best_contour is not None and area >= min_area:
            x, y, w, h = cv2.boundingRect(best_contour)
            return MatchResult(
                found=True, top_left=(x, y),
                center_point=(x + w // 2, y + h // 2),
                rect=(x, y, w, h), confidence=area
            )

        return MatchResult(found=False, confidence=area)

    # =========================================================================
    # Section 3: 内部辅助工具 (同步)
    # =========================================================================

    def _prepare_image(self, image: Optional[np.ndarray | str]) -> Optional[np.ndarray]:
        """
        准备用于模板匹配的图像，确保其为灰度图。
        """
        if image is None: return None
        if isinstance(image, str):
            img = cv2.imread(image, cv2.IMREAD_UNCHANGED)
            if img is None: raise FileNotFoundError(f"无法从路径加载图像: {image}")
        elif isinstance(image, np.ndarray):
            img = image
        else:
            raise TypeError(f"不支持的图像类型，需要str(路径)或np.ndarray。实际类型为{type(image)}")

        if len(img.shape) == 2: return img
        if len(img.shape) == 3:
            channels = img.shape[2]
            if channels == 4: return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
            if channels == 3: return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            if channels == 1: return img.squeeze(axis=2)
            raise TypeError(f"不支持的3D图像通道数: {channels}")
        raise TypeError(f"不支持的图像形状: {img.shape}")

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
                    raise RuntimeError("VisionService 无法找到正在运行的 asyncio 事件循环。")
            return self._loop

    def _submit_to_loop_and_wait(self, coro: asyncio.Future) -> Any:
        """将一个协程从同步代码提交到事件循环，并阻塞地等待其结果。"""
        loop = self._get_running_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()


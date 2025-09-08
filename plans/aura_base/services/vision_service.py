# src/notifier_services/vision_service.py (异步升级版)

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any, Tuple, Optional

import cv2
import numpy as np

from packages.aura_core.api import register_service
from packages.aura_core.logger import logger


# --- 返回值数据结构 (保持不变) ---

@dataclass
class MatchResult:
    found: bool = False
    top_left: tuple[int, int] | None = None
    center_point: tuple[int, int] | None = None
    rect: tuple[int, int, int, int] | None = None
    confidence: float = 0.0
    debug_info: dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiMatchResult:
    count: int = 0
    matches: list[MatchResult] = field(default_factory=list)


@register_service(alias="vision", public=True)
class VisionService:
    """
    【异步升级版】一个无状态的视觉服务。
    - 对外保持100%兼容的同步接口。
    - 内部将CPU密集型的图像计算移至后台线程执行，避免阻塞事件循环。
    """

    def __init__(self):
        logger.info("视觉服务 (异步核心版) 已初始化。")
        # --- 桥接器组件 ---
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()

    # =========================================================================
    # Section 1: 公共同步接口 (保持100%向后兼容)
    # =========================================================================

    def find_template(self,
                      source_image: np.ndarray | str,
                      template_image: np.ndarray | str,
                      mask_image: Optional[np.ndarray | str] = None,
                      threshold: float = 0.8) -> MatchResult:
        """【同步接口】在源图像中查找最匹配的单个模板。"""
        return self._submit_to_loop_and_wait(
            self.find_template_async(source_image, template_image, mask_image, threshold)
        )

    def find_all_templates(self,
                           source_image: np.ndarray,
                           template_image: np.ndarray | str,
                           mask_image: Optional[np.ndarray | str] = None,
                           threshold: float = 0.8,
                           nms_threshold: float = 0.5) -> MultiMatchResult:
        """【同步接口】在源图像中查找所有匹配的模板实例。"""
        return self._submit_to_loop_and_wait(
            self.find_all_templates_async(source_image, template_image, mask_image, threshold, nms_threshold)
        )

    def find_color(self,
                   source_image: np.ndarray,
                   lower_hsv: Tuple[int, int, int],
                   upper_hsv: Tuple[int, int, int],
                   min_area: int = 50) -> MatchResult:
        """【同步接口】在源图像中查找指定HSV颜色范围内的最大区域。"""
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
        """【异步内核】将模板匹配计算调度到后台线程。"""
        try:
            # 图像准备是快速的CPU操作，可以在调用前完成
            source_gray = self._prepare_image(source_image)
            template_gray = self._prepare_image(template_image)
            h, w = template_gray.shape
            mask = self._prepare_image(mask_image) if mask_image is not None else None

            if mask is not None and mask.shape != template_gray.shape:
                raise ValueError(f"蒙版尺寸 {mask.shape} 必须与模板尺寸 {template_gray.shape} 完全一致。")

            # 将阻塞的 cv2.matchTemplate 放入线程池
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
        """【异步内核】将查找所有模板的计算调度到后台线程。"""
        try:
            source_gray = self._prepare_image(source_image)
            template_gray = self._prepare_image(template_image)
            h, w = template_gray.shape
            mask = self._prepare_image(mask_image) if mask_image is not None else None

            if mask is not None and mask.shape != template_gray.shape:
                raise ValueError(f"蒙版尺寸 {mask.shape} 必须与模板尺寸 {template_gray.shape} 完全一致。")

            # 将核心计算部分放入后台线程
            def _find_and_filter():
                result = cv2.matchTemplate(source_gray, template_gray, cv2.TM_CCOEFF_NORMED, mask=mask)
                locations = np.where(result >= threshold)

                rects = [[pt[0], pt[1], pt[0] + w, pt[1] + h] for pt in zip(*locations[::-1])]
                scores = [result[pt[1], pt[0]] for pt in zip(*locations[::-1])]

                if not rects:
                    return []

                indices = cv2.dnn.NMSBoxes(rects, np.array(scores, dtype=np.float32), threshold, nms_threshold)

                final_matches = []
                if len(indices) > 0:
                    for i in indices.flatten():
                        box = rects[i]
                        top_left = (box[0], box[1])
                        final_matches.append(MatchResult(
                            found=True,
                            top_left=top_left,
                            center_point=(top_left[0] + w // 2, top_left[1] + h // 2),
                            rect=(top_left[0], top_left[1], w, h),
                            confidence=scores[i]
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
        """【异步内核】将颜色查找计算调度到后台线程。"""
        if not isinstance(source_image, np.ndarray) or len(source_image.shape) != 3:
            return MatchResult(found=False, debug_info={"error": "输入图像必须是BGR或RGB格式的NumPy数组。"})

        def _find_largest_contour():
            hsv_image = cv2.cvtColor(source_image, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv_image, np.array(lower_hsv), np.array(upper_hsv))
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            if not contours:
                return None, 0

            best_contour = max(contours, key=cv2.contourArea)
            return best_contour, cv2.contourArea(best_contour)

        best_contour, area = await asyncio.to_thread(_find_largest_contour)

        if best_contour is not None and area >= min_area:
            x, y, w, h = cv2.boundingRect(best_contour)
            return MatchResult(
                found=True,
                top_left=(x, y),
                center_point=(x + w // 2, y + h // 2),
                rect=(x, y, w, h),
                confidence=area
            )

        return MatchResult(found=False, confidence=area)

    # =========================================================================
    # Section 3: 内部辅助工具 (同步)
    # =========================================================================

    def _prepare_image(self, image: np.ndarray | str | None) -> np.ndarray | None:
        """
        准备用于模板匹配的图像，确保输出为标准的单通道2D灰度图。
        现在可以接受 None 并直接返回 None。
        """
        if image is None:
            return None

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
        """线程安全地获取正在运行的事件循环。"""
        with self._loop_lock:
            if self._loop is None or self._loop.is_closed():
                from packages.aura_core.api import service_registry
                scheduler = service_registry.get_service_instance('scheduler')
                if scheduler and scheduler._loop and scheduler._loop.is_running():
                    self._loop = scheduler._loop
                else:
                    raise RuntimeError("VisionService无法找到正在运行的asyncio事件循环。")
            return self._loop

    def _submit_to_loop_and_wait(self, coro: asyncio.Future) -> Any:
        """将一个协程从同步代码提交到事件循环，并阻塞等待其结果。"""
        loop = self._get_running_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()


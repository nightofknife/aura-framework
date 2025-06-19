# src/notifier_services/vision_service.py

import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import Any

# --- 返回值数据结构 ---

@dataclass
class MatchResult:
    """封装单次匹配操作的结果。"""
    found: bool = False
    # 匹配区域的左上角坐标 (x, y)
    top_left: tuple[int, int] | None = None
    # 匹配区域的中心点坐标 (x, y)
    center_point: tuple[int, int] | None = None
    # 匹配区域的矩形 (x, y, w, h)
    rect: tuple[int, int, int, int] | None = None
    # 匹配的置信度/相似度
    confidence: float = 0.0
    debug_info: dict[str, Any] = field(default_factory=dict)

@dataclass
class MultiMatchResult:
    """封装多次匹配操作的结果。"""
    count: int = 0
    # MatchResult 对象的列表
    matches: list[MatchResult] = field(default_factory=list)


class VisionService:
    """
    一个无状态的视觉服务，提供模板匹配和未来可能的特征匹配功能。
    所有方法都接收图像数据作为参数。
    """

    def __init__(self):
        print("视觉服务已初始化。")
        # 如果需要基于特征的匹配，可以在这里初始化检测器
        # self.detector = cv2.ORB_create(nfeatures=1000)
        # self.bf_matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

    def _prepare_image(self, image: np.ndarray | str) -> np.ndarray:
        """
        [内部辅助] 准备用于匹配的图像。
        :param image: 图像路径(str)或NumPy数组(BGR)。
        :return: 灰度图NumPy数组。
        """
        if isinstance(image, str):
            # 从路径加载，需要检查文件是否存在
            img = cv2.imread(image, cv2.IMREAD_GRAYSCALE)
            if img is None:
                raise FileNotFoundError(f"无法从路径加载图像: {image}")
            return img
        elif isinstance(image, np.ndarray):
            # 将传入的BGR或BGRA图像转为灰度图
            if len(image.shape) == 3:
                return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            return image  # 假设已经是灰度图
        else:
            raise TypeError("不支持的图像类型，需要str(路径)或np.ndarray。")

    def find_template(self,
                      source_image: np.ndarray,
                      template_image: np.ndarray | str,
                      threshold: float = 0.8) -> MatchResult:
        """
        【修改后】在源图像中查找最匹配的单个模板。
        无论成功与否，都会返回包含调试信息的结果。
        """
        try:
            source_gray = self._prepare_image(source_image)
            template_gray = self._prepare_image(template_image)
            h, w = template_gray.shape
        except (FileNotFoundError, TypeError) as e:
            print(f"错误: {e}")
            return MatchResult(found=False)

        result = cv2.matchTemplate(source_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        # 【关键修改】即使失败，也记录下最接近的匹配信息
        best_match_confidence = max_val
        best_match_rect = (max_loc[0], max_loc[1], w, h)

        if best_match_confidence >= threshold:
            top_left = max_loc
            center_x = top_left[0] + w // 2
            center_y = top_left[1] + h // 2
            return MatchResult(
                found=True,
                top_left=top_left,
                center_point=(center_x, center_y),
                rect=(top_left[0], top_left[1], w, h),
                confidence=best_match_confidence
            )
        else:
            # 失败了，但返回一个带有调试信息的失败结果
            return MatchResult(
                found=False,
                confidence=best_match_confidence,
                debug_info={
                    "best_match_rect_on_fail": best_match_rect
                }
            )

    def find_all_templates(self,
                           source_image: np.ndarray,
                           template_image: np.ndarray | str,
                           threshold: float = 0.8,
                           nms_threshold: float = 0.5) -> MultiMatchResult:
        """
        在源图像中查找所有匹配的模板实例。

        :param source_image: 在其中进行搜索的图像 (BGR或灰度图)。
        :param template_image: 要查找的模板图像 (路径或BGR/灰度图)。
        :param threshold: 匹配的置信度阈值。
        :param nms_threshold: 非极大值抑制(NMS)的重叠阈值，用于合并重叠的框。
        :return: 一个 MultiMatchResult 对象。
        """
        try:
            source_gray = self._prepare_image(source_image)
            template_gray = self._prepare_image(template_image)
            h, w = template_gray.shape
        except (FileNotFoundError, TypeError) as e:
            print(f"错误: {e}")
            return MultiMatchResult()

        result = cv2.matchTemplate(source_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= threshold)

        # 将结果打包成 (x, y, confidence) 的形式
        rects = []
        for pt in zip(*locations[::-1]):
            rects.append([pt[0], pt[1], pt[0] + w, pt[1] + h])

        scores = [result[pt[1], pt[0]] for pt in zip(*locations[::-1])]

        # 使用非极大值抑制来合并重叠的检测框
        indices = cv2.dnn.NMSBoxes(rects, np.array(scores, dtype=np.float32), threshold, nms_threshold)

        final_matches = []
        if len(indices) > 0:
            for i in indices.flatten():
                box = rects[i]
                top_left = (box[0], box[1])
                center_x = top_left[0] + w // 2
                center_y = top_left[1] + h // 2
                final_matches.append(MatchResult(
                    found=True,
                    top_left=top_left,
                    center_point=(center_x, center_y),
                    rect=(top_left[0], top_left[1], w, h),
                    confidence=scores[i]
                ))

        return MultiMatchResult(count=len(final_matches), matches=final_matches)


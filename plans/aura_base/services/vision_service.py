# src/notifier_services/vision_service.py

from dataclasses import dataclass, field
from typing import Any, Tuple, Optional

import cv2
import numpy as np

from packages.aura_core.api import register_service


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


@register_service(alias="vision", public=True)
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
        【最终加固版】准备用于模板匹配的图像，确保输出为标准的单通道2D灰度图。

        这个函数现在能够处理所有已知情况，包括您指出的PNG读取问题。

        :param image: 图像路径(str)或NumPy数组。
        :return: 标准的单通道2D灰度图 (H, W) NumPy 数组。
        """
        # 1. 统一输入：确保我们处理的是一个NumPy数组
        if isinstance(image, str):
            # 以“不变”模式加载，保留所有通道信息，让后续逻辑统一处理
            img = cv2.imread(image, cv2.IMREAD_UNCHANGED)
            if img is None:
                raise FileNotFoundError(f"无法从路径加载图像: {image}")
        elif isinstance(image, np.ndarray):
            img = image
        else:
            raise TypeError(f"不支持的图像类型，需要str(路径)或np.ndarray。实际类型为{type(image)}")

        # 2. 统一处理：将任何格式的NumPy数组转换为标准的2D灰度图 (H, W)

        # 检查是否已经是2D灰度图
        if len(img.shape) == 2:
            return img

        # 处理3D数组，这部分是关键
        if len(img.shape) == 3:
            height, width, channels = img.shape

            if channels == 4:
                # 4通道 BGRA -> 灰度
                return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
            elif channels == 3:
                # 3通道 BGR -> 灰度
                return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            elif channels == 1:
                # 处理您提到的 (H, W, 1) 特殊情况，将其压缩为 (H, W)
                return img.squeeze(axis=2)
            else:
                # 其他异常通道数的3D数组
                raise TypeError(f"不支持的3D图像通道数: {channels}")

        # 如果不是2D或3D，则是无法处理的形状
        raise TypeError(f"不支持的图像形状: {img.shape}")


    def find_template(self,
                      source_image: np.ndarray | str,
                      template_image: np.ndarray | str,
                      mask_image: Optional[np.ndarray | str] = None,
                      threshold: float = 0.8) -> MatchResult:
        """
        【修改后】在源图像中查找最匹配的单个模板。
        无论成功与否，都会返回包含调试信息的结果。
        """
        # try:
        source_gray = self._prepare_image(source_image)
        template_gray = self._prepare_image(template_image)
        h, w = template_gray.shape
        mask = None
        # 【新增】处理蒙版逻辑
        if mask_image is not None:
            mask = self._prepare_image(mask_image)
            if mask.shape != template_gray.shape:
                raise ValueError(f"蒙版尺寸 {mask.shape} 必须与模板尺寸 {template_gray.shape} 完全一致。")

        # except (FileNotFoundError, TypeError) as e:
        #     print(f"错误: {e}")
        #     return MatchResult(found=False,debug_info={"error": str(e)})
        # print(source_gray.shape,template_gray.shape)
        result = cv2.matchTemplate( image=source_gray,templ= template_gray,method= cv2.TM_CCOEFF_NORMED, mask=mask)
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
                           mask_image: Optional[np.ndarray | str] = None,
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
            mask = None
            # 【新增】处理蒙版逻辑
            if mask_image is not None:
                mask = self._prepare_image(mask_image)
                if mask.shape != template_gray.shape:
                    raise ValueError(f"蒙版尺寸 {mask.shape} 必须与模板尺寸 {template_gray.shape} 完全一致。")

        except (FileNotFoundError, TypeError, ValueError) as e:
            print(f"错误: {e}")
            return MultiMatchResult()

        result = cv2.matchTemplate(source_gray, template_gray, cv2.TM_CCOEFF_NORMED, mask=mask)
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

    def find_color(self,
                   source_image: np.ndarray,
                   lower_hsv: Tuple[int, int, int],
                   upper_hsv: Tuple[int, int, int],
                   min_area: int = 50) -> MatchResult:
        """
        在源图像中查找指定HSV颜色范围内的最大区域。

        :param source_image: 要搜索的图像 (BGR或RGB格式的NumPy数组)。
        :param lower_hsv: HSV颜色范围的下限 (H, S, V)。
        :param upper_hsv: HSV颜色范围的  上限 (H, S, V)。
        :param min_area: 匹配区域的最小像素面积，用于过滤噪点。
        :return: 一个 MatchResult 对象。
        """
        if not isinstance(source_image, np.ndarray) or len(source_image.shape) != 3:
            return MatchResult(found=False, debug_info={"error": "输入图像必须是BGR或RGB格式的NumPy数组。"})

        # 1. 转换到HSV色彩空间
        hsv_image = cv2.cvtColor(source_image, cv2.COLOR_BGR2HSV)

        # 2. 创建颜色掩码
        mask = cv2.inRange(hsv_image, np.array(lower_hsv), np.array(upper_hsv))

        # 3. 查找轮廓
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return MatchResult(found=False)

        # 4. 找到面积最大的轮廓
        best_contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(best_contour)

        # 5. 检查面积是否满足阈值
        if area >= min_area:
            x, y, w, h = cv2.boundingRect(best_contour)
            center_x = x + w // 2
            center_y = y + h // 2
            return MatchResult(
                found=True,
                top_left=(x, y),
                center_point=(center_x, center_y),
                rect=(x, y, w, h),
                confidence=area  # 使用面积作为一种置信度
            )

        return MatchResult(found=False, confidence=area)

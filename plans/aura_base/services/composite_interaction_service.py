# file: plans/your_plan/services/composite_interaction_service.py

import time
from typing import Optional, Tuple, List

from packages.aura_core.api import register_service
from .app_provider_service import AppProviderService
from .screen_service import ScreenService
from .ocr_service import OcrService, OcrResult
from .vision_service import VisionService


@register_service("composite-interaction", public=True)
class CompositeInteractionService:
    """
    提供高级、可复用的复合交互行为，封装底层OCR、视觉和控制操作。
    """

    def __init__(
            self,
            app: AppProviderService,
            screen: ScreenService,
            ocr: OcrService,
            vision: VisionService
    ):
        self.app = app
        self.screen = screen
        self.ocr = ocr
        self.vision = vision

    # ===================================================================
    # 已有方法 (无改动)
    # ===================================================================

    def click_text(
            self,
            text: str,
            region: Optional[Tuple[int, int, int, int]] = None,
            match_mode: str = "fuzzy",
            timeout: float = 3.0
    ) -> bool:
        """
        在指定区域和超时时间内查找并点击文本。这是最常用的复合行为。
        """
        print(f"[交互] 尝试点击文本: '{text}' (超时: {timeout}s)")
        start_time = time.time()
        while time.time() - start_time < timeout:
            capture = self.screen.capture(rect=region)
            if not capture.success or capture.image is None:
                time.sleep(0.2)
                continue

            result = self.ocr.find_text(text, capture.image, match_mode=match_mode)
            if result.found and result.center_point:
                click_x = result.center_point[0] + (region[0] if region else 0)
                click_y = result.center_point[1] + (region[1] if region else 0)

                self.app.click(click_x, click_y)
                print(f"  [成功] 在 ({click_x}, {click_y}) 点击了 '{text}'。")
                return True

            time.sleep(0.3)

        print(f"  [失败] 超时 {timeout}s 后仍未找到文本 '{text}'。")
        return False

    def click_image(self, image_path: str, region: Optional[Tuple[int, int, int, int]] = None,
                    timeout: float = 3.0) -> bool:
        """查找并点击指定的图像/图标。"""
        print(f"[交互] 尝试点击图像: '{image_path}'")
        result = self.vision.wait_for_image(
            image_path=image_path,
            region=region,
            timeout=timeout,
            match_threshold=0.8
        )
        if result.found and result.center_point:
            self.app.click(result.center_point[0], result.center_point[1])
            print(f"  [成功] 在 ({result.center_point[0]}, {result.center_point[1]}) 点击了图像。")
            return True

        print(f"  [失败] 超时 {timeout}s 后仍未找到图像 '{image_path}'。")
        return False

    def wait_for_text(self, text: str, timeout: int = 10, region: Optional[Tuple[int, int, int, int]] = None) -> bool:
        """等待某个文本出现在屏幕上，直到超时。"""
        print(f"[交互] 等待文本出现: '{text}' (超时: {timeout}s)")
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.check_text_exists(text, region):
                print(f"  [成功] 文本 '{text}' 已出现。")
                return True
            time.sleep(0.5)
        print(f"  [失败] 超时 {timeout}s 后文本 '{text}' 未出现。")
        return False

    def check_text_exists(self, text: str, rect: Optional[Tuple[int, int, int, int]] = None) -> bool:
        """检查屏幕上是否存在某个文本，立即返回 True 或 False。"""
        capture = self.screen.capture(rect=rect)
        if not capture.success or capture.image is None:
            return False
        result = self.ocr.find_text(text, capture.image)
        return result.found

    def find_text_with_scroll(
            self,
            text: str,
            scroll_area: Tuple[int, int, int, int],
            max_scrolls: int = 5
    ) -> bool:
        """在可滚动区域查找文本，如果找不到则自动向下滚动。"""
        print(f"[交互] 在可滚动区域查找 '{text}'...")
        for i in range(max_scrolls + 1):
            if self.click_text(text, region=scroll_area, timeout=1.0):
                return True
            if i < max_scrolls:
                print(f"  [滚动] 未找到，执行第 {i + 1}/{max_scrolls} 次滚动。")
                x1, y1, x2, y2 = scroll_area
                drag_start_y = y1 + (y2 - y1) * 0.75
                drag_end_y = y1 + (y2 - y1) * 0.25
                center_x = x1 + (x2 - x1) / 2
                self.app.drag(int(center_x), int(drag_start_y), int(center_x), int(drag_end_y), duration=0.5)
                time.sleep(1.0)
        print(f"  [失败] 滚动 {max_scrolls} 次后仍未找到 '{text}'。")
        return False

    # ===================================================================
    # 【【【新增复合操作】】】
    # ===================================================================

    def wait_for_text_to_disappear(self, text: str, timeout: int = 10,
                                   region: Optional[Tuple[int, int, int, int]] = None) -> bool:
        """
        等待某个文本从屏幕上消失，直到超时。
        常用于等待“加载中...”或“处理中...”等临时提示消失。
        """
        print(f"[交互] 等待文本消失: '{text}' (超时: {timeout}s)")
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not self.check_text_exists(text, region):
                print(f"  [成功] 文本 '{text}' 已消失。")
                return True
            time.sleep(0.5)
        print(f"  [失败] 超时 {timeout}s 后文本 '{text}' 仍存在。")
        return False

    def get_text_near_anchor(
            self,
            anchor_text: str,
            direction: str,
            search_offset: int = 5,
            search_size: Tuple[int, int] = (150, 50),
            rect: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[str]:
        """
        获取一个“锚点”文本附近区域的文本。非常适合用于读取标签旁边的数值。
        例如: get_text_near_anchor("价格:", "right") -> "5,800"

        :param anchor_text: 作为定位基准的文本。
        :param direction: 'right', 'left', 'above', 'below' 中的一个。
        :param search_offset: 从锚点边界开始的偏移量（像素）。
        :param search_size: (宽, 高) 定义的搜索区域大小。
        :param rect: 锚点所在的搜索区域。
        :return: 找到的文本字符串，或 None。
        """
        print(f"[交互] 尝试获取锚点 '{anchor_text}' {direction}方向的文本...")
        capture = self.app.capture(rect=rect)
        if not capture.success or not capture.image:
            return None

        anchor_result = self.ocr.find_text(anchor_text, capture.image)
        if not anchor_result.found or not anchor_result.rect:
            print(f"  [失败] 未能找到锚点文本 '{anchor_text}'。")
            return None

        ax1, ay1, ax2, ay2 = anchor_result.rect
        w, h = search_size

        # 根据方向计算目标搜索区域
        if direction == 'right':
            target_rect = (ax2 + search_offset, ay1, ax2 + search_offset + w, ay2)
        elif direction == 'left':
            target_rect = (ax1 - search_offset - w, ay1, ax1 - search_offset, ay2)
        elif direction == 'below':
            target_rect = (ax1, ay2 + search_offset, ax2, ay2 + search_offset + h)
        elif direction == 'above':
            target_rect = (ax1, ay1 - search_offset - h, ax2, ay1 - search_offset)
        else:
            raise ValueError("direction 参数必须是 'right', 'left', 'above', 'below' 之一")

        # 在小区域内进行OCR
        all_results = self.ocr.recognize_all(capture.image, rect=target_rect)
        if all_results.results:
            # 将找到的所有文本片段连接起来
            found_text = " ".join([res.text for res in all_results.results])
            print(f"  [成功] 在锚点附近找到文本: '{found_text}'")
            return found_text

        print(f"  [失败] 在锚点 '{anchor_text}' {direction}方向的区域内未找到任何文本。")
        return None

    def drag_image_to_image(
            self,
            source_image_path: str,
            target_image_path: str,
            region: Optional[Tuple[int, int, int, int]] = None,
            timeout: float = 3.0
    ) -> bool:
        """
        将一个图标/图像拖动到另一个图标/图像的位置。
        常用于游戏中的物品拖放、滑块验证等场景。
        """
        print(f"[交互] 尝试从 '{source_image_path}' 拖动到 '{target_image_path}'")

        # 同时查找源和目标
        source_result = self.vision.find_template(source_image_path, threshold=0.8)
        if not source_result.found or not source_result.center_point:
            print(f"  [失败] 未找到源图像: '{source_image_path}'")
            return False

        target_result = self.vision.find_template(target_image_path,threshold=0.8)
        if not target_result.found or not target_result.center_point:
            print(f"  [失败] 未找到目标图像: '{target_image_path}'")
            return False

        sx, sy = source_result.center_point
        tx, ty = target_result.center_point

        print(f"  [执行] 从 ({sx}, {sy}) 拖动到 ({tx}, {ty})")
        self.app.drag(sx, sy, tx, ty, duration=0.8)
        return True
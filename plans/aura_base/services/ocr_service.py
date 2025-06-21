# aura_official_packages/aura_base/services/ocr_service.py

import re
import cv2
import numpy as np
from dataclasses import dataclass, field
from paddleocr import PaddleOCR
from typing import Any
import threading

# 【核心修改】从框架的统一API入口导入装饰器
from packages.aura_core.api import register_service

# --- 数据类 (OcrResult, MultiOcrResult) 保持不变 ---
@dataclass
class OcrResult:
    """封装单次OCR识别的结果。"""
    found: bool = False
    text: str = ""
    center_point: tuple[int, int] | None = None
    rect: tuple[int, int, int, int] | None = None
    confidence: float = 0.0
    debug_info: dict[str, Any] = field(default_factory=dict)

@dataclass
class MultiOcrResult:
    """封装多次OCR识别的结果。"""
    count: int = 0
    results: list[OcrResult] = field(default_factory=list)

# --- 【核心修改】使用装饰器标记此类为服务 ---
@register_service(alias="ocr", public=True)
class OcrService:
    """
    一个封装了PaddleOCR的服务，提供文本查找和识别功能。
    此类是线程安全的。
    """
    def __init__(self):
        # ... (类的内部实现完全不变)
        print("正在初始化OCR服务元数据...")
        self._thread_local_storage = threading.local()
        print("OCR服务元数据初始化完毕。引擎将在首次使用时按需创建。")

    def _get_engine(self) -> PaddleOCR:
        engine = getattr(self._thread_local_storage, 'ocr_engine', None)
        if engine is None:
            thread_id = threading.get_ident()
            print(f"线程 {thread_id}: 未找到OCR引擎，正在创建新的实例...")
            try:
                new_engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
                self._thread_local_storage.ocr_engine = new_engine
                print(f"线程 {thread_id}: OCR引擎创建成功。")
                return new_engine
            except Exception as e:
                print(f"错误: 线程 {thread_id} 的OCR引擎初始化失败 - {e}")
                raise
        return engine

    def _run_ocr(self, image: np.ndarray) -> list:
        ocr_engine = self._get_engine()
        if len(image.shape) == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        result = ocr_engine.ocr(image, cls=True)
        return result[0] if result and result[0] is not None else []

    def _parse_line(self, line: list) -> OcrResult:
        box = line[0]
        text, confidence = line[1]
        top_left = (int(box[0][0]), int(box[0][1]))
        bottom_right = (int(box[2][0]), int(box[2][1]))
        rect = (top_left[0], top_left[1], bottom_right[0] - top_left[0], bottom_right[1] - top_left[1])
        center_point = (top_left[0] + rect[2] // 2, top_left[1] + rect[3] // 2)
        return OcrResult(
            found=True, text=text, center_point=center_point, rect=rect, confidence=confidence
        )

    def find_text(self, text_to_find: str, source_image: np.ndarray, match_mode: str = "exact") -> OcrResult:
        ocr_results = self._run_ocr(source_image)
        for line in ocr_results:
            line_text = line[1][0]
            is_match = False
            if match_mode == "exact": is_match = (line_text == text_to_find)
            elif match_mode == "contains": is_match = (text_to_find in line_text)
            elif match_mode == "regex":
                try:
                    if re.search(text_to_find, line_text): is_match = True
                except re.error: is_match = (text_to_find in line_text)
            if is_match:
                return self._parse_line(line)
        all_recognized_texts = [self._parse_line(line) for line in ocr_results]
        return OcrResult(found=False, debug_info={"all_recognized_results": all_recognized_texts})

    def find_all_text(self, text_to_find: str, source_image: np.ndarray, match_mode: str = "exact") -> MultiOcrResult:
        ocr_results = self._run_ocr(source_image)
        found_matches = []
        for line in ocr_results:
            line_text = line[1][0]
            is_match = False
            if match_mode == "exact": is_match = (line_text == text_to_find)
            elif match_mode == "contains": is_match = (text_to_find in line_text)
            elif match_mode == "regex":
                try:
                    if re.search(text_to_find, line_text): is_match = True
                except re.error: is_match = (text_to_find in line_text)
            if is_match:
                found_matches.append(self._parse_line(line))
        return MultiOcrResult(count=len(found_matches), results=found_matches)

    def recognize_all(self, source_image: np.ndarray) -> MultiOcrResult:
        ocr_results = self._run_ocr(source_image)
        all_text = [self._parse_line(line) for line in ocr_results]
        return MultiOcrResult(count=len(all_text), results=all_text)


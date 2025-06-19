# src/notifier_services/ocr_service.py

import re
import cv2
import numpy as np
from dataclasses import dataclass, field
from paddleocr import PaddleOCR
from typing import Any
import threading  # 【新增】导入threading模块


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


# --- 【修改后的 OcrService 类】 ---
class OcrService:
    """
    一个封装了PaddleOCR的服务，提供文本查找和识别功能。
    【修改后】此类是线程安全的。
    """

    def __init__(self):
        """
        初始化OCR服务。
        【修改】不再立即创建引擎，而是创建线程局部存储。
        """
        print("正在初始化OCR服务元数据...")
        # 【核心修改】创建线程局部存储对象
        self._thread_local_storage = threading.local()
        print("OCR服务元数据初始化完毕。引擎将在首次使用时按需创建。")

    def _get_engine(self) -> PaddleOCR:
        """
        【新增】获取当前线程的 PaddleOCR 引擎实例。
        如果当前线程还没有引擎，则为其创建一个新的。
        """
        # 检查当前线程的局部存储中是否已有 ocr_engine
        engine = getattr(self._thread_local_storage, 'ocr_engine', None)

        if engine is None:
            thread_id = threading.get_ident()
            print(f"线程 {thread_id}: 未找到OCR引擎，正在创建新的实例...")
            try:
                # 创建新的引擎实例
                new_engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)

                # 将新创建的引擎存入当前线程的局部存储中
                self._thread_local_storage.ocr_engine = new_engine
                print(f"线程 {thread_id}: OCR引擎创建成功。")
                return new_engine
            except Exception as e:
                print(f"错误: 线程 {thread_id} 的OCR引擎初始化失败 - {e}")
                raise

        # 如果引擎已存在，直接返回
        return engine

    def _run_ocr(self, image: np.ndarray) -> list:
        """[内部辅助] 运行OCR引擎并返回原始结果。"""
        # 【核心修改】通过 _get_engine() 获取线程安全的引擎
        ocr_engine = self._get_engine()

        # PaddleOCR 期望 BGR 格式的图像
        if len(image.shape) == 2:  # 如果是灰度图，转为BGR
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

        result = ocr_engine.ocr(image, cls=True)
        return result[0] if result and result[0] is not None else []

    # --- 以下所有方法 ( _parse_line, find_text, find_all_text, recognize_all ) ---
    # --- 均保持完全不变，因为它们依赖的 _run_ocr 已经是线程安全的了。 ---

    def _parse_line(self, line: list) -> OcrResult:
        """[内部辅助] 将单行OCR原始结果解析为OcrResult对象。"""
        box = line[0]
        text, confidence = line[1]
        top_left = (int(box[0][0]), int(box[0][1]))
        bottom_right = (int(box[2][0]), int(box[2][1]))
        rect = (top_left[0], top_left[1], bottom_right[0] - top_left[0], bottom_right[1] - top_left[1])
        center_point = (top_left[0] + rect[2] // 2, top_left[1] + rect[3] // 2)
        return OcrResult(
            found=True,
            text=text,
            center_point=center_point,
            rect=rect,
            confidence=confidence
        )

    def find_text(self,
                  text_to_find: str,
                  source_image: np.ndarray,
                  match_mode: str = "exact") -> OcrResult:
        """
        在源图像中查找单个指定的文本。
        """
        ocr_results = self._run_ocr(source_image)
        for line in ocr_results:
            line_text = line[1][0]
            is_match = False
            if match_mode == "exact":
                is_match = (line_text == text_to_find)
            elif match_mode == "contains":
                is_match = (text_to_find in line_text)
            elif match_mode == "regex":
                try:
                    if re.search(text_to_find, line_text):
                        is_match = True
                except re.error:
                    is_match = (text_to_find in line_text)
            if is_match:
                return self._parse_line(line)
        all_recognized_texts = [self._parse_line(line) for line in ocr_results]
        return OcrResult(
            found=False,
            debug_info={"all_recognized_results": all_recognized_texts}
        )

    def find_all_text(self,
                      text_to_find: str,
                      source_image: np.ndarray,
                      match_mode: str = "exact") -> MultiOcrResult:
        """
        在源图像中查找所有匹配的文本实例。
        """
        ocr_results = self._run_ocr(source_image)
        found_matches = []
        for line in ocr_results:
            line_text = line[1][0]
            is_match = False
            if match_mode == "exact":
                is_match = (line_text == text_to_find)
            elif match_mode == "contains":
                is_match = (text_to_find in line_text)
            elif match_mode == "regex":
                try:
                    if re.search(text_to_find, line_text):
                        is_match = True
                except re.error:
                    is_match = (text_to_find in line_text)
            if is_match:
                found_matches.append(self._parse_line(line))
        return MultiOcrResult(count=len(found_matches), results=found_matches)

    def recognize_all(self, source_image: np.ndarray) -> MultiOcrResult:
        """
        识别图像中的所有文本。
        """
        ocr_results = self._run_ocr(source_image)
        all_text = [self._parse_line(line) for line in ocr_results]
        return MultiOcrResult(count=len(all_text), results=all_text)


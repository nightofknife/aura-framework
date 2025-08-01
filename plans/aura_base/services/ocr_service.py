# packages/aura_base/services/ocr_service.py

import re
import threading
from dataclasses import dataclass, field
from typing import Any, List, Dict, Optional

import cv2
import numpy as np
from paddleocr import PaddleOCR

from packages.aura_core.api import register_service


@dataclass
class OcrResult:
    found: bool = False
    text: str = ""
    center_point: tuple[int, int] | None = None
    rect: tuple[int, int, int, int] | None = None
    confidence: float = 0.0
    debug_info: dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiOcrResult:
    count: int = 0
    results: list[OcrResult] = field(default_factory=list)


@register_service(alias="ocr", public=True)
class OcrService:
    def __init__(self):
        self._thread_local_storage = threading.local()

    def _get_engine(self) -> PaddleOCR:
        engine = getattr(self._thread_local_storage, 'ocr_engine', None)
        if engine is None:
            thread_id = threading.get_ident()
            print(f"线程 {thread_id}: 正在为OCR服务创建新的引擎实例...")
            new_engine = PaddleOCR(
                lang="ch", ocr_version="PP-OCRv5", device="gpu",
                use_doc_unwarping=False
            )
            self._thread_local_storage.ocr_engine = new_engine
            return new_engine
        return engine

    def _run_ocr(self, image: np.ndarray) -> List[Dict]:
        ocr_engine = self._get_engine()

        if len(image.shape) == 2:
            image_bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

        # 核心修复：禁用文档方向分类，防止图像被错误旋转
        result = ocr_engine.predict(image_bgr, use_doc_orientation_classify=False)
        return result

    def _parse_results(self, ocr_raw_results: List[Dict]) -> List[OcrResult]:
        parsed_list = []
        if not ocr_raw_results or not ocr_raw_results[0]:
            return []
        data = ocr_raw_results[0]
        texts = data.get('rec_texts', [])
        scores = data.get('rec_scores', [])
        boxes = data.get('rec_polys', [])
        for text, score, box in zip(texts, scores, boxes):
            if not isinstance(box, np.ndarray) or box.ndim != 2 or box.shape[0] < 1:
                continue
            x_coords = box[:, 0]
            y_coords = box[:, 1]
            x, y = int(np.min(x_coords)), int(np.min(y_coords))
            w, h = int(np.max(x_coords) - x), int(np.max(y_coords) - y)
            center_x, center_y = x + w // 2, y + h // 2
            parsed_list.append(OcrResult(
                found=True, text=text, center_point=(center_x, center_y),
                rect=(x, y, w, h), confidence=float(score)
            ))
        return parsed_list

    def find_text(self, text_to_find: str, source_image: np.ndarray, match_mode: str = "exact",
                  synonyms: Optional[Dict[str, str]] = None) -> OcrResult:
        raw_results = self._run_ocr(source_image)
        all_parsed_results = self._parse_results(raw_results)
        for result in all_parsed_results:
            ocr_text = result.text
            normalized_text = synonyms.get(ocr_text, ocr_text) if synonyms else ocr_text
            is_match = False
            if match_mode == "exact":
                is_match = (normalized_text == text_to_find)
            elif match_mode == "contains":
                is_match = (text_to_find in normalized_text)
            elif match_mode == "regex":
                try:
                    if re.search(text_to_find, normalized_text): is_match = True
                except re.error:
                    is_match = (text_to_find in normalized_text)
            if is_match:
                return result
        return OcrResult(found=False, debug_info={"all_recognized_results": all_parsed_results})

    def find_all_text(self, text_to_find: str, source_image: np.ndarray, match_mode: str = "exact",
                      synonyms: Optional[Dict[str, str]] = None) -> MultiOcrResult:
        raw_results = self._run_ocr(source_image)
        all_parsed_results = self._parse_results(raw_results)
        found_matches = []
        for result in all_parsed_results:
            ocr_text = result.text
            normalized_text = synonyms.get(ocr_text, ocr_text) if synonyms else ocr_text
            is_match = False
            if match_mode == "exact":
                is_match = (normalized_text == text_to_find)
            elif match_mode == "contains":
                is_match = (text_to_find in normalized_text)
            elif match_mode == "regex":
                try:
                    if re.search(text_to_find, normalized_text): is_match = True
                except re.error:
                    is_match = (text_to_find in normalized_text)
            if is_match:
                found_matches.append(result)
        return MultiOcrResult(count=len(found_matches), results=found_matches)

    def recognize_all(self, source_image: np.ndarray) -> MultiOcrResult:
        raw_results = self._run_ocr(source_image)
        all_parsed_results = self._parse_results(raw_results)
        filtered_results = [res for res in all_parsed_results if res.text and res.confidence > 0]
        return MultiOcrResult(count=len(filtered_results), results=filtered_results)

"""
提供一个高性能、资源可控的光学字符识别（OCR）服务。

该模块的核心是 `OcrService` 类，它封装了 `PaddleOCR` 引擎。
为了解决 `PaddleOCR` 引擎初始化耗时和内存占用高的问题，本服务采用了
单例共享引擎的设计模式。所有OCR请求都通过一个异步信号量进行并发控制，
以保护GPU资源并确保在高负载下的系统稳定性。

与框架中的其他IO密集型服务类似，它也提供了同步的公共接口和异步的
内部核心实现，通过桥接器模式实现两者的无缝转换。
"""
import asyncio
import re
import threading
from dataclasses import dataclass, field
from typing import Any, List, Dict, Optional

import cv2
import numpy as np
from paddleocr import PaddleOCR

from packages.aura_core.api import register_service
from packages.aura_core.logger import logger


@dataclass
class OcrResult:
    """
    封装单次OCR查找或识别的结果。

    Attributes:
        found (bool): 是否找到了匹配的文本。
        text (str): 识别出的文本内容。
        center_point (Optional[Tuple[int, int]]): 文本框的中心点坐标 `(x, y)`。
        rect (Optional[Tuple[int, int, int, int]]): 文本框的矩形区域 `(x, y, width, height)`。
        confidence (float): 识别结果的置信度，介于0.0和1.0之间。
        debug_info (Dict[str, Any]): 用于存储调试信息的附加字典。
    """
    found: bool = False
    text: str = ""
    center_point: Optional[Tuple[int, int]] = None
    rect: Optional[Tuple[int, int, int, int]] = None
    confidence: float = 0.0
    debug_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiOcrResult:
    """
    封装一次识别或查找中所有匹配结果的集合。

    Attributes:
        count (int): 找到的匹配结果数量。
        results (List[OcrResult]): 一个包含所有 `OcrResult` 对象的列表。
    """
    count: int = 0
    results: List[OcrResult] = field(default_factory=list)


@register_service(alias="ocr", public=True)
class OcrService:
    """
    一个高性能、资源可控的OCR服务。

    它使用单一共享的 `PaddleOCR` 引擎实例，以避免重复加载模型导致的内存
    和性能开销。通过异步信号量控制对引擎的并发访问，保护GPU资源。
    """

    def __init__(self):
        """初始化OCR服务，设置异步锁和信号量。"""
        self._engine: Optional[PaddleOCR] = None
        self._engine_lock = asyncio.Lock()
        self._ocr_semaphore = asyncio.Semaphore(1)  # 同一时间只允许一个OCR任务在GPU上运行
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_lock = threading.Lock()

    # =========================================================================
    # Section 1: 公共同步接口
    # =========================================================================

    def initialize_engine(self):
        """
        手动预初始化OCR引擎。

        此方法是线程安全的，可以在框架启动的任何阶段调用，以预先加载
        OCR模型，避免首次使用时出现延迟。
        """
        logger.info("收到同步初始化OCR引擎请求...")
        self._submit_to_loop_and_wait(self._initialize_engine_async())

    def find_text(self, text_to_find: str, source_image: np.ndarray, match_mode: str = "exact",
                  synonyms: Optional[Dict[str, str]] = None) -> OcrResult:
        """
        在给定的图像中查找符合条件的第一个文本实例。

        Args:
            text_to_find (str): 要查找的文本或正则表达式。
            source_image (np.ndarray): 要在其中进行查找的源图像。
            match_mode (str): 匹配模式，可选值为 'exact', 'contains', 'regex'。
            synonyms (Optional[Dict[str, str]]): 一个同义词字典，用于在匹配前进行文本替换。

        Returns:
            OcrResult: 包含第一个匹配项的结果对象。如果未找到，`found` 字段为 False。
        """
        return self._submit_to_loop_and_wait(
            self._find_text_async(text_to_find, source_image, match_mode, synonyms)
        )

    def find_all_text(self, text_to_find: str, source_image: np.ndarray, match_mode: str = "exact",
                      synonyms: Optional[Dict[str, str]] = None) -> MultiOcrResult:
        """
        在给定的图像中查找所有符合条件的文本实例。

        Args:
            text_to_find (str): 要查找的文本或正则表达式。
            source_image (np.ndarray): 源图像。
            match_mode (str): 匹配模式。
            synonyms (Optional[Dict[str, str]]): 同义词字典。

        Returns:
            MultiOcrResult: 包含所有匹配项的结果集合。
        """
        return self._submit_to_loop_and_wait(
            self._find_all_text_async(text_to_find, source_image, match_mode, synonyms)
        )

    def recognize_text(self, source_image: np.ndarray) -> OcrResult:
        """
        识别图像中置信度最高的单个文本。

        Args:
            source_image (np.ndarray): 要识别的图像。

        Returns:
            OcrResult: 置信度最高的识别结果。如果图像中没有文本，`found` 字段为 False。
        """
        return self._submit_to_loop_and_wait(self._recognize_text_async(source_image))

    def recognize_all(self, source_image: np.ndarray) -> MultiOcrResult:
        """
        识别并返回图像中的所有文本。

        Args:
            source_image (np.ndarray): 要识别的图像。

        Returns:
            MultiOcrResult: 包含所有识别出的文本的结果集合。
        """
        return self._submit_to_loop_and_wait(self._recognize_all_async(source_image))

    # =========================================================================
    # Section 2: 内部异步核心实现
    # =========================================================================

    async def _initialize_engine_async(self):
        """异步地、线程安全地初始化共享的 PaddleOCR 引擎。"""
        async with self._engine_lock:
            if self._engine is None:
                logger.info("OCR服务: 正在初始化共享的PaddleOCR引擎...")
                self._engine = await asyncio.to_thread(
                    PaddleOCR, lang="ch", ocr_version="PP-OCRv5", device="gpu", use_doc_unwarping=False,
                    doc_orientation_classify_model_dir= r".\plans\aura_base\services\ocr_model\PP-LCNet_x1_0_doc_ori",
                    text_detection_model_dir= r".\plans\aura_base\services\ocr_model\PP-OCRv5_server_det",
                    text_recognition_model_dir = r".\plans\aura_base\services\ocr_model\PP-OCRv5_server_rec",
                    textline_orientation_model_dir=r".\plans\aura_base\services\ocr_model\PP-LCNet_x1_0_textline_ori" ,
                    )
                logger.info("OCR服务: 共享引擎初始化完成。")
            else:
                logger.info("OCR服务: 共享引擎已初始化，无需重复操作。")

    async def _get_engine_async(self) -> PaddleOCR:
        """异步地获取 OCR 引擎实例，如果尚未初始化，则先进行初始化。"""
        if self._engine is None:
            await self._initialize_engine_async()
        return self._engine

    async def _find_text_async(self, text_to_find: str, source_image: np.ndarray, match_mode: str,
                               synonyms: Optional[Dict[str, str]]) -> OcrResult:
        """异步地执行查找单个文本的逻辑。"""
        all_parsed_results = await self._recognize_all_and_parse_async(source_image)
        for result in all_parsed_results:
            normalized_text = synonyms.get(result.text, result.text) if synonyms else result.text
            if self._is_match(normalized_text, text_to_find, match_mode):
                return result
        return OcrResult(found=False, debug_info={"all_recognized_results": all_parsed_results})

    async def _find_all_text_async(self, text_to_find: str, source_image: np.ndarray, match_mode: str,
                                   synonyms: Optional[Dict[str, str]]) -> MultiOcrResult:
        """异步地执行查找所有文本的逻辑。"""
        all_parsed_results = await self._recognize_all_and_parse_async(source_image)
        found_matches = []
        for result in all_parsed_results:
            normalized_text = synonyms.get(result.text, result.text) if synonyms else result.text
            if self._is_match(normalized_text, text_to_find, match_mode):
                found_matches.append(result)
        return MultiOcrResult(count=len(found_matches), results=found_matches)

    async def _recognize_text_async(self, source_image: np.ndarray) -> OcrResult:
        """异步地执行识别最佳文本的逻辑。"""
        all_parsed_results = await self._recognize_all_and_parse_async(source_image)
        if not all_parsed_results:
            return OcrResult(found=False)
        best_result = max(all_parsed_results, key=lambda r: r.confidence)
        best_result.found = True
        return best_result

    async def _recognize_all_async(self, source_image: np.ndarray) -> MultiOcrResult:
        """异步地执行识别所有文本的逻辑。"""
        all_parsed_results = await self._recognize_all_and_parse_async(source_image)
        return MultiOcrResult(count=len(all_parsed_results), results=all_parsed_results)

    # =========================================================================
    # Section 3: 核心辅助工具
    # =========================================================================

    async def _recognize_all_and_parse_async(self, source_image: np.ndarray) -> List[OcrResult]:
        """
        所有识别功能的异步核心，处理并发控制和OCR执行。

        Args:
            source_image (np.ndarray): 要识别的图像。

        Returns:
            List[OcrResult]: 一个包含所有识别结果的列表。
        """
        engine = await self._get_engine_async()
        async with self._ocr_semaphore:
            raw_results = await asyncio.to_thread(
                self._run_ocr_sync, engine, source_image
            )
        return self._parse_results(raw_results)

    def _run_ocr_sync(self, engine: PaddleOCR, image: np.ndarray) -> List[Dict[str, Any]]:
        """一个纯粹的、阻塞的同步函数，用于在线程池中执行OCR预测。"""
        if len(image.shape) == 2:
            image_bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        result = engine.predict(image_bgr, use_doc_orientation_classify=False)
        return result

    def _parse_results(self, ocr_raw_results: List[Dict[str, Any]]) -> List[OcrResult]:
        """将 PaddleOCR 的原始输出解析成 `OcrResult` 对象列表。"""
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
            x_coords, y_coords = box[:, 0], box[:, 1]
            x, y = int(np.min(x_coords)), int(np.min(y_coords))
            w, h = int(np.max(x_coords) - x), int(np.max(y_coords) - y)
            center_x, center_y = x + w // 2, y + h // 2
            parsed_list.append(OcrResult(
                found=True, text=text, center_point=(center_x, center_y),
                rect=(x, y, w, h), confidence=float(score)
            ))
        return parsed_list

    def _is_match(self, text_to_check: str, text_to_find: str, match_mode: str) -> bool:
        """根据指定的匹配模式检查文本是否匹配。"""
        if match_mode == "exact":
            return text_to_check == text_to_find
        if match_mode == "contains":
            return text_to_find in text_to_check
        if match_mode == "regex":
            try:
                return bool(re.search(text_to_find, text_to_check))
            except re.error:
                logger.warning(f"正则表达式 '{text_to_find}' 无效，已回退到 'contains' 模式进行匹配。")
                return text_to_find in text_to_check
        return False

    # =========================================================================
    # Section 4: 同步/异步桥接器
    # =========================================================================

    def _get_running_loop(self) -> asyncio.AbstractEventLoop:
        """线程安全地获取正在运行的 asyncio 事件循环。"""
        with self._loop_lock:
            if self._loop is None or self._loop.is_closed():
                try:
                    self._loop = asyncio.get_running_loop()
                except RuntimeError:
                    from packages.aura_core.api import service_registry
                    scheduler = service_registry.get_service_instance('scheduler')
                    if scheduler and scheduler._loop and scheduler._loop.is_running():
                        self._loop = scheduler._loop
                    else:
                        raise RuntimeError("OCR服务无法找到正在运行的asyncio事件循环。")
            return self._loop

    def _submit_to_loop_and_wait(self, coro: asyncio.Future) -> Any:
        """
        将一个协程从同步代码提交到事件循环，并阻塞地等待其结果。

        这是实现“同步外壳，异步内核”模式的核心。
        """
        loop = self._get_running_loop()
        try:
            running_loop = asyncio.get_running_loop()
            if running_loop is loop:
                logger.warning(
                    "OCR服务的同步接口被从异步代码中调用，这可能导致性能问题。请直接调用异步内核方法 (_..._async)。")
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                return future.result()
        except RuntimeError:
            pass
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()



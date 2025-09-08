# packages/aura_base/services/ocr_service.py (最终稳定版 - 异步核心)

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
    """
    【最终稳定版】一个高性能、资源可控的OCR服务。
    - 对外保持100%兼容的同步接口。
    - 内部使用异步核心和单一共享引擎，从根本上解决内存爆炸和启动风暴问题。
    - 通过信号量控制并发，保护GPU资源，确保高负载下系统稳定。
    """

    def __init__(self):
        # --- 异步核心组件 ---
        self._engine: Optional[PaddleOCR] = None
        self._engine_lock = asyncio.Lock()
        self._ocr_semaphore = asyncio.Semaphore(1)  # 同一时间只允许一个OCR任务在GPU上运行
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # --- 同步接口组件 ---
        self._loop_lock = threading.Lock()  # 用于安全地获取事件循环

    # =========================================================================
    # Section 1: 公共同步接口 (保持100%向后兼容)
    # =========================================================================

    def initialize_engine(self):
        """
        【保持同步】手动预初始化OCR引擎。
        此方法是线程安全的，可以在框架启动的任何阶段调用。
        """
        logger.info("收到同步初始化OCR引擎请求...")
        self._submit_to_loop_and_wait(self._initialize_engine_async())

    def find_text(self, text_to_find: str, source_image: np.ndarray, match_mode: str = "exact",
                  synonyms: Optional[Dict[str, str]] = None) -> OcrResult:
        """【保持同步】查找符合条件的第一个文本。"""
        return self._submit_to_loop_and_wait(
            self._find_text_async(text_to_find, source_image, match_mode, synonyms)
        )

    def find_all_text(self, text_to_find: str, source_image: np.ndarray, match_mode: str = "exact",
                      synonyms: Optional[Dict[str, str]] = None) -> MultiOcrResult:
        """【保持同步】查找所有符合条件的文本。"""
        return self._submit_to_loop_and_wait(
            self._find_all_text_async(text_to_find, source_image, match_mode, synonyms)
        )

    def recognize_text(self, source_image: np.ndarray) -> OcrResult:
        """【保持同步】识别可信度最高的单个文本。"""
        return self._submit_to_loop_and_wait(self._recognize_text_async(source_image))

    def recognize_all(self, source_image: np.ndarray) -> MultiOcrResult:
        """【保持同步】识别所有文本。"""
        return self._submit_to_loop_and_wait(self._recognize_all_async(source_image))

    # =========================================================================
    # Section 2: 内部异步核心实现
    # =========================================================================

    async def _initialize_engine_async(self):
        """【异步内核】安全地初始化共享引擎。"""
        async with self._engine_lock:
            if self._engine is None:
                logger.info("OCR服务: 正在初始化共享的PaddleOCR引擎...")
                self._engine = await asyncio.to_thread(
                    PaddleOCR, lang="ch", ocr_version="PP-OCRv5", device="gpu", use_doc_unwarping=False
                )
                logger.info("OCR服务: 共享引擎初始化完成。")
            else:
                logger.info("OCR服务: 共享引擎已初始化，无需重复操作。")

    async def _get_engine_async(self) -> PaddleOCR:
        """【异步内核】确保引擎已初始化。"""
        if self._engine is None:
            await self._initialize_engine_async()
        return self._engine

    async def _find_text_async(self, text_to_find: str, source_image: np.ndarray, match_mode: str,
                               synonyms: Optional[Dict[str, str]]) -> OcrResult:
        """【异步内核】执行查找单个文本的逻辑。"""
        all_parsed_results = await self._recognize_all_and_parse_async(source_image)
        for result in all_parsed_results:
            normalized_text = synonyms.get(result.text, result.text) if synonyms else result.text
            if self._is_match(normalized_text, text_to_find, match_mode):
                return result
        return OcrResult(found=False, debug_info={"all_recognized_results": all_parsed_results})

    async def _find_all_text_async(self, text_to_find: str, source_image: np.ndarray, match_mode: str,
                                   synonyms: Optional[Dict[str, str]]) -> MultiOcrResult:
        """【异步内核】执行查找所有文本的逻辑。"""
        all_parsed_results = await self._recognize_all_and_parse_async(source_image)
        found_matches = []
        for result in all_parsed_results:
            normalized_text = synonyms.get(result.text, result.text) if synonyms else result.text
            if self._is_match(normalized_text, text_to_find, match_mode):
                found_matches.append(result)
        return MultiOcrResult(count=len(found_matches), results=found_matches)

    async def _recognize_text_async(self, source_image: np.ndarray) -> OcrResult:
        """【异步内核】执行识别最佳文本的逻辑。"""
        all_parsed_results = await self._recognize_all_and_parse_async(source_image)
        if not all_parsed_results:
            return OcrResult(found=False)
        best_result = max(all_parsed_results, key=lambda r: r.confidence)
        best_result.found = True
        return best_result

    async def _recognize_all_async(self, source_image: np.ndarray) -> MultiOcrResult:
        """【异步内核】执行识别所有文本的逻辑。"""
        all_parsed_results = await self._recognize_all_and_parse_async(source_image)
        return MultiOcrResult(count=len(all_parsed_results), results=all_parsed_results)

    # =========================================================================
    # Section 3: 核心辅助工具
    # =========================================================================

    async def _recognize_all_and_parse_async(self, source_image: np.ndarray) -> List[OcrResult]:
        """【异步内核】这是所有识别功能的核心，它处理并发控制和OCR执行。"""
        engine = await self._get_engine_async()

        async with self._ocr_semaphore:
            # 使用 asyncio.to_thread 在后台线程中执行阻塞的OCR预测
            raw_results = await asyncio.to_thread(
                self._run_ocr_sync, engine, source_image
            )

        # 解析是纯CPU计算，可以在主线程快速完成
        return self._parse_results(raw_results)

    def _run_ocr_sync(self, engine: PaddleOCR, image: np.ndarray) -> List[Dict]:
        """【内部同步】这是一个纯粹的、阻塞的同步函数，用于在线程池中执行。"""
        if len(image.shape) == 2:
            image_bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

        result = engine.predict(image_bgr, use_doc_orientation_classify=False)
        return result

    def _parse_results(self, ocr_raw_results: List[Dict]) -> List[OcrResult]:
        """【内部同步】纯数据处理，无需修改。"""
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

    def _is_match(self, text_to_check: str, text_to_find: str, match_mode: str) -> bool:
        """【内部同步】将匹配逻辑提取到一个独立的辅助函数中，避免代码重复。"""
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
    # Section 4: 同步/异步桥接器 (关键)
    # =========================================================================

    def _get_running_loop(self) -> asyncio.AbstractEventLoop:
        """【桥接器】线程安全地获取正在运行的事件循环。"""
        with self._loop_lock:
            if self._loop is None or self._loop.is_closed():
                try:
                    # 尝试获取当前线程的事件循环 (如果主线程调用)
                    self._loop = asyncio.get_running_loop()
                except RuntimeError:
                    # 如果在非asyncio管理的线程中调用，则需要从scheduler获取
                    # 注意: 这需要你的服务注册机制能够注入scheduler实例，
                    # 或者通过全局服务注册表访问。
                    from packages.aura_core.api import service_registry
                    scheduler = service_registry.get_service_instance('scheduler')
                    if scheduler and scheduler._loop and scheduler._loop.is_running():
                        self._loop = scheduler._loop
                    else:
                        raise RuntimeError("OCR服务无法找到正在运行的asyncio事件循环。")
            return self._loop

    def _submit_to_loop_and_wait(self, coro: asyncio.Future) -> Any:
        """
        【桥接器】将一个协程从同步代码提交到事件循环，并阻塞等待其结果。
        这是实现“同步外壳，异步内核”模式的核心。
        """
        loop = self._get_running_loop()

        # 检查是否已经在事件循环线程中。如果是，直接 await 会导致死锁。
        try:
            running_loop = asyncio.get_running_loop()
            if running_loop is loop:
                # 这种情况非常罕见，但为了健壮性处理一下
                # 这意味着一个异步函数错误地调用了同步接口
                logger.warning(
                    "OCR服务的同步接口被从异步代码中调用，这可能导致性能问题。请直接调用异步内核方法 (_..._async)。")
                # 创建一个任务来避免阻塞事件循环
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                return future.result()
        except RuntimeError:
            # 不在事件循环线程中，这是预期的正常情况
            pass

        future = asyncio.run_coroutine_threadsafe(coro, loop)
        # .result() 会阻塞当前线程，直到协程在事件循环中完成，并返回结果或抛出异常
        return future.result()

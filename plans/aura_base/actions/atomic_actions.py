"""
提供了一系列基础的、原子级的核心行为（Actions）。

这些行为是构成 Aura 自动化任务的基本构建块。它们被设计为无状态的、
可重用的，并通过依赖注入的方式从 `ServiceRegistry` 获取所需的服务。
这些行为涵盖了从视觉识别（OCR/图像匹配）、键鼠控制到流程控制和
数据处理的各种基础功能。
"""
import time
from typing import Optional, Any, Dict, List, Tuple
import re
import cv2
from pydantic import BaseModel, Field

# --- 核心导入 ---
from packages.aura_core.api import register_action, requires_services
from packages.aura_core.engine import ExecutionEngine
from packages.aura_core.context import ExecutionContext
from packages.aura_core.event_bus import EventBus, Event
from packages.aura_core.exceptions import StopTaskException
from packages.aura_core.logger import logger
from packages.aura_core.state_store_service import StateStoreService

# --- 服务与数据模型导入 (来自本包) ---
from ..services.app_provider_service import AppProviderService
from ..services.ocr_service import OcrService, OcrResult, MultiOcrResult
from ..services.vision_service import VisionService, MatchResult, MultiMatchResult


# ==============================================================================
# I. 视觉与OCR原子行为 (Vision & OCR Actions)
# ==============================================================================

# --- Find Actions (查找信息) ---
@register_action(name="find_image", read_only=True, public=True)
@requires_services(vision='vision', app='app')
def find_image(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
               region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8) -> MatchResult:
    """
    在屏幕的指定区域内查找单个图像模板的最佳匹配项。

    Args:
        app (AppProviderService): 注入的应用提供者服务，用于截图。
        vision (VisionService): 注入的视觉服务，用于执行模板匹配。
        engine (ExecutionEngine): 注入的执行引擎，用于访问方案路径等上下文信息。
        template (str): 模板图像相对于方案根目录的路径。
        region (Optional[tuple[int, int, int, int]]): 要进行搜索的屏幕区域 `(x, y, width, height)`。
            如果为 None，则在整个目标窗口中查找。默认为 None。
        threshold (float): 匹配的置信度阈值，介于 0.0 和 1.0 之间。默认为 0.8。

    Returns:
        MatchResult: 一个包含匹配结果的对象。如果找到，`found` 字段为 True，
            并包含位置和置信度信息。
    """
    is_inspect_mode = engine.root_context.data.get("initial", {}).get("__is_inspect_mode__", False)
    capture = app.capture(rect=region)
    if not capture.success:
        logger.error("行为 'find_image' 失败：无法截图。")
        return MatchResult(found=False)

    source_image_for_debug = capture.image.copy()
    plan_path = engine.orchestrator.current_plan_path
    full_template_path = plan_path / template

    match_result = vision.find_template(source_image=source_image_for_debug, template_image=str(full_template_path),
                                        threshold=threshold)

    if match_result.found:
        region_x_offset = region[0] if region else 0
        region_y_offset = region[1] if region else 0
        match_result.top_left = (match_result.top_left[0] + region_x_offset, match_result.top_left[1] + region_y_offset)
        match_result.center_point = (
        match_result.center_point[0] + region_x_offset, match_result.center_point[1] + region_y_offset)
        match_result.rect = (
        match_result.rect[0] + region_x_offset, match_result.rect[1] + region_y_offset, match_result.rect[2],
        match_result.rect[3])

    if is_inspect_mode:
        try:
            template_image_for_debug = cv2.imread(str(full_template_path))
            match_result.debug_info.update(
                {"source_image": source_image_for_debug, "template_image": template_image_for_debug,
                 "params": {"template": template, "region": region, "threshold": threshold}})
        except Exception as e:
            logger.error(f"打包调试信息时出错: {e}")

    return match_result


@register_action(name="find_all_images", read_only=True, public=True)
@requires_services(vision='vision', app='app')
def find_all_images(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                    region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8) -> MultiMatchResult:
    """
    在屏幕的指定区域内查找所有与图像模板匹配的实例。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        vision (VisionService): 注入的视觉服务。
        engine (ExecutionEngine): 注入的执行引擎。
        template (str): 模板图像的相对路径。
        region (Optional[tuple[int, int, int, int]]): 搜索区域 `(x, y, width, height)`。默认为全窗口。
        threshold (float): 匹配的置信度阈值。默认为 0.8。

    Returns:
        MultiMatchResult: 包含所有匹配项的结果集合。
    """
    capture = app.capture(rect=region)
    if not capture.success:
        logger.error("行为 'find_all_images' 失败：无法截图。")
        return MultiMatchResult()

    plan_path = engine.orchestrator.current_plan_path
    full_template_path = plan_path / template
    multi_match_result = vision.find_all_templates(source_image=capture.image, template_image=str(full_template_path),
                                                   threshold=threshold)

    region_x_offset = region[0] if region else 0
    region_y_offset = region[1] if region else 0
    for match in multi_match_result.matches:
        match.top_left = (match.top_left[0] + region_x_offset, match.top_left[1] + region_y_offset)
        match.center_point = (match.center_point[0] + region_x_offset, match.center_point[1] + region_y_offset)
        match.rect = (match.rect[0] + region_x_offset, match.rect[1] + region_y_offset, match.rect[2], match.rect[3])

    return multi_match_result


@register_action(name="find_image_in_scrolling_area", public=True)
@requires_services(vision='vision', app='app')
def find_image_in_scrolling_area(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                                 scroll_area: tuple[int, int, int, int], scroll_direction: str = 'down',
                                 max_scrolls: int = 5, scroll_amount: int = 200, threshold: float = 0.8,
                                 delay_after_scroll: float = 0.5) -> MatchResult:
    """
    在可滚动的区域内查找图像，如果找不到则滚动后重试。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        vision (VisionService): 注入的视觉服务。
        engine (ExecutionEngine): 注入的执行引擎。
        template (str): 模板图像的相对路径。
        scroll_area (tuple[int, int, int, int]): 定义可滚动区域的 `(x, y, width, height)`。
        scroll_direction (str): 滚动方向，'up' 或 'down'。默认为 'down'。
        max_scrolls (int): 最大滚动次数。默认为 5。
        scroll_amount (int): 每次滚动的量。默认为 200。
        threshold (float): 图像匹配的置信度阈值。默认为 0.8。
        delay_after_scroll (float): 每次滚动后的等待时间（秒）。默认为 0.5。

    Returns:
        MatchResult: 如果找到图像，则返回匹配结果；否则返回 `found=False` 的结果。
    """
    logger.info(f"在可滚动区域 {scroll_area} 中查找 '{template}'，最多滚动 {max_scrolls} 次。")
    direction_map = {"up": 1, "down": -1}
    if scroll_direction.lower() not in direction_map:
        logger.error(f"无效的滚动方向: '{scroll_direction}'。")
        return MatchResult(found=False)

    scroll_val = scroll_amount * direction_map[scroll_direction.lower()]
    scroll_center_x = scroll_area[0] + scroll_area[2] // 2
    scroll_center_y = scroll_area[1] + scroll_area[3] // 2
    app.move_to(scroll_center_x, scroll_center_y, duration=0.1)

    for i in range(max_scrolls + 1):
        if i > 0:
            logger.info(f"第 {i} 次滚动...")
            app.scroll(scroll_val)
            time.sleep(delay_after_scroll)
        match_result = find_image(app, vision, engine, template, region=scroll_area, threshold=threshold)
        if match_result.found:
            logger.info(f"在第 {i} 次滚动后找到图像！")
            return match_result

    logger.warning(f"在滚动 {max_scrolls} 次后，仍未找到图像 '{template}'。")
    return MatchResult(found=False)


@register_action(name="find_text", read_only=True, public=True)
@requires_services(ocr='ocr', app='app')
def find_text(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str,
              region: Optional[tuple[int, int, int, int]] = None, match_mode: str = "exact") -> OcrResult:
    """
    在屏幕的指定区域内查找单个文本实例。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        ocr (OcrService): 注入的OCR服务。
        engine (ExecutionEngine): 注入的执行引擎。
        text_to_find (str): 要查找的文本。
        region (Optional[tuple[int, int, int, int]]): 搜索区域 `(x, y, width, height)`。默认为全窗口。
        match_mode (str): 匹配模式 ('exact', 'contains', 'regex')。默认为 'exact'。

    Returns:
        OcrResult: 包含查找结果的对象。
    """
    is_inspect_mode = engine.root_context.data.get("initial", {}).get("__is_inspect_mode__", False)
    capture = app.capture(rect=region)
    if not capture.success:
        logger.error("行为 'find_text' 失败：无法截图。")
        return OcrResult(found=False)

    source_image_for_debug = capture.image.copy()
    ocr_result = ocr.find_text(source_image=source_image_for_debug, text_to_find=text_to_find, match_mode=match_mode)

    if ocr_result.found:
        region_x_offset = region[0] if region else 0
        region_y_offset = region[1] if region else 0
        ocr_result.center_point = (
        ocr_result.center_point[0] + region_x_offset, ocr_result.center_point[1] + region_y_offset)
        ocr_result.rect = (
        ocr_result.rect[0] + region_x_offset, ocr_result.rect[1] + region_y_offset, ocr_result.rect[2],
        ocr_result.rect[3])

    if is_inspect_mode:
        ocr_result.debug_info.update({"source_image": source_image_for_debug,
                                      "params": {"text_to_find": text_to_find, "region": region,
                                                 "match_mode": match_mode}})

    return ocr_result


@register_action(name="recognize_all_text", read_only=True, public=True)
@requires_services(ocr='ocr', app='app')
def recognize_all_text(app: AppProviderService, ocr: OcrService,
                       region: Optional[tuple[int, int, int, int]] = None) -> MultiOcrResult:
    """
    识别并返回指定区域内的所有文本。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        ocr (OcrService): 注入的OCR服务。
        region (Optional[tuple[int, int, int, int]]): 识别区域。默认为全窗口。

    Returns:
        MultiOcrResult: 包含所有识别出的文本的结果集合。
    """
    capture = app.capture(rect=region)
    if not capture.success:
        logger.error("行为 'recognize_all_text' 失败：无法截图。")
        return MultiOcrResult()
    multi_ocr_result = ocr.recognize_all(source_image=capture.image)
    region_x_offset = region[0] if region else 0
    region_y_offset = region[1] if region else 0
    for result in multi_ocr_result.results:
        result.center_point = (result.center_point[0] + region_x_offset, result.center_point[1] + region_y_offset)
        result.rect = (
        result.rect[0] + region_x_offset, result.rect[1] + region_y_offset, result.rect[2], result.rect[3])
    return multi_ocr_result


@register_action(name="get_text_in_region", read_only=True, public=True)
@requires_services(ocr='ocr', app='app')
def get_text_in_region(app: AppProviderService, ocr: OcrService, region: tuple[int, int, int, int],
                       whitelist: Optional[str] = None, join_with: str = " ") -> str:
    """
    识别指定区域内的所有文本，并将其连接成单个字符串。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        ocr (OcrService): 注入的OCR服务。
        region (tuple[int, int, int, int]): 要识别的区域。
        whitelist (Optional[str]): 一个包含所有允许字符的字符串，用于过滤结果。
        join_with (str): 用于连接多个文本片段的分隔符。

    Returns:
        str: 识别并处理后的文本字符串。
    """
    logger.info(f"正在读取区域 {region} 内的文本...")
    multi_ocr_result = recognize_all_text(app, ocr, region)
    if not multi_ocr_result.results:
        return ""
    detected_texts = [res.text for res in multi_ocr_result.results]
    if whitelist:
        pattern = f'[^{re.escape(whitelist)}]'
        cleaned_texts = [re.sub(r'[\n\r]', '', txt) for txt in detected_texts]
        filtered_texts = [re.sub(pattern, '', txt) for txt in cleaned_texts]
    else:
        filtered_texts = detected_texts
    result = join_with.join(filtered_texts)
    logger.info(f"识别并处理后的文本: '{result}'")
    return result


# --- Check Actions (检查状态，返回布尔值) ---
@register_action(name="check_text_exists", read_only=True, public=True)
@requires_services(ocr='ocr', app='app')
def check_text_exists(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str,
                      region: Optional[tuple[int, int, int, int]] = None, match_mode: str = "exact") -> bool:
    """
    检查指定的文本当前是否存在于屏幕区域内。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        ocr (OcrService): 注入的OCR服务。
        engine (ExecutionEngine): 注入的执行引擎。
        text_to_find (str): 要检查的文本。
        region (Optional[tuple[int, int, int, int]]): 检查区域。默认为全窗口。
        match_mode (str): 匹配模式。默认为 'exact'。

    Returns:
        bool: 如果文本存在，则返回 True。
    """
    ocr_result = find_text(app, ocr, engine, text_to_find, region, match_mode)
    return ocr_result.found


@register_action(name="check_image_exists", read_only=True, public=True)
@requires_services(vision='vision', app='app')
def check_image_exists(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                       region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8) -> bool:
    """
    检查指定的图像当前是否存在于屏幕区域内。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        vision (VisionService): 注入的视觉服务。
        engine (ExecutionEngine): 注入的执行引擎。
        template (str): 模板图像的相对路径。
        region (Optional[tuple[int, int, int, int]]): 检查区域。默认为全窗口。
        threshold (float): 匹配阈值。默认为 0.8。

    Returns:
        bool: 如果图像存在，则返回 True。
    """
    match_result = find_image(app, vision, engine, template, region, threshold)
    return match_result.found


# --- Assert Actions (断言条件，失败则中断) ---
@register_action(name="assert_image_exists", read_only=True, public=True)
@requires_services(vision='vision', app='app')
def assert_image_exists(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                        region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8,
                        message: Optional[str] = None):
    """
    断言指定的图像必须存在，否则中断任务。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        vision (VisionService): 注入的视觉服务。
        engine (ExecutionEngine): 注入的执行引擎。
        template (str): 模板图像的相对路径。
        region (Optional[tuple[int, int, int, int]]): 检查区域。
        threshold (float): 匹配阈值。
        message (Optional[str]): 断言失败时显示的自定义错误消息。
    """
    match_result = find_image(app, vision, engine, template, region, threshold)
    if not match_result.found:
        error_message = message or f"断言失败：期望的图像 '{template}' 不存在。"
        logger.error(error_message)
        raise StopTaskException(error_message, success=False)
    logger.info(f"断言成功：图像 '{template}' 已确认存在。")
    return True


@register_action(name="assert_image_not_exists", read_only=True, public=True)
@requires_services(vision='vision', app='app')
def assert_image_not_exists(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                            region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8,
                            message: Optional[str] = None):
    """
    断言指定的图像必须不存在，否则中断任务。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        vision (VisionService): 注入的视觉服务。
        engine (ExecutionEngine): 注入的执行引擎。
        template (str): 模板图像的相对路径。
        region (Optional[tuple[int, int, int, int]]): 检查区域。
        threshold (float): 匹配阈值。
        message (Optional[str]): 断言失败时显示的自定义错误消息。
    """
    match_result = find_image(app, vision, engine, template, region, threshold)
    if match_result.found:
        error_message = message or f"断言失败：不期望的图像 '{template}' 却存在了。"
        logger.error(error_message)
        raise StopTaskException(error_message, success=False)
    logger.info(f"断言成功：图像 '{template}' 已确认不存在。")
    return True


@register_action(name="assert_text_exists", read_only=True, public=True)
@requires_services(ocr='ocr', app='app')
def assert_text_exists(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str,
                       region: Optional[tuple[int, int, int, int]] = None, match_mode: str = "contains",
                       message: Optional[str] = None):
    """
    断言指定的文本必须存在，否则中断任务。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        ocr (OcrService): 注入的OCR服务。
        engine (ExecutionEngine): 注入的执行引擎。
        text_to_find (str): 要断言存在的文本。
        region (Optional[tuple[int, int, int, int]]): 检查区域。
        match_mode (str): 匹配模式。
        message (Optional[str]): 自定义错误消息。
    """
    ocr_result = find_text(app, ocr, engine, text_to_find, region, match_mode)
    if not ocr_result.found:
        error_message = message or f"断言失败：期望的文本 '{text_to_find}' 不存在。"
        logger.error(error_message)
        raise StopTaskException(error_message, success=False)
    logger.info(f"断言成功：文本 '{text_to_find}' 已确认存在。")
    return True


@register_action(name="assert_text_not_exists", read_only=True, public=True)
@requires_services(ocr='ocr', app='app')
def assert_text_not_exists(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str,
                           region: Optional[tuple[int, int, int, int]] = None, match_mode: str = "contains",
                           message: Optional[str] = None):
    """
    断言指定的文本必须不存在，否则中断任务。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        ocr (OcrService): 注入的OCR服务。
        engine (ExecutionEngine): 注入的执行引擎。
        text_to_find (str): 要断言不存在的文本。
        region (Optional[tuple[int, int, int, int]]): 检查区域。
        match_mode (str): 匹配模式。
        message (Optional[str]): 自定义错误消息。
    """
    ocr_result = find_text(app, ocr, engine, text_to_find, region, match_mode)
    if ocr_result.found:
        error_message = message or f"断言失败：不期望的文本 '{ocr_result.text}' 却存在了。"
        logger.error(error_message)
        raise StopTaskException(error_message, success=False)
    logger.info(f"断言成功：文本 '{text_to_find}' 已确认不存在。")
    return True


@register_action(name="assert_text_equals", read_only=True, public=True)
@requires_services(ocr='ocr', app='app')
def assert_text_equals(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str,
                       expected_value: str, region: Optional[tuple[int, int, int, int]] = None,
                       message: Optional[str] = None):
    """
    断言找到的文本内容必须精确等于期望值。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        ocr (OcrService): 注入的OCR服务。
        engine (ExecutionEngine): 注入的执行引擎。
        text_to_find (str): 用于定位的文本。
        expected_value (str): 期望该文本的精确内容。
        region (Optional[tuple[int, int, int, int]]): 检查区域。
        message (Optional[str]): 自定义错误消息。
    """
    ocr_result = find_text(app, ocr, engine, text_to_find, region, match_mode="exact")
    if not ocr_result.found:
        error_message = message or f"断言失败：期望的文本 '{text_to_find}' 不存在。"
        raise StopTaskException(error_message, success=False)
    if ocr_result.text != expected_value:
        error_message = message or f"断言失败：文本内容不匹配。期望: '{expected_value}', 实际: '{ocr_result.text}'。"
        raise StopTaskException(error_message, success=False)
    logger.info(f"断言成功：文本 '{ocr_result.text}' 内容符合预期。")
    return True


# --- Wait Actions (等待UI变化) ---
@register_action(name="wait_for_text", public=True)
@requires_services(ocr='ocr', app='app')
def wait_for_text(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str,
                  timeout: float = 10.0, interval: float = 1.0, region: Optional[tuple[int, int, int, int]] = None,
                  match_mode: str = "contains") -> OcrResult:
    """
    在指定时间内轮询等待某个文本出现。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        ocr (OcrService): 注入的OCR服务。
        engine (ExecutionEngine): 注入的执行引擎。
        text_to_find (str): 要等待的文本。
        timeout (float): 最大等待时间（秒）。
        interval (float): 轮询间隔时间（秒）。
        region (Optional[tuple[int, int, int, int]]): 查找区域。
        match_mode (str): 匹配模式。

    Returns:
        OcrResult: 如果找到，则返回匹配结果；否则返回 `found=False` 的结果。
    """
    logger.info(f"开始等待文本 '{text_to_find}' 出现，最长等待 {timeout} 秒...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        ocr_result = find_text(app, ocr, engine, text_to_find, region, match_mode)
        if ocr_result.found:
            logger.info(f"成功等到文本 '{ocr_result.text}'！")
            return ocr_result
        logger.debug(f"尚未等到文本，将在 {interval} 秒后重试...")
        time.sleep(interval)
    logger.warning(f"超时 {timeout} 秒，未能等到文本 '{text_to_find}'。")
    return OcrResult(found=False)


@register_action(name="wait_for_text_to_disappear", public=True)
@requires_services(ocr='ocr', app='app')
def wait_for_text_to_disappear(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_monitor: str,
                               timeout: float = 10.0, interval: float = 1.0,
                               region: Optional[tuple[int, int, int, int]] = None,
                               match_mode: str = "contains") -> bool:
    """
    在指定时间内轮询等待某个文本消失。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        ocr (OcrService): 注入的OCR服务。
        engine (ExecutionEngine): 注入的执行引擎。
        text_to_monitor (str): 要等待其消失的文本。
        timeout (float): 最大等待时间。
        interval (float): 轮询间隔。
        region (Optional[tuple[int, int, int, int]]): 查找区域。
        match_mode (str): 匹配模式。

    Returns:
        bool: 如果文本在超时前消失，则返回 True。
    """
    logger.info(f"开始等待文本 '{text_to_monitor}' 消失，最长等待 {timeout} 秒...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        ocr_result = find_text(app, ocr, engine, text_to_monitor, region, match_mode)
        if not ocr_result.found:
            logger.info(f"文本 '{text_to_monitor}' 已消失。等待成功！")
            return True
        logger.debug(f"文本仍然存在，将在 {interval} 秒后重试...")
        time.sleep(interval)
    logger.warning(f"超时 {timeout} 秒，文本 '{text_to_monitor}' 仍然存在。")
    return False


@register_action(name="wait_for_image", public=True)
@requires_services(vision='vision', app='app')
def wait_for_image(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                   timeout: float = 10.0, interval: float = 1.0, region: Optional[tuple[int, int, int, int]] = None,
                   threshold: float = 0.8) -> MatchResult:
    """
    在指定时间内轮询等待某个图像出现。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        vision (VisionService): 注入的视觉服务。
        engine (ExecutionEngine): 注入的执行引擎。
        template (str): 模板图像的相对路径。
        timeout (float): 最大等待时间。
        interval (float): 轮询间隔。
        region (Optional[tuple[int, int, int, int]]): 查找区域。
        threshold (float): 匹配阈值。

    Returns:
        MatchResult: 如果找到，则返回匹配结果；否则返回 `found=False` 的结果。
    """
    logger.info(f"开始等待图像 '{template}' 出现，最长等待 {timeout} 秒...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        match_result = find_image(app, vision, engine, template, region, threshold)
        if match_result.found:
            logger.info(f"成功等到图像 '{template}'！")
            return match_result
        logger.debug(f"尚未等到图像，将在 {interval} 秒后重试...")
        time.sleep(interval)
    logger.warning(f"超时 {timeout} 秒，未能等到图像 '{template}'。")
    return MatchResult(found=False)


# ==============================================================================
# II. 键鼠控制原子行为 (I/O Control Actions)
# ==============================================================================
@register_action(name="click", public=True)
@requires_services(app='app')
def click(app: AppProviderService, x: Optional[int] = None, y: Optional[int] = None, button: str = 'left',
          clicks: int = 1, interval: float = 0.1):
    """
    模拟鼠标点击。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        x (Optional[int]): 点击位置的 x 坐标。如果为 None，则在当前位置点击。
        y (Optional[int]): 点击位置的 y 坐标。
        button (str): 'left', 'right', 或 'middle'。
        clicks (int): 点击次数。
        interval (float): 多次点击的间隔时间。
    """
    if x is not None and y is not None:
        app.click(x, y, button, clicks, interval)
    else:
        logger.info("在当前鼠标位置点击...")
        app.controller.click(button=button, clicks=clicks, interval=interval)
    return True


@register_action(name="double_click", public=True)
@requires_services(app='app')
def double_click(app: AppProviderService, x: Optional[int] = None, y: Optional[int] = None):
    """
    模拟鼠标左键双击。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        x (Optional[int]): 点击位置的 x 坐标。
        y (Optional[int]): 点击位置的 y 坐标。
    """
    click(app, x, y, button='left', clicks=2, interval=0.05)
    return True


@register_action(name="right_click", public=True)
@requires_services(app='app')
def right_click(app: AppProviderService, x: Optional[int] = None, y: Optional[int] = None):
    """
    模拟鼠标右键单击。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        x (Optional[int]): 点击位置的 x 坐标。
        y (Optional[int]): 点击位置的 y 坐标。
    """
    click(app, x, y, button='right', clicks=1)
    return True


@register_action(name="move_to", public=True)
@requires_services(app='app')
def move_to(app: AppProviderService, x: int, y: int, duration: float = 0.25):
    """
    平滑移动鼠标到指定坐标。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        x (int): 目标 x 坐标。
        y (int): 目标 y 坐标。
        duration (float): 移动持续时间（秒）。
    """
    app.move_to(x, y, duration)
    return True


@register_action(name="drag", public=True)
@requires_services(app='app')
def drag(app: AppProviderService, start_x: int, start_y: int, end_x: int, end_y: int, button: str = 'left',
         duration: float = 0.5):
    """
    模拟鼠标拖拽操作。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        start_x (int): 拖拽起点的 x 坐标。
        start_y (int): 拖拽起点的 y 坐标。
        end_x (int): 拖拽终点的 x 坐标。
        end_y (int): 拖拽终点的 y 坐标。
        button (str): 用于拖拽的鼠标按钮。
        duration (float): 拖拽持续时间。
    """
    app.drag(start_x, start_y, end_x, end_y, button, duration)
    return True


@register_action(name="press_key", public=True)
@requires_services(app='app')
def press_key(app: AppProviderService, key: str, presses: int = 1, interval: float = 0.1):
    """
    模拟按键（按下并松开）。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        key (str): 要按下的键的名称。
        presses (int): 按键次数。
        interval (float): 多次按键的间隔时间。
    """
    app.press_key(key, presses, interval)
    return True


@register_action(name="press_hotkey", public=True)
@requires_services(app='app')
def press_hotkey(app: AppProviderService, keys: List[str]):
    """
    模拟按下组合键（例如 Ctrl+C）。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        keys (List[str]): 要依次按下的键的列表，例如 ['ctrl', 'c']。
    """
    if not isinstance(keys, list) or not keys:
        logger.error("'press_hotkey' 的 'keys' 参数必须是一个非空列表。")
        return False
    logger.info(f"正在按下组合键: {keys}")
    with app.hold_key(keys[0]):
        for key in keys[1:]:
            app.press_key(key)
    return True


@register_action(name="type_text", public=True)
@requires_services(app='app')
def type_text(app: AppProviderService, text: str, interval: float = 0.01):
    """
    模拟输入一段文本。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        text (str): 要输入的文本。
        interval (float): 每个字符之间的输入间隔。
    """
    app.type_text(text, interval)
    return True


@register_action(name="scroll", public=True)
@requires_services(app='app')
def scroll(app: AppProviderService, direction: str, amount: int):
    """
    模拟鼠标滚轮滚动。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        direction (str): 'up' 或 'down'。
        amount (int): 滚动的量。
    """
    direction_map = {"up": 1, "down": -1}
    if direction.lower() not in direction_map:
        logger.error(f"无效的滚动方向: '{direction}'。请使用 'up' 或 'down'。")
        return False
    scroll_amount = amount * direction_map[direction.lower()]
    logger.info(f"向 {direction} 滚动 {amount} 单位。")
    app.scroll(scroll_amount)
    return True


@register_action(name="get_pixel_color", read_only=True, public=True)
@requires_services(app='app')
def get_pixel_color(app: AppProviderService, x: int, y: int) -> tuple:
    """
    获取指定屏幕坐标的像素颜色。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        x (int): 屏幕 x 坐标。
        y (int): 屏幕 y 坐标。

    Returns:
        tuple: (R, G, B) 颜色元组。
    """
    return app.get_pixel_color(x, y)


@register_action(name="mouse_move_relative", public=True)
@requires_services(app='app')
def mouse_move_relative(app: AppProviderService, dx: int, dy: int, duration: float = 0.2):
    """
    相对当前鼠标位置移动鼠标。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        dx (int): x 轴移动距离。
        dy (int): y 轴移动距离。
        duration (float): 移动持续时间。
    """
    app.move_relative(dx, dy, duration)
    return True


@register_action(name="key_down", public=True)
@requires_services(app='app')
def key_down(app: AppProviderService, key: str):
    """
    模拟按下键盘按键（不松开）。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        key (str): 要按下的键。
    """
    app.key_down(key)
    return True


@register_action(name="key_up", public=True)
@requires_services(app='app')
def key_up(app: AppProviderService, key: str):
    """
    模拟松开键盘按键。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        key (str): 要松开的键。
    """
    app.key_up(key)
    return True


@register_action(name="mouse_down", public=True)
@requires_services(app='app')
def mouse_down(app: AppProviderService, button: str = 'left'):
    """
    模拟按下鼠标按钮（不松开）。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        button (str): 要按下的鼠标按钮。
    """
    logger.info(f"按下鼠标 '{button}' 键")
    app.controller.mouse_down(button)
    return True


@register_action(name="mouse_up", public=True)
@requires_services(app='app')
def mouse_up(app: AppProviderService, button: str = 'left'):
    """
    模拟松开鼠标按钮。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        button (str): 要松开的鼠标按钮。
    """
    logger.info(f"松开鼠标 '{button}' 键")
    app.controller.mouse_up(button)
    return True


# ==============================================================================
# III. 流程控制与数据处理行为 (Flow & Data Actions)
# ==============================================================================
@register_action(name="sleep", read_only=True, public=True)
def sleep(seconds: float):
    """
    暂停执行指定的秒数。

    Args:
        seconds (float): 要暂停的秒数。
    """
    time.sleep(seconds)
    return True


@register_action(name="log", read_only=True, public=True)
def log(message: str, level: str = "info"):
    """
    记录一条日志信息。

    Args:
        message (str): 要记录的日志消息。
        level (str): 日志级别 ('info', 'debug', 'warning', 'error', 'critical')。
    """
    level_str = str(level).lower()
    log_func = getattr(logger, level_str, logger.debug)
    log_func(f"[YAML Log] {message}")
    return True


@register_action(name="stop_task", read_only=True)
def stop_task(message: str = "任务已停止", success: bool = True):
    """
    停止当前任务的执行。

    Args:
        message (str): 停止时记录的消息。
        success (bool): 任务是否应被标记为成功。
    """
    raise StopTaskException(message, success)


@register_action(name="assert_condition", read_only=True, public=True)
def assert_condition(condition: bool, message: str = "断言失败"):
    """
    断言一个条件必须为真，否则停止任务。

    Args:
        condition (bool): 要断言的布尔条件。
        message (str): 如果断言失败，要显示的错误消息。
    """
    if not condition:
        raise StopTaskException(message, success=False)
    logger.info(f"断言成功: {message}")
    return True


@register_action(name="set_variable", public=True)
def set_variable(context: ExecutionContext, name: str, value: any) -> bool:
    """
    【已弃用】设置一个变量。在新数据流模型中，此行为无效。
    请使用节点的 `outputs` 块来传递数据。
    """
    logger.warning(f"Action 'set_variable' 在新的数据流模型中已弃用。")
    logger.warning(f"请在节点的 'outputs' 块中定义输出来传递数据。")
    logger.warning(f"尝试设置 '{name}' = {repr(value)} 的操作已被忽略。")
    return False


@register_action(name="string_format", read_only=True, public=True)
def string_format(template: str, *args, **kwargs) -> str:
    """
    格式化一个字符串模板。

    Args:
        template (str): 要格式化的字符串，例如 "Hello, {}!"。
        *args: 用于填充 `{}` 的位置参数。
        **kwargs: 用于填充 `{name}` 的关键字参数。

    Returns:
        str: 格式化后的字符串。
    """
    return template.format(*args, **kwargs)


@register_action(name="string_split", read_only=True, public=True)
def string_split(text: str, separator: str, max_split: int = -1) -> List[str]:
    """
    根据分隔符分割字符串。

    Args:
        text (str): 要分割的字符串。
        separator (str): 分隔符。
        max_split (int): 最大分割次数。

    Returns:
        List[str]: 分割后的字符串列表。
    """
    return text.split(separator, max_split)


@register_action(name="string_join", read_only=True, public=True)
def string_join(items: List[Any], separator: str) -> str:
    """
    使用分隔符连接列表中的所有项。

    Args:
        items (List[Any]): 要连接的项的列表。
        separator (str): 分隔符。

    Returns:
        str: 连接后的字符串。
    """
    return separator.join(str(item) for item in items)


@register_action(name="regex_search", read_only=True, public=True)
def regex_search(text: str, pattern: str) -> Optional[Dict[str, Any]]:
    """
    使用正则表达式在文本中进行搜索。

    Args:
        text (str): 要搜索的文本。
        pattern (str): 正则表达式模式。

    Returns:
        Optional[Dict[str, Any]]: 如果找到匹配项，则返回一个包含匹配信息的字典，
            否则返回 None。
    """
    match = re.search(pattern, text)
    if match:
        return {
            "full_match": match.group(0),
            "groups": match.groups(),
            "named_groups": match.groupdict()
        }
    return None


@register_action(name="math_compute", read_only=True, public=True)
def math_compute(expression: str) -> Any:
    """
    计算一个简单的数学表达式字符串。

    Args:
        expression (str): 要计算的数学表达式，例如 "1 + 2 * 3"。

    Returns:
        Any: 计算结果。如果表达式无效，则返回 None。
    """
    allowed_chars = "0123456789.+-*/() "
    if all(char in allowed_chars for char in expression):
        try:
            return eval(expression)
        except Exception as e:
            logger.error(f"数学表达式计算失败 '{expression}': {e}")
            return None
    logger.error(f"表达式 '{expression}' 包含不允许的字符。")
    return None


# ==============================================================================
# IV. 状态与系统行为 (State & System Actions)
# ==============================================================================
@register_action(name="publish_event", public=True)
@requires_services(event_bus='event_bus')
async def publish_event(event_bus: EventBus, name: str, payload: Dict[str, Any] = None,
                        source: Optional[str] = None,
                        channel: str = "global") -> bool:
    """
    向事件总线发布一个事件。

    Args:
        event_bus (EventBus): 注入的事件总线服务。
        name (str): 事件的名称。
        payload (Dict[str, Any]): 事件的负载数据。
        source (Optional[str]): 事件的来源标识。
        channel (str): 要发布到的频道。

    Returns:
        bool: 如果发布成功，返回 True。
    """
    try:
        event_source = source or 'unknown_task'
        new_event = Event(name=name, channel=channel, payload=payload or {}, source=event_source)
        await event_bus.publish(new_event)
        return True
    except Exception as e:
        logger.error(f"发布事件 '{name}' 时失败: {e}", exc_info=True)
        return False


@register_action(name="get_window_size", read_only=True, public=True)
@requires_services(app='app')
def get_window_size(app: AppProviderService) -> Optional[Tuple[int, int]]:
    """
    获取目标窗口的尺寸。

    Args:
        app (AppProviderService): 注入的应用提供者服务。

    Returns:
        Optional[Tuple[int, int]]: (宽度, 高度) 元组，如果找不到窗口则为 None。
    """
    return app.get_window_size()


@register_action(name="focus_window", public=True)
@requires_services(app='app')
def focus_window(app: AppProviderService) -> bool:
    """
    激活目标窗口并使其获得焦点。

    Args:
        app (AppProviderService): 注入的应用提供者服务。

    Returns:
        bool: 如果成功，返回 True。
    """
    return app.screen.focus()


@register_action(name="file_read", read_only=True, public=True)
def file_read(engine: ExecutionEngine, file_path: str) -> Optional[str]:
    """
    从方案目录中读取一个文件的内容。

    Args:
        engine (ExecutionEngine): 注入的执行引擎，用于获取方案路径。
        file_path (str): 相对于方案根目录的文件路径。

    Returns:
        Optional[str]: 文件的文本内容，如果失败则为 None。
    """
    try:
        full_path = engine.orchestrator.current_plan_path / file_path
        if not full_path.is_file():
            logger.error(f"文件读取失败：'{file_path}' 不存在或不是一个文件。")
            return None
        return full_path.read_text('utf-8')
    except Exception as e:
        logger.error(f"读取文件 '{file_path}' 时发生错误: {e}")
        return None


@register_action(name="file_write", public=True)
def file_write(engine: ExecutionEngine, file_path: str, content: str, append: bool = False) -> bool:
    """
    将内容写入到方案目录中的一个文件。

    Args:
        engine (ExecutionEngine): 注入的执行引擎。
        file_path (str): 相对于方案根目录的文件路径。
        content (str): 要写入的内容。
        append (bool): 是否以追加模式写入。默认为 False（覆盖）。

    Returns:
        bool: 如果写入成功，返回 True。
    """
    try:
        full_path = engine.orchestrator.current_plan_path / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        mode = 'a' if append else 'w'
        full_path.write_text(content, encoding='utf-8')
        return True
    except Exception as e:
        logger.error(f"写入文件 '{file_path}' 时发生错误: {e}")
        return False


# ==============================================================================
# V. 复合与高级行为 (Compound & Advanced Actions)
# ==============================================================================
@register_action(name="find_image_and_click", public=True)
@requires_services(vision='vision', app='app')
def find_image_and_click(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                         region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8,
                         button: str = 'left', move_duration: float = 0.2) -> bool:
    """
    查找指定的图像，如果找到，则点击其中心点。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        vision (VisionService): 注入的视觉服务。
        engine (ExecutionEngine): 注入的执行引擎。
        template (str): 模板图像的相对路径。
        region (Optional[tuple[int, int, int, int]]): 查找区域。
        threshold (float): 匹配阈值。
        button (str): 要使用的鼠标按钮。
        move_duration (float): 移动到目标点的持续时间。

    Returns:
        bool: 如果成功找到并点击，返回 True。
    """
    match_result = find_image(app, vision, engine, template, region, threshold)
    if match_result.found:
        found_x, found_y = match_result.center_point
        logger.info(f"图像找到，位于窗口坐标 ({found_x}, {found_y})，置信度: {match_result.confidence:.2f}")
        app.move_to(found_x, found_y, duration=move_duration)
        app.click(x=found_x, y=found_y, button=button)
        logger.info("点击操作完成。")
        return True
    else:
        logger.warning(f"未能在指定区域找到图像 '{template}'。")
        return False


@register_action(name="find_text_and_click", public=True)
@requires_services(ocr='ocr', app='app')
def find_text_and_click(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str,
                        region: Optional[tuple[int, int, int, int]] = None, match_mode: str = "contains",
                        button: str = 'left', move_duration: float = 0.2) -> bool:
    """
    查找指定的文本，如果找到，则点击其中心点。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        ocr (OcrService): 注入的OCR服务。
        engine (ExecutionEngine): 注入的执行引擎。
        text_to_find (str): 要查找的文本。
        region (Optional[tuple[int, int, int, int]]): 查找区域。
        match_mode (str): 文本匹配模式。
        button (str): 要使用的鼠标按钮。
        move_duration (float): 移动到目标点的持续时间。

    Returns:
        bool: 如果成功找到并点击，返回 True。
    """
    ocr_result = find_text(app, ocr, engine, text_to_find, region, match_mode)
    if ocr_result.found:
        found_x, found_y = ocr_result.center_point
        logger.info(
            f"文本找到: '{ocr_result.text}'，位于窗口坐标 ({found_x}, {found_y})，置信度: {ocr_result.confidence:.2f}")
        app.move_to(found_x, found_y, duration=move_duration)
        app.click(x=found_x, y=found_y, button=button)
        logger.info("点击操作完成。")
        return True
    else:
        logger.warning(f"未能在指定区域找到文本 '{text_to_find}'。")
        return False


@register_action(name="drag_to_find", public=True)
@requires_services(vision='vision', app='app')
def drag_to_find(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, drag_from_template: str,
                 drag_to_template: str, from_region: Optional[tuple[int, int, int, int]] = None,
                 to_region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8,
                 duration: float = 0.5) -> bool:
    """
    查找起点和终点图像，并执行从起点到终点的拖拽操作。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        vision (VisionService): 注入的视觉服务。
        engine (ExecutionEngine): 注入的执行引擎。
        drag_from_template (str): 起点图像的相对路径。
        drag_to_template (str): 终点图像的相对路径。
        from_region (Optional): 起点图像的查找区域。
        to_region (Optional): 终点图像的查找区域。
        threshold (float): 图像匹配阈值。
        duration (float): 拖拽持续时间。

    Returns:
        bool: 如果操作成功，返回 True。
    """
    source_match = find_image(app, vision, engine, drag_from_template, from_region, threshold)
    if not source_match.found:
        logger.error(f"拖拽失败：找不到起点图像 '{drag_from_template}'。")
        return False
    target_match = find_image(app, vision, engine, drag_to_template, to_region, threshold)
    if not target_match.found:
        logger.error(f"拖拽失败：找不到终点图像 '{drag_to_template}'。")
        return False
    start_x, start_y = source_match.center_point
    end_x, end_y = target_match.center_point
    logger.info(f"执行拖拽: 从 {start_x, start_y} 到 {end_x, end_y}")
    app.drag(start_x, start_y, end_x, end_y, duration=duration)
    return True


# --- 占位符与脚本执行行为 ---
@register_action(name="run_task", public=True)
def run_task(engine: ExecutionEngine, task_name: str, plan_name: Optional[str] = None):
    """
    【占位符】执行一个子任务。

    这是一个特殊的行为，其逻辑完全由 `ExecutionEngine` 在内部处理，
    用于实现任务的嵌套调用。
    """
    pass


@register_action(name="scan_and_find_best_match", read_only=True, public=True)
@requires_services(vision='vision', app='app')
def scan_and_find_best_match(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                             region: tuple[int, int, int, int], priority: str = 'top',
                             threshold: float = 0.8) -> MatchResult:
    """
    扫描指定区域，查找所有匹配的图像，并根据优先级规则返回最佳匹配项。

    Args:
        app (AppProviderService): 注入的应用提供者服务。
        vision (VisionService): 注入的视觉服务。
        engine (ExecutionEngine): 注入的执行引擎。
        template (str): 模板图像的相对路径。
        region (tuple[int, int, int, int]): 要扫描的区域。
        priority (str): 最佳匹配规则 ('top', 'bottom', 'left', 'right')。
        threshold (float): 匹配阈值。

    Returns:
        MatchResult: 最佳匹配项的结果。
    """
    logger.info(f"扫描区域寻找最佳匹配项 '{template}'，优先级: {priority}")
    multi_match_result = find_all_images(app, vision, engine, template, region, threshold)
    if not multi_match_result.matches:
        logger.warning("在扫描区域内未找到任何匹配项。")
        return MatchResult(found=False)
    matches = multi_match_result.matches

    priority_map = {
        'top': lambda m: m.center_point[1],
        'bottom': lambda m: -m.center_point[1],
        'left': lambda m: m.center_point[0],
        'right': lambda m: -m.center_point[0]
    }

    if priority not in priority_map:
        logger.error(f"无效的优先级规则: '{priority}'。")
        return MatchResult(found=False)

    best_match = min(matches, key=priority_map[priority]) if priority in ['top', 'left'] else max(matches,
                                                                                                  key=priority_map[
                                                                                                      priority])

    logger.info(f"找到最佳匹配项，位于 {best_match.center_point}")
    return best_match





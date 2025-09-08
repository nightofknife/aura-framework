# aura_official_packages/aura_base/actions/atomic_actions.py (增强版)

import ast
import time
from typing import Optional, Any, Dict, List, Tuple
import re
import cv2
import os

# --- 核心导入 ---
from packages.aura_core.api import register_action, requires_services
from packages.aura_core.engine import ExecutionEngine, Context
from packages.aura_core.event_bus import EventBus, Event
from packages.aura_core.exceptions import StopTaskException
from packages.aura_core.persistent_context import PersistentContext
from packages.aura_core.state_store import StateStore
from packages.aura_core.logger import logger
# --- 服务与数据模型导入 (来自本包) ---
from ..services.app_provider_service import AppProviderService
from ..services.ocr_service import OcrService, OcrResult, MultiOcrResult
from ..services.vision_service import VisionService, MatchResult, MultiMatchResult


# ==============================================================================
# I. 视觉与OCR原子行为 (Vision & OCR Actions)
# ==============================================================================

# --- Find Actions (查找信息) ---
# (find_image, find_all_images, find_image_in_scrolling_area, find_text, recognize_all_text, get_text_in_region 保持不变)
@register_action(name="find_image", read_only=True, public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def find_image(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str, region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8) -> MatchResult:
    # ... (代码不变)
    is_inspect_mode = engine.context.get("__is_inspect_mode__", False)
    capture = app.capture(rect=region)
    if not capture.success:
        logger.error("行为 'find_image' 失败：无法截图。")
        return MatchResult(found=False)
    source_image_for_debug = capture.image.copy()
    plan_path = engine.orchestrator.current_plan_path
    full_template_path = plan_path / template
    match_result = vision.find_template(source_image=source_image_for_debug, template_image=str(full_template_path), threshold=threshold)
    if match_result.found:
        region_x_offset = region[0] if region else 0
        region_y_offset = region[1] if region else 0
        match_result.top_left = (match_result.top_left[0] + region_x_offset, match_result.top_left[1] + region_y_offset)
        match_result.center_point = (match_result.center_point[0] + region_x_offset, match_result.center_point[1] + region_y_offset)
        match_result.rect = (match_result.rect[0] + region_x_offset, match_result.rect[1] + region_y_offset, match_result.rect[2], match_result.rect[3])
    if is_inspect_mode:
        try:
            template_image_for_debug = cv2.imread(str(full_template_path))
            match_result.debug_info.update({"source_image": source_image_for_debug, "template_image": template_image_for_debug, "params": {"template": template, "region": region, "threshold": threshold}})
        except Exception as e:
            logger.error(f"打包调试信息时出错: {e}")
    return match_result

@register_action(name="find_all_images", read_only=True, public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def find_all_images(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str, region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8) -> MultiMatchResult:
    # ... (代码不变)
    capture = app.capture(rect=region)
    if not capture.success:
        logger.error("行为 'find_all_images' 失败：无法截图。")
        return MultiMatchResult()
    plan_path = engine.orchestrator.current_plan_path
    full_template_path = plan_path / template
    multi_match_result = vision.find_all_templates(source_image=capture.image, template_image=str(full_template_path), threshold=threshold)
    region_x_offset = region[0] if region else 0
    region_y_offset = region[1] if region else 0
    for match in multi_match_result.matches:
        match.top_left = (match.top_left[0] + region_x_offset, match.top_left[1] + region_y_offset)
        match.center_point = (match.center_point[0] + region_x_offset, match.center_point[1] + region_y_offset)
        match.rect = (match.rect[0] + region_x_offset, match.rect[1] + region_y_offset, match.rect[2], match.rect[3])
    return multi_match_result

@register_action(name="find_image_in_scrolling_area", public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def find_image_in_scrolling_area(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str, scroll_area: tuple[int, int, int, int], scroll_direction: str = 'down', max_scrolls: int = 5, scroll_amount: int = 200, threshold: float = 0.8, delay_after_scroll: float = 0.5) -> MatchResult:
    # ... (代码不变)
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
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def find_text(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str, region: Optional[tuple[int, int, int, int]] = None, match_mode: str = "exact") -> OcrResult:
    is_inspect_mode = engine.context.get("__is_inspect_mode__", False)
    capture = app.capture(rect=region)
    if not capture.success:
        logger.error("行为 'find_text' 失败：无法截图。")
        return OcrResult(found=False)
    source_image_for_debug = capture.image.copy()
    ocr_result = ocr.find_text(source_image=source_image_for_debug, text_to_find=text_to_find, match_mode=match_mode)
    if ocr_result.found:
        region_x_offset = region[0] if region else 0
        region_y_offset = region[1] if region else 0
        ocr_result.center_point = (ocr_result.center_point[0] + region_x_offset, ocr_result.center_point[1] + region_y_offset)
        ocr_result.rect = (ocr_result.rect[0] + region_x_offset, ocr_result.rect[1] + region_y_offset, ocr_result.rect[2], ocr_result.rect[3])
    if is_inspect_mode:
        ocr_result.debug_info.update({"source_image": source_image_for_debug, "params": {"text_to_find": text_to_find, "region": region, "match_mode": match_mode}})
    return ocr_result

@register_action(name="recognize_all_text", read_only=True, public=True)
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def recognize_all_text(app: AppProviderService, ocr: OcrService, region: Optional[tuple[int, int, int, int]] = None) -> MultiOcrResult:
    # ... (代码不变)
    capture = app.capture(rect=region)
    if not capture.success:
        logger.error("行为 'recognize_all_text' 失败：无法截图。")
        return MultiOcrResult()
    multi_ocr_result = ocr.recognize_all(source_image=capture.image)
    region_x_offset = region[0] if region else 0
    region_y_offset = region[1] if region else 0
    for result in multi_ocr_result.results:
        result.center_point = (result.center_point[0] + region_x_offset, result.center_point[1] + region_y_offset)
        result.rect = (result.rect[0] + region_x_offset, result.rect[1] + region_y_offset, result.rect[2], result.rect[3])
    return multi_ocr_result

@register_action(name="get_text_in_region", read_only=True, public=True)
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def get_text_in_region(app: AppProviderService, ocr: OcrService, region: tuple[int, int, int, int], whitelist: Optional[str] = None, join_with: str = " ") -> str:
    # ... (代码不变)
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
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def check_text_exists(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str, region: Optional[tuple[int, int, int, int]] = None, match_mode: str = "exact") -> bool:
    """【新】检查指定的文本是否存在，并直接返回布尔值 True/False。专为条件检查和状态规划设计。"""
    ocr_result = find_text(app, ocr, engine, text_to_find, region, match_mode)
    return ocr_result.found

@register_action(name="check_image_exists", read_only=True, public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def check_image_exists(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str, region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8) -> bool:
    """【新】检查指定的图像是否存在，并直接返回布尔值 True/False。专为条件检查和状态规划设计。"""
    match_result = find_image(app, vision, engine, template, region, threshold)
    return match_result.found

# --- Assert Actions (断言条件，失败则中断) ---
# (assert_image_exists, assert_image_not_exists, assert_text_exists, assert_text_not_exists 保持不变)
@register_action(name="assert_image_exists", read_only=True, public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def assert_image_exists(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str, region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8, message: Optional[str] = None):
    # ... (代码不变)
    match_result = find_image(app, vision, engine, template, region, threshold)
    if not match_result.found:
        error_message = message or f"断言失败：期望的图像 '{template}' 不存在。"
        logger.error(error_message)
        raise StopTaskException(error_message, success=False)
    logger.info(f"断言成功：图像 '{template}' 已确认存在。")
    return True

@register_action(name="assert_image_not_exists", read_only=True, public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def assert_image_not_exists(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str, region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8, message: Optional[str] = None):
    # ... (代码不变)
    match_result = find_image(app, vision, engine, template, region, threshold)
    if match_result.found:
        error_message = message or f"断言失败：不期望的图像 '{template}' 却存在了。"
        logger.error(error_message)
        raise StopTaskException(error_message, success=False)
    logger.info(f"断言成功：图像 '{template}' 已确认不存在。")
    return True

@register_action(name="assert_text_exists", read_only=True, public=True)
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def assert_text_exists(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str, region: Optional[tuple[int, int, int, int]] = None, match_mode: str = "contains", message: Optional[str] = None):
    # ... (代码不变)
    ocr_result = find_text(app, ocr, engine, text_to_find, region, match_mode)
    if not ocr_result.found:
        error_message = message or f"断言失败：期望的文本 '{text_to_find}' 不存在。"
        logger.error(error_message)
        raise StopTaskException(error_message, success=False)
    logger.info(f"断言成功：文本 '{text_to_find}' 已确认存在。")
    return True

@register_action(name="assert_text_not_exists", read_only=True, public=True)
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def assert_text_not_exists(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str, region: Optional[tuple[int, int, int, int]] = None, match_mode: str = "contains", message: Optional[str] = None):
    # ... (代码不变)
    ocr_result = find_text(app, ocr, engine, text_to_find, region, match_mode)
    if ocr_result.found:
        error_message = message or f"断言失败：不期望的文本 '{ocr_result.text}' 却存在了。"
        logger.error(error_message)
        raise StopTaskException(error_message, success=False)
    logger.info(f"断言成功：文本 '{text_to_find}' 已确认不存在。")
    return True

@register_action(name="assert_text_equals", read_only=True, public=True)
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def assert_text_equals(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str, expected_value: str, region: Optional[tuple[int, int, int, int]] = None, message: Optional[str] = None):
    """【新】断言找到的文本内容必须精确等于期望值。"""
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
# (wait_for_text, wait_for_text_to_disappear, wait_for_image 保持不变)
@register_action(name="wait_for_text", public=True)
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def wait_for_text(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str, timeout: float = 10.0, interval: float = 1.0, region: Optional[tuple[int, int, int, int]] = None, match_mode: str = "contains") -> OcrResult:
    # ... (代码不变)
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
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def wait_for_text_to_disappear(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_monitor: str, timeout: float = 10.0, interval: float = 1.0, region: Optional[tuple[int, int, int, int]] = None, match_mode: str = "contains") -> bool:
    # ... (代码不变)
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
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def wait_for_image(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str, timeout: float = 10.0, interval: float = 1.0, region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8) -> MatchResult:
    # ... (代码不变)
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
# (click, move_to, drag, press_key, type_text, scroll, get_pixel_color, mouse_move_relative, key_down, key_up 保持不变)
@register_action(name="click", public=True)
@requires_services(app='Aura-Project/base/app')
def click(app: AppProviderService, x: Optional[int] = None, y: Optional[int] = None, button: str = 'left', clicks: int = 1, interval: float = 0.1):
    # ... (代码不变)
    if x is not None and y is not None:
        app.click(x, y, button, clicks, interval)
    else:
        logger.info("在当前鼠标位置点击...")
        app.controller.click(button=button, clicks=clicks, interval=interval)
    return True

@register_action(name="double_click", public=True)
@requires_services(app='Aura-Project/base/app')
def double_click(app: AppProviderService, x: Optional[int] = None, y: Optional[int] = None):
    """【新】在指定坐标或当前位置执行鼠标双击。"""
    click(app, x, y, button='left', clicks=2, interval=0.05)
    return True

@register_action(name="right_click", public=True)
@requires_services(app='Aura-Project/base/app')
def right_click(app: AppProviderService, x: Optional[int] = None, y: Optional[int] = None):
    """【新】在指定坐标或当前位置执行鼠标右键单击。"""
    click(app, x, y, button='right', clicks=1)
    return True

@register_action(name="move_to", public=True)
@requires_services(app='Aura-Project/base/app')
def move_to(app: AppProviderService, x: int, y: int, duration: float = 0.25):
    # ... (代码不变)
    app.move_to(x, y, duration)
    return True

@register_action(name="drag", public=True)
@requires_services(app='Aura-Project/base/app')
def drag(app: AppProviderService, start_x: int, start_y: int, end_x: int, end_y: int, button: str = 'left', duration: float = 0.5):
    # ... (代码不变)
    app.drag(start_x, start_y, end_x, end_y, button, duration)
    return True

@register_action(name="press_key", public=True)
@requires_services(app='Aura-Project/base/app')
def press_key(app: AppProviderService, key: str, presses: int = 1, interval: float = 0.1):
    # ... (代码不变)
    app.press_key(key, presses, interval)
    return True

@register_action(name="press_hotkey", public=True)
@requires_services(app='Aura-Project/base/app')
def press_hotkey(app: AppProviderService, keys: List[str]):
    """【新】按下组合键，例如 ['ctrl', 's']。"""
    if not isinstance(keys, list) or not keys:
        logger.error("'press_hotkey' 的 'keys' 参数必须是一个非空列表。")
        return False
    logger.info(f"正在按下组合键: {keys}")
    with app.hold_key(keys[0]):
        for key in keys[1:]:
            app.press_key(key)
    return True

@register_action(name="type_text", public=True)
@requires_services(app='Aura-Project/base/app')
def type_text(app: AppProviderService, text: str, interval: float = 0.01):
    # ... (代码不变)
    app.type_text(text, interval)
    return True

@register_action(name="scroll", public=True)
@requires_services(app='Aura-Project/base/app')
def scroll(app: AppProviderService, direction: str, amount: int):
    # ... (代码不变)
    direction_map = {"up": 1, "down": -1}
    if direction.lower() not in direction_map:
        logger.error(f"无效的滚动方向: '{direction}'。请使用 'up' 或 'down'。")
        return False
    scroll_amount = amount * direction_map[direction.lower()]
    logger.info(f"向 {direction} 滚动 {amount} 单位。")
    app.scroll(scroll_amount)
    return True

@register_action(name="get_pixel_color", read_only=True, public=True)
@requires_services(app='Aura-Project/base/app')
def get_pixel_color(app: AppProviderService, x: int, y: int) -> tuple:
    # ... (代码不变)
    return app.get_pixel_color(x, y)

@register_action(name="mouse_move_relative", public=True)
@requires_services(app='Aura-Project/base/app')
def mouse_move_relative(app: AppProviderService, dx: int, dy: int, duration: float = 0.2):
    # ... (代码不变)
    app.move_relative(dx, dy, duration)
    return True

@register_action(name="key_down", public=True)
@requires_services(app='Aura-Project/base/app')
def key_down(app: AppProviderService, key: str):
    # ... (代码不变)
    app.key_down(key)
    return True

@register_action(name="key_up", public=True)
@requires_services(app='Aura-Project/base/app')
def key_up(app: AppProviderService, key: str):
    # ... (代码不变)
    app.key_up(key)
    return True

@register_action(name="mouse_down", public=True)
@requires_services(app='Aura-Project/base/app')
def mouse_down(app: AppProviderService, button: str = 'left'):
    """【新】在当前鼠标位置按下鼠标按键并保持。"""
    logger.info(f"按下鼠标 '{button}' 键")
    app.controller.mouse_down(button)
    return True

@register_action(name="mouse_up", public=True)
@requires_services(app='Aura-Project/base/app')
def mouse_up(app: AppProviderService, button: str = 'left'):
    """【新】在当前鼠标位置松开鼠标按键。"""
    logger.info(f"松开鼠标 '{button}' 键")
    app.controller.mouse_up(button)
    return True

# ==============================================================================
# III. 流程控制与数据处理行为 (Flow & Data Actions)
# ==============================================================================
# (sleep, log, stop_task, assert_condition, set_variable, string_format 保持不变)
@register_action(name="sleep", read_only=True, public=True)
def sleep(seconds: float):
    # ... (代码不变)
    time.sleep(seconds)
    return True

@register_action(name="log", read_only=True, public=True)
def log(message: str, level: str = "info"):
    # ... (代码不变)
    level_str = str(level).lower()
    if level_str == "info":
        logger.info(f"[YAML Log] {message}")
    elif level_str == "warning":
        logger.warning(f"[YAML Log] {message}")
    elif level_str == "error":
        logger.error(f"[YAML Log] {message}")
    else:
        logger.debug(f"[YAML Log] {message}")
    return True


@register_action(name="stop_task", read_only=True)
def stop_task(message: str = "任务已停止", success: bool = True):
    # ... (代码不变)
    raise StopTaskException(message, success)


@register_action(name="assert_condition", read_only=True, public=True)
def assert_condition(condition: bool, message: str = "断言失败"):
    # ... (代码不变)
    if not condition:
        raise StopTaskException(message, success=False)
    logger.info(f"断言成功: {message}")
    return True


@register_action(name="set_variable", public=True)
def set_variable(context: Context, name: str, value: any) -> bool:
    # ... (代码不变)
    try:
        context.set(name, value)
        logger.info(f"设置上下文变量 '{name}' = {repr(value)}")
        return True
    except Exception as e:
        logger.error(f"设置变量 '{name}' 时失败: {e}", exc_info=True)
        return False


@register_action(name="string_format", read_only=True, public=True)
def string_format(template: str, *args, **kwargs) -> str:
    # ... (代码不变)
    return template.format(*args, **kwargs)


@register_action(name="string_split", read_only=True, public=True)
def string_split(text: str, separator: str, max_split: int = -1) -> List[str]:
    """【新】使用指定的分隔符分割字符串，并返回一个列表。"""
    return text.split(separator, max_split)


@register_action(name="string_join", read_only=True, public=True)
def string_join(items: List[Any], separator: str) -> str:
    """【新】将列表中的所有项目连接成一个字符串。"""
    return separator.join(str(item) for item in items)


@register_action(name="regex_search", read_only=True, public=True)
def regex_search(text: str, pattern: str) -> Optional[Dict[str, Any]]:
    """【新】使用正则表达式搜索文本。如果找到，返回包含匹配组的字典；否则返回 None。"""
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
    """【新】执行一个安全的数学表达式。仅支持基本的数学运算和数字。"""
    # 注意：这是一个非常简化的安全实现。在生产环境中可能需要更强大的库。
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
# (set_persistent_value, save_persistent_context, set_state, get_state, delete_state, publish_event 保持不变)
@register_action("set_persistent_value", public=True)
def set_persistent_value(key: str, value, persistent_context: PersistentContext):
    # ... (代码不变)
    if not isinstance(persistent_context, PersistentContext):
        logger.error("无法设置长期值，因为 'persistent_context' 未正确注入。")
        return False
    logger.info(f"在长期上下文中设置: '{key}' = '{value}' (尚未保存)")
    persistent_context.set(key, value)
    return True


@register_action("save_persistent_context", public=True)
def save_persistent_context(persistent_context: PersistentContext):
    # ... (代码不变)
    if not isinstance(persistent_context, PersistentContext):
        logger.error("无法保存长期上下文，因为 'persistent_context' 未正确注入。")
        return False
    return persistent_context.save()


@register_action(name="set_state", public=True)
@requires_services(state_store='state_store')
def set_state(state_store: StateStore, key: str, value: Any, ttl: Optional[float] = None) -> bool:
    # ... (代码不变)
    try:
        state_store.set(key, value, ttl)
        if ttl:
            logger.info(f"设置驻留信号 '{key}' = {repr(value)} (TTL: {ttl}s)")
        else:
            logger.info(f"设置驻留信号 '{key}' = {repr(value)}")
        return True
    except Exception as e:
        logger.error(f"设置驻留信号 '{key}' 时失败: {e}", exc_info=True)
        return False


@register_action(name="get_state", read_only=True, public=True)
@requires_services(state_store='state_store')
def get_state(state_store: StateStore, context: Context, key: str, default: Any = None,
              output_to: Optional[str] = None) -> Any:
    # ... (代码不变)
    value = state_store.get(key, default)
    if output_to:
        context.set(output_to, value)
        found = value is not default
        logger.info(f"获取驻留信号 '{key}' -> '{output_to}' (找到: {found})")
        return found
    else:
        logger.info(f"获取驻留信号 '{key}' -> 返回值")
        return value


@register_action(name="delete_state", public=True)
@requires_services(state_store='state_store')
def delete_state(state_store: StateStore, key: str) -> bool:
    # ... (代码不变)
    try:
        deleted = state_store.delete(key)
        if deleted:
            logger.info(f"删除了驻留信号 '{key}'")
        else:
            logger.info(f"尝试删除驻留信号 '{key}'，但它不存在。")
        return True
    except Exception as e:
        logger.error(f"删除驻留信号 '{key}' 时失败: {e}", exc_info=True)
        return False


@register_action(name="publish_event", public=True)
@requires_services(event_bus='event_bus')
def publish_event(event_bus: EventBus, context: Context, name: str, payload: Dict[str, Any] = None,
                  source: Optional[str] = None) -> bool:
    # ... (代码不变)
    try:
        causation_chain = []
        depth = 0
        triggering_event = context.get_triggering_event()
        if triggering_event:
            causation_chain.extend(triggering_event.causation_chain)
            depth = triggering_event.depth + 1
        event_source = source or context.get('__task_name__', 'unknown_task')
        new_event = Event(name=name, payload=payload or {}, source=event_source, causation_chain=causation_chain,
                          depth=depth)
        event_bus.publish(new_event)
        return True
    except Exception as e:
        logger.error(f"发布事件 '{name}' 时失败: {e}", exc_info=True)
        return False


@register_action(name="get_window_size", read_only=True, public=True)
@requires_services(app='Aura-Project/base/app')
def get_window_size(app: AppProviderService) -> Optional[Tuple[int, int]]:
    """【新】获取当前目标窗口的尺寸 (宽度, 高度)。"""
    return app.get_window_size()


@register_action(name="focus_window", public=True)
@requires_services(app='Aura-Project/base/app')
def focus_window(app: AppProviderService) -> bool:
    """【新】将目标应用窗口置于最前台并激活。"""
    return app.screen.focus()


@register_action(name="file_read", read_only=True, public=True)
def file_read(engine: ExecutionEngine, file_path: str) -> Optional[str]:
    """【新】从方案包目录内读取一个文件的内容。"""
    try:
        full_path = engine.orchestrator.current_plan_path / file_path
        if not full_path.is_file():
            logger.error(f"文件读取失败：'{file_path}' 不存在或不是一个文件。")
            return None
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"读取文件 '{file_path}' 时发生错误: {e}")
        return None


@register_action(name="file_write", public=True)
def file_write(engine: ExecutionEngine, file_path: str, content: str, append: bool = False) -> bool:
    """【新】向方案包目录内的一个文件写入内容。"""
    try:
        full_path = engine.orchestrator.current_plan_path / file_path
        # 确保目录存在
        full_path.parent.mkdir(parents=True, exist_ok=True)
        mode = 'a' if append else 'w'
        with open(full_path, mode, encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception as e:
        logger.error(f"写入文件 '{file_path}' 时发生错误: {e}")
        return False


# ==============================================================================
# V. 复合与高级行为 (Compound & Advanced Actions)
# ==============================================================================
# (find_image_and_click, find_text_and_click, drag_to_find 等保持不变)
@register_action(name="find_image_and_click", public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def find_image_and_click(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                         region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8,
                         button: str = 'left', move_duration: float = 0.2) -> bool:
    # ... (代码不变)
    match_result = find_image(app, vision, engine, template, region, threshold)
    if match_result.found:
        logger.info(f"图像找到，位于窗口坐标 {match_result.center_point}，置信度: {match_result.confidence:.2f}")
        app.move_to(match_result.center_point[0], match_result.center_point[1], duration=move_duration)
        app.click(match_result.center_point[0], match_result.center_point[1], button=button)
        logger.info("点击操作完成。")
        return True
    else:
        logger.warning(f"未能在指定区域找到图像 '{template}'。")
        return False


@register_action(name="find_text_and_click", public=True)
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def find_text_and_click(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str,
                        region: Optional[tuple[int, int, int, int]] = None, match_mode: str = "contains",
                        button: str = 'left', move_duration: float = 0.2) -> bool:
    # ... (代码不变)
    ocr_result = find_text(app, ocr, engine, text_to_find, region, match_mode)
    if ocr_result.found:
        logger.info(
            f"文本找到: '{ocr_result.text}'，位于窗口坐标 {ocr_result.center_point}，置信度: {ocr_result.confidence:.2f}")
        app.move_to(ocr_result.center_point[0], ocr_result.center_point[1], duration=move_duration)
        app.click(ocr_result.center_point[0], ocr_result.center_point[1], button=button)
        logger.info("点击操作完成。")
        return True
    else:
        logger.warning(f"未能在指定区域找到文本 '{text_to_find}'。")
        return False


@register_action(name="drag_to_find", public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def drag_to_find(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, drag_from_template: str,
                 drag_to_template: str, from_region: Optional[tuple[int, int, int, int]] = None,
                 to_region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8,
                 duration: float = 0.5) -> bool:
    # ... (代码不变)
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


# (其他旧的复合行为保持不变)
# ...

# --- 占位符与脚本执行行为 ---
# (run_task, run_python_script, run_python, log_test_step 保持不变)
@register_action(name="run_task", public=True)
def run_task(engine, task_name: str, plan_name: str = None):
    pass  # 由引擎实现


@register_action(name="run_python_script", public=True)
def run_python_script(engine: ExecutionEngine, context: Context, script_path: str, **kwargs) -> Any:
    # ... (代码不变)
    orchestrator = engine.orchestrator
    if not orchestrator:
        logger.error("'run_python_script' 无法执行，因为未关联到编排器。")
        return False
    full_script_path = orchestrator.current_plan_path / script_path
    if not full_script_path.is_file():
        logger.error(f"找不到Python脚本: {full_script_path}")
        return False
    logger.info(f"--- 开始执行Python脚本: {script_path} ---")
    try:
        with open(full_script_path, 'r', encoding='utf-8') as f:
            script_code = f.read()
        AuraApi_class = context.get('AuraApi')
        aura_instance = AuraApi_class(orchestrator, engine, kwargs)
        script_globals = {'aura': aura_instance}
        wrapped_code = f"def __aura_script_executor__():\n" + "".join(
            f"    {line}\n" for line in script_code.splitlines())
        exec(wrapped_code, script_globals)
        script_function = script_globals['__aura_script_executor__']
        return_value = script_function()
        logger.info(f"--- Python脚本 '{script_path}' 执行完毕 ---")
        return return_value
    except Exception as e:
        logger.error(f"执行Python脚本 '{script_path}' 时发生严重错误: {e}", exc_info=True)
        return False

@register_action(name="run_python", public=True)
@requires_services()
def run_python(context: Context, code: str) -> Any:
    # ... (代码不变)
    if not isinstance(code, str):
        logger.error(f"'run_python' 的 'code' 参数必须是字符串，但收到了 {type(code)}。")
        return None
    logger.debug(f"准备执行 Python 代码:\n---\n{code}\n---")
    try:
        execution_scope = {'ctx': context._data}
        try:
            parsed_code = ast.parse(code.strip(), mode='eval')
            compiled_code = compile(parsed_code, '<string>', 'eval')
            return_value = eval(compiled_code, execution_scope)
        except SyntaxError:
            wrapped_code = f"def __aura_py_executor__():\n"
            for line in code.strip().splitlines():
                wrapped_code += f"    {line}\n"
            if 'return' not in wrapped_code:
                wrapped_code += "    return None\n"
            exec(wrapped_code, execution_scope)
            script_function = execution_scope['__aura_py_executor__']
            return_value = script_function()
        for key, value in execution_scope['ctx'].items():
            if key not in context._data or context._data[key] is not value:
                context.set(key, value)
                logger.debug(f"Python 代码更新了上下文变量: '{key}'")
        logger.debug(f"Python 代码执行完毕，返回: {repr(return_value)}")
        return return_value
    except Exception as e:
        logger.error(f"执行 Python 代码时发生错误: {e}", exc_info=True)
        return None

@register_action(name="log_test_step", read_only=True, public=True)
def log_test_step(message: str, context_vars: dict = None):
    # ... (代码不变)
    log_message = f"[FrameworkTest] >> {message}"
    if context_vars:
        var_str_list = []
        for key, value in context_vars.items():
            var_str_list.append(f"{key}={repr(value)}")
        log_message += f" ({', '.join(var_str_list)})"
    logger.info(log_message)
    return True

# --- 重新加入之前版本中存在的高级复合行为 ---

@register_action(name="wait_for_any", public=True)
def wait_for_any(engine: ExecutionEngine, conditions: list, timeout: float = 10.0, interval: float = 1.0) -> dict:
    # ... (代码不变)
    logger.info(f"等待 {len(conditions)} 个条件中的任意一个满足，超时 {timeout}s...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        for i, cond_step in enumerate(conditions):
            # 注意：这里假设 _execute_single_action_step 存在且行为符合预期
            if engine._execute_single_action_step(cond_step):
                logger.info(f"条件 {i} 满足！")
                return {"found": True, "index": i}
        time.sleep(interval)
    logger.warning("等待超时，所有条件均未满足。")
    return {"found": False, "index": -1}

@register_action(name="wait_for_color_change", read_only=True, public=True)
@requires_services(app='Aura-Project/base/app')
def wait_for_color_change(app: AppProviderService, x: int, y: int, initial_color: tuple[int, int, int],
                          timeout: float = 10.0, interval: float = 0.2, tolerance: int = 5) -> bool:
    # ... (代码不变)
    logger.info(f"等待坐标 ({x},{y}) 的颜色从 {initial_color} 发生变化，最长等待 {timeout} 秒...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        current_color = app.get_pixel_color(x, y)
        r_diff = abs(current_color[0] - initial_color[0])
        g_diff = abs(current_color[1] - initial_color[1])
        b_diff = abs(current_color[2] - initial_color[2])
        is_still_initial_color = (r_diff + g_diff + b_diff) <= tolerance
        if not is_still_initial_color:
            logger.info(f"颜色已变化为 {current_color}。等待成功！")
            return True
        time.sleep(interval)
    logger.warning(f"超时 {timeout} 秒，坐标 ({x},{y}) 的颜色未发生变化。")
    return False

@register_action(name="scan_and_find_best_match", read_only=True, public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def scan_and_find_best_match(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                             region: tuple[int, int, int, int], priority: str = 'top',
                             threshold: float = 0.8) -> MatchResult:
    # ... (代码不变)
    logger.info(f"扫描区域寻找最佳匹配项 '{template}'，优先级: {priority}")
    multi_match_result = find_all_images(app, vision, engine, template, region, threshold)
    if not multi_match_result.matches:
        logger.warning("在扫描区域内未找到任何匹配项。")
        return MatchResult(found=False)
    matches = multi_match_result.matches
    best_match = None
    if priority == 'top':
        best_match = min(matches, key=lambda m: m.center_point[1])
    elif priority == 'bottom':
        best_match = max(matches, key=lambda m: m.center_point[1])
    elif priority == 'left':
        best_match = min(matches, key=lambda m: m.center_point[0])
    elif priority == 'right':
        best_match = max(matches, key=lambda m: m.center_point[0])
    else:
        logger.error(f"无效的优先级规则: '{priority}'。")
        return MatchResult(found=False)
    logger.info(f"找到最佳匹配项，位于 {best_match.center_point}")
    return best_match

@register_action(name="verify_color_at", read_only=True, public=True)
@requires_services(app='Aura-Project/base/app')
def verify_color_at(app: AppProviderService, x: int, y: int, expected_color: tuple[int, int, int],
                    tolerance: int = 0) -> bool:
    # ... (代码不变)
    actual_color = app.get_pixel_color(x, y)
    if tolerance == 0:
        is_match = actual_color == expected_color
    else:
        r_diff = abs(actual_color[0] - expected_color[0])
        g_diff = abs(actual_color[1] - expected_color[1])
        b_diff = abs(actual_color[2] - expected_color[2])
        is_match = (r_diff + g_diff + b_diff) <= tolerance
    if is_match:
        logger.debug(f"颜色验证成功在 ({x},{y})。期望: {expected_color}, 实际: {actual_color} (容差: {tolerance})")
    else:
        logger.info(f"颜色验证失败在 ({x},{y})。期望: {expected_color}, 实际: {actual_color} (容差: {tolerance})")
    return is_match

@register_action(name="press_sequence", public=True)
def press_sequence(engine: ExecutionEngine, sequence: list) -> bool:
    # ... (代码不变)
    if not isinstance(sequence, list):
        logger.error(f"'press_sequence' 的参数必须是一个列表，但收到了 {type(sequence)}。")
        return False
    logger.info(f"开始执行输入序列，共 {len(sequence)} 个操作。")
    for i, step_data in enumerate(sequence):
        if not isinstance(step_data, dict) or 'action' not in step_data:
            logger.error(f"序列中的第 {i + 1} 项格式错误，它必须是包含 'action' 键的字典。")
            return False
        action_name = step_data.get('action')
        logger.info(f"  - 序列步骤 {i + 1}: 执行 '{action_name}'")
        # 注意：这里假设 _execute_single_action_step 存在且行为符合预期
        if not engine._execute_single_action_step(step_data):
            logger.error(f"序列在执行 '{action_name}' 时失败，序列中止。")
            return False
    logger.info("输入序列成功执行完毕。")
    return True







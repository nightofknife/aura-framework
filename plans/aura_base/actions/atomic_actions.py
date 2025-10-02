# aura_official_packages/aura_base/actions/atomic_actions.py (升级版)

import time
from typing import Optional, Any, Dict, List, Tuple
import re
import cv2
from typing import Any
from pydantic import BaseModel, Field

# --- 核心导入 ---
from packages.aura_core.api import register_action, requires_services
from packages.aura_core.engine import ExecutionEngine
# [MODIFIED] 导入新的ExecutionContext
from packages.aura_core.context import ExecutionContext
from packages.aura_core.event_bus import EventBus, Event
from packages.aura_core.exceptions import StopTaskException
from packages.aura_core.logger import logger
# [MODIFIED] 导入新的StateStoreService
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
# [MODIFIED] 移除旧Context，engine保留
def find_image(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
               region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8) -> MatchResult:
    # [MODIFIED] __is_inspect_mode__ 现在从 initial context 获取
    is_inspect_mode = engine.root_context.data.get("initial", {}).get("__is_inspect_mode__", False)
    capture = app.capture(rect=region)
    if not capture.success:
        logger.error("行为 'find_image' 失败：无法截图。")
        return MatchResult(found=False)

    source_image_for_debug = capture.image.copy()
    # [MODIFIED] plan_path 从 engine.orchestrator 获取
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
# [MODIFIED] 移除旧Context，engine保留
def find_all_images(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                    region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8) -> MultiMatchResult:
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
# [MODIFIED] 移除旧Context，engine保留
def find_image_in_scrolling_area(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                                 scroll_area: tuple[int, int, int, int], scroll_direction: str = 'down',
                                 max_scrolls: int = 5, scroll_amount: int = 200, threshold: float = 0.8,
                                 delay_after_scroll: float = 0.5) -> MatchResult:
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
        # 内部调用也需要传递engine
        match_result = find_image(app, vision, engine, template, region=scroll_area, threshold=threshold)
        if match_result.found:
            logger.info(f"在第 {i} 次滚动后找到图像！")
            return match_result

    logger.warning(f"在滚动 {max_scrolls} 次后，仍未找到图像 '{template}'。")
    return MatchResult(found=False)


@register_action(name="find_text", read_only=True, public=True)
@requires_services(ocr='ocr', app='app')
# [MODIFIED] 移除旧Context，engine保留
def find_text(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str,
              region: Optional[tuple[int, int, int, int]] = None, match_mode: str = "exact") -> OcrResult:
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


# ... (recognize_all_text, get_text_in_region 保持类似修改，移除engine注入因其不再需要)
@register_action(name="recognize_all_text", read_only=True, public=True)
@requires_services(ocr='ocr', app='app')
def recognize_all_text(app: AppProviderService, ocr: OcrService,
                       region: Optional[tuple[int, int, int, int]] = None) -> MultiOcrResult:
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
    ocr_result = find_text(app, ocr, engine, text_to_find, region, match_mode)
    return ocr_result.found


@register_action(name="check_image_exists", read_only=True, public=True)
@requires_services(vision='vision', app='app')
def check_image_exists(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                       region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8) -> bool:
    match_result = find_image(app, vision, engine, template, region, threshold)
    return match_result.found


# --- Assert Actions (断言条件，失败则中断) ---
# ... (所有assert_* actions保持类似修改, 移除旧Context, 保留engine)
@register_action(name="assert_image_exists", read_only=True, public=True)
@requires_services(vision='vision', app='app')
def assert_image_exists(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                        region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8,
                        message: Optional[str] = None):
    match_result = find_image(app, vision, engine, template, region, threshold)
    if not match_result.found:
        error_message = message or f"断言失败：期望的图像 '{template}' 不存在。"
        logger.error(error_message)
        raise StopTaskException(error_message, success=False)
    logger.info(f"断言成功：图像 '{template}' 已确认存在。")
    return True


# ... (其他assert_* actions类似)
@register_action(name="assert_image_not_exists", read_only=True, public=True)
@requires_services(vision='vision', app='app')
def assert_image_not_exists(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                            region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8,
                            message: Optional[str] = None):
    match_result = find_image(app, vision, engine, template, region, threshold)
    if match_result.found:
        error_message = message or f"断言失败：不期望的图像 '{template}' 却存在了。"
        logger.error(error_message)
        raise StopTaskException(error_message, success=False)
    logger.info(f"断言成功：图像 '{template}' 已确认不存在。")
    return True


# [MODIFIED] 接着上一段代码...

@register_action(name="assert_text_exists", read_only=True, public=True)
@requires_services(ocr='ocr', app='app')
def assert_text_exists(app: AppProviderService, ocr: OcrService, engine: ExecutionEngine, text_to_find: str,
                       region: Optional[tuple[int, int, int, int]] = None, match_mode: str = "contains",
                       message: Optional[str] = None):
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
    """断言找到的文本内容必须精确等于期望值。"""
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
# [MODIFIED] 这一部分的所有action都不再需要context或engine，因为它们只与AppProviderService交互。
@register_action(name="click", public=True)
@requires_services(app='app')
def click(app: AppProviderService, x: Optional[int] = None, y: Optional[int] = None, button: str = 'left',
          clicks: int = 1, interval: float = 0.1):
    if x is not None and y is not None:
        app.click(x, y, button, clicks, interval)
    else:
        logger.info("在当前鼠标位置点击...")
        app.controller.click(button=button, clicks=clicks, interval=interval)
    return True


@register_action(name="double_click", public=True)
@requires_services(app='app')
def double_click(app: AppProviderService, x: Optional[int] = None, y: Optional[int] = None):
    click(app, x, y, button='left', clicks=2, interval=0.05)
    return True


@register_action(name="right_click", public=True)
@requires_services(app='app')
def right_click(app: AppProviderService, x: Optional[int] = None, y: Optional[int] = None):
    click(app, x, y, button='right', clicks=1)
    return True


@register_action(name="move_to", public=True)
@requires_services(app='app')
def move_to(app: AppProviderService, x: int, y: int, duration: float = 0.25):
    app.move_to(x, y, duration)
    return True


@register_action(name="drag", public=True)
@requires_services(app='app')
def drag(app: AppProviderService, start_x: int, start_y: int, end_x: int, end_y: int, button: str = 'left',
         duration: float = 0.5):
    app.drag(start_x, start_y, end_x, end_y, button, duration)
    return True


@register_action(name="press_key", public=True)
@requires_services(app='app')
def press_key(app: AppProviderService, key: str, presses: int = 1, interval: float = 0.1):
    app.press_key(key, presses, interval)
    return True


@register_action(name="press_hotkey", public=True)
@requires_services(app='app')
def press_hotkey(app: AppProviderService, keys: List[str]):
    if not isinstance(keys, list) or not keys:
        logger.error("'press_hotkey' 的 'keys' 参数必须是一个非空列表。")
        return False
    logger.info(f"正在按下组合键: {keys}")
    # hold_key需要AppProviderService支持
    with app.hold_key(keys[0]):
        for key in keys[1:]:
            app.press_key(key)
    return True


@register_action(name="type_text", public=True)
@requires_services(app='app')
def type_text(app: AppProviderService, text: str, interval: float = 0.01):
    app.type_text(text, interval)
    return True


@register_action(name="scroll", public=True)
@requires_services(app='app')
def scroll(app: AppProviderService, direction: str, amount: int):
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
    return app.get_pixel_color(x, y)


@register_action(name="mouse_move_relative", public=True)
@requires_services(app='app')
def mouse_move_relative(app: AppProviderService, dx: int, dy: int, duration: float = 0.2):
    app.move_relative(dx, dy, duration)
    return True


@register_action(name="key_down", public=True)
@requires_services(app='app')
def key_down(app: AppProviderService, key: str):
    app.key_down(key)
    return True


@register_action(name="key_up", public=True)
@requires_services(app='app')
def key_up(app: AppProviderService, key: str):
    app.key_up(key)
    return True


@register_action(name="mouse_down", public=True)
@requires_services(app='app')
def mouse_down(app: AppProviderService, button: str = 'left'):
    logger.info(f"按下鼠标 '{button}' 键")
    app.controller.mouse_down(button)
    return True


@register_action(name="mouse_up", public=True)
@requires_services(app='app')
def mouse_up(app: AppProviderService, button: str = 'left'):
    logger.info(f"松开鼠标 '{button}' 键")
    app.controller.mouse_up(button)
    return True


# ==============================================================================
# III. 流程控制与数据处理行为 (Flow & Data Actions)
# ==============================================================================
@register_action(name="sleep", read_only=True, public=True)
def sleep(seconds: float):
    time.sleep(seconds)
    return True


@register_action(name="log", read_only=True, public=True)
def log(message: str, level: str = "info"):
    level_str = str(level).lower()
    log_func = getattr(logger, level_str, logger.debug)
    log_func(f"[YAML Log] {message}")
    return True


@register_action(name="stop_task", read_only=True)
def stop_task(message: str = "任务已停止", success: bool = True):
    raise StopTaskException(message, success)


@register_action(name="assert_condition", read_only=True, public=True)
def assert_condition(condition: bool, message: str = "断言失败"):
    if not condition:
        raise StopTaskException(message, success=False)
    logger.info(f"断言成功: {message}")
    return True


@register_action(name="set_variable", public=True)
# [MODIFIED] 注入新的ExecutionContext
def set_variable(context: ExecutionContext, name: str, value: any) -> bool:
    # [MODIFIED] 在新模型下，此action没有意义，因为无法修改上游上下文。
    # 我们将其行为改为打印一个警告，并建议用户使用具名输出。
    # 如果确实需要这个功能，需要engine支持将数据写回root_context，但这会破坏数据流的清晰性。
    logger.warning(f"Action 'set_variable' 在新的数据流模型中已弃用。")
    logger.warning(f"请在节点的 'outputs' 块中定义输出来传递数据。")
    logger.warning(f"尝试设置 '{name}' = {repr(value)} 的操作已被忽略。")
    # 如果要强制实现，可以这样做，但不推荐：
    # context.data['nodes'][f'__variable_{name}'] = {'output': value}
    return False


@register_action(name="string_format", read_only=True, public=True)
def string_format(template: str, *args, **kwargs) -> str:
    return template.format(*args, **kwargs)


@register_action(name="string_split", read_only=True, public=True)
def string_split(text: str, separator: str, max_split: int = -1) -> List[str]:
    return text.split(separator, max_split)


@register_action(name="string_join", read_only=True, public=True)
def string_join(items: List[Any], separator: str) -> str:
    return separator.join(str(item) for item in items)


@register_action(name="regex_search", read_only=True, public=True)
def regex_search(text: str, pattern: str) -> Optional[Dict[str, Any]]:
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
    allowed_chars = "0123456789.+-*/() "
    if all(char in allowed_chars for char in expression):
        try:
            # 使用ast.literal_eval更安全，但功能有限。eval功能强大但风险高。
            # 这里保持eval，但依赖于严格的字符白名单。
            return eval(expression)
        except Exception as e:
            logger.error(f"数学表达式计算失败 '{expression}': {e}")
            return None
    logger.error(f"表达式 '{expression}' 包含不允许的字符。")
    return None


# ==============================================================================
# IV. 状态与系统行为 (State & System Actions)
# ==============================================================================
# [MODIFIED] 移除所有旧的 persistent_context 和 state_store action，
# 因为它们已经被新的 state.set/get/delete action (在state_actions.py中) 替代。

@register_action(name="publish_event", public=True)
@requires_services(event_bus='event_bus')
# [MODIFIED] 移除旧context
async def publish_event(event_bus: EventBus, name: str, payload: Dict[str, Any] = None,
                        source: Optional[str] = None,
                        channel: str = "global") -> bool:
    try:
        # 在新模型下，无法轻易获取触发事件。
        # causation_chain和depth由EventBus在发布时自动处理。
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
    return app.get_window_size()


@register_action(name="focus_window", public=True)
@requires_services(app='app')
def focus_window(app: AppProviderService) -> bool:
    # 假设AppProviderService有screen属性
    return app.screen.focus()


@register_action(name="file_read", read_only=True, public=True)
def file_read(engine: ExecutionEngine, file_path: str) -> Optional[str]:
    try:
        # 路径安全由Orchestrator处理
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
# [MODIFIED] 所有复合action同样更新签名
@register_action(name="find_image_and_click", public=True)
@requires_services(vision='vision', app='app')
def find_image_and_click(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                         region: Optional[tuple[int, int, int, int]] = None, threshold: float = 0.8,
                         button: str = 'left', move_duration: float = 0.2) -> bool:
    match_result = find_image(app, vision, engine, template, region, threshold)
    if match_result.found:
        found_x, found_y = match_result.center_point
        logger.info(f"图像找到，位于窗口坐标 ({found_x}, {found_y})，置信度: {match_result.confidence:.2f}")

        # 先移动到目标点
        app.move_to(found_x, found_y, duration=move_duration)

        # [CORE FIX] 调用 click 时，必须传入 x 和 y 坐标
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
    ocr_result = find_text(app, ocr, engine, text_to_find, region, match_mode)
    if ocr_result.found:
        found_x, found_y = ocr_result.center_point
        logger.info(
            f"文本找到: '{ocr_result.text}'，位于窗口坐标 ({found_x}, {found_y})，置信度: {ocr_result.confidence:.2f}")

        # 先移动到目标点
        app.move_to(found_x, found_y, duration=move_duration)

        # [CORE FIX] 调用 click 时，必须传入 x 和 y 坐标
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
def run_task(engine, task_name: str, plan_name: str = None):
    # [MODIFIED] 这个action的实现完全在engine内部，这里只是一个注册占位符。
    # 它不需要修改，因为engine内部会处理上下文传递。
    pass


# [MODIFIED] run_python* actions 变得非常复杂，因为它们的设计与旧上下文紧密耦合。
# 在新模型下，它们应该被重新设计。
# 作为一个过渡，我们将移除它们，因为它们无法直接映射到新模型。
# 如果需要，可以后续作为新功能重新添加，并设计新的API（例如，脚本如何接收上游数据）。
# @register_action(name="run_python_script", ...)
# @register_action(name="run_python", ...)

# ... (其他复合action也类似地更新签名)
@register_action(name="scan_and_find_best_match", read_only=True, public=True)
@requires_services(vision='vision', app='app')
def scan_and_find_best_match(app: AppProviderService, vision: VisionService, engine: ExecutionEngine, template: str,
                             region: tuple[int, int, int, int], priority: str = 'top',
                             threshold: float = 0.8) -> MatchResult:
    logger.info(f"扫描区域寻找最佳匹配项 '{template}'，优先级: {priority}")
    multi_match_result = find_all_images(app, vision, engine, template, region, threshold)
    if not multi_match_result.matches:
        logger.warning("在扫描区域内未找到任何匹配项。")
        return MatchResult(found=False)
    matches = multi_match_result.matches

    priority_map = {
        'top': lambda m: m.center_point[1],
        'bottom': lambda m: -m.center_point[1],  # 用负数实现max
        'left': lambda m: m.center_point[0],
        'right': lambda m: -m.center_point[0]  # 用负数实现max
    }

    if priority not in priority_map:
        logger.error(f"无效的优先级规则: '{priority}'。")
        return MatchResult(found=False)

    # 使用min/max和key函数来找到最佳匹配
    best_match = min(matches, key=priority_map[priority]) if priority in ['top', 'left'] else max(matches,
                                                                                                  key=priority_map[
                                                                                                      priority])

    logger.info(f"找到最佳匹配项，位于 {best_match.center_point}")
    return best_match





# aura_official_packages/aura_base/actions/atomic_actions.py (最终合并版)

import ast
import time
from typing import Optional, Any, Dict
import re
import cv2

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
# I. 视觉与OCR原子行为
# ==============================================================================

@register_action(name="find_image", read_only=True, public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def find_image(
        app: AppProviderService,
        vision: VisionService,
        engine: ExecutionEngine,
        template: str,
        region: Optional[tuple[int, int, int, int]] = None,
        threshold: float = 0.8
) -> MatchResult:
    """在窗口内查找单个图像。"""
    is_inspect_mode = engine.context.get("__is_inspect_mode__", False)
    capture = app.capture(rect=region)
    if not capture.success:
        logger.error("行为 'find_image' 失败：无法截图。")
        return MatchResult(found=False)

    source_image_for_debug = capture.image.copy()
    plan_path = engine.orchestrator.current_plan_path
    full_template_path = plan_path / template

    match_result = vision.find_template(
        source_image=source_image_for_debug,
        template_image=str(full_template_path),
        threshold=threshold
    )

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
            match_result.debug_info.update({
                "source_image": source_image_for_debug,
                "template_image": template_image_for_debug,
                "params": {"template": template, "region": region, "threshold": threshold}
            })
        except Exception as e:
            logger.error(f"打包调试信息时出错: {e}")

    return match_result


@register_action(name="find_all_images", read_only=True, public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def find_all_images(
        app: AppProviderService,
        vision: VisionService,
        engine: ExecutionEngine,
        template: str,
        region: Optional[tuple[int, int, int, int]] = None,
        threshold: float = 0.8
) -> MultiMatchResult:
    """在窗口的指定区域内查找所有匹配的模板图像。"""
    capture = app.capture(rect=region)
    if not capture.success:
        logger.error("行为 'find_all_images' 失败：无法截图。")
        return MultiMatchResult()

    plan_path = engine.orchestrator.current_plan_path
    full_template_path = plan_path / template

    multi_match_result = vision.find_all_templates(
        source_image=capture.image,
        template_image=str(full_template_path),
        threshold=threshold
    )

    # 坐标转换
    region_x_offset = region[0] if region else 0
    region_y_offset = region[1] if region else 0
    for match in multi_match_result.matches:
        match.top_left = (match.top_left[0] + region_x_offset, match.top_left[1] + region_y_offset)
        match.center_point = (match.center_point[0] + region_x_offset, match.center_point[1] + region_y_offset)
        match.rect = (match.rect[0] + region_x_offset, match.rect[1] + region_y_offset, match.rect[2], match.rect[3])

    return multi_match_result


@register_action(name="find_image_in_scrolling_area", public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def find_image_in_scrolling_area(
        app: AppProviderService,
        vision: VisionService,
        engine: ExecutionEngine,
        template: str,
        scroll_area: tuple[int, int, int, int],
        # 新增参数: 'up' 或 'down'
        scroll_direction: str = 'down',
        max_scrolls: int = 5,
        scroll_amount: int = 200,  # 每次滚动的像素量
        threshold: float = 0.8,
        # 新增参数: 每次滚动后等待UI稳定的时间
        delay_after_scroll: float = 0.5
) -> MatchResult:
    """
    在一个可滚动的区域内查找图像。如果找不到，会模拟鼠标滚动并再次尝试，
    直到找到图像或达到最大滚动次数。

    :param scroll_area: 定义了可以滚动的区域 (x, y, width, height)。查找和光标定位都在此区域内。
    :param scroll_direction: 滚动方向, 'up' 或 'down'。
    :param max_scrolls: 最大滚动次数。
    :param scroll_amount: 每次滚动的量。对于 pyautogui 来说，正值向下，负值向上。
    :param delay_after_scroll: 每次滚动后等待UI加载的时间。
    :return: 如果找到，返回 MatchResult，否则返回 found=False 的结果。
    """
    logger.info(f"在可滚动区域 {scroll_area} 中查找 '{template}'，最多滚动 {max_scrolls} 次。")

    direction_map = {"up": 1, "down": -1}
    if scroll_direction.lower() not in direction_map:
        logger.error(f"无效的滚动方向: '{scroll_direction}'。")
        return MatchResult(found=False)

    scroll_val = scroll_amount * direction_map[scroll_direction.lower()]

    # 将鼠标光标移动到滚动区域中心，以确保滚动作用于此区域
    scroll_center_x = scroll_area[0] + scroll_area[2] // 2
    scroll_center_y = scroll_area[1] + scroll_area[3] // 2
    app.move_to(scroll_center_x, scroll_center_y, duration=0.1)

    for i in range(max_scrolls + 1):  # +1 是因为要先检查一次当前视图
        if i > 0:
            logger.info(f"第 {i} 次滚动...")
            # pyautogui的scroll是在当前鼠标位置滚动
            app.scroll(scroll_val)
            time.sleep(delay_after_scroll)

        # 在指定的滚动区域内查找
        match_result = find_image(app, vision, engine, template, region=scroll_area, threshold=threshold)
        if match_result.found:
            logger.info(f"在第 {i} 次滚动后找到图像！")
            return match_result

    logger.warning(f"在滚动 {max_scrolls} 次后，仍未找到图像 '{template}'。")
    return MatchResult(found=False)


@register_action(name="assert_image_exists", read_only=True, public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def assert_image_exists(
        app: AppProviderService,
        vision: VisionService,
        engine: ExecutionEngine,
        template: str,
        region: Optional[tuple[int, int, int, int]] = None,
        threshold: float = 0.8,
        message: Optional[str] = None
):
    """
    断言指定的图像必须存在。如果不存在，则抛出 StopTaskException 使任务失败。
    这是一个 'Guard Action'，用于保护后续流程的正确性。
    """
    match_result = find_image(app, vision, engine, template, region, threshold)
    if not match_result.found:
        error_message = message or f"断言失败：期望的图像 '{template}' 不存在。"
        logger.error(error_message)
        raise StopTaskException(error_message, success=False)

    logger.info(f"断言成功：图像 '{template}' 已确认存在。")
    return True  # 如果成功，返回True


@register_action(name="assert_image_not_exists", read_only=True, public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def assert_image_not_exists(
        app: AppProviderService,
        vision: VisionService,
        engine: ExecutionEngine,
        template: str,
        region: Optional[tuple[int, int, int, int]] = None,
        threshold: float = 0.8,
        message: Optional[str] = None
):
    """
    断言指定的图像必须不存在。如果存在，则抛出 StopTaskException 使任务失败。
    用于检查错误状态，如“断线重连”弹窗。
    """
    match_result = find_image(app, vision, engine, template, region, threshold)
    if match_result.found:
        error_message = message or f"断言失败：不期望的图像 '{template}' 却存在了。"
        logger.error(error_message)
        raise StopTaskException(error_message, success=False)

    logger.info(f"断言成功：图像 '{template}' 已确认不存在。")
    return True


@register_action(name="find_text", read_only=True, public=True)
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def find_text(
        app: AppProviderService,
        ocr: OcrService,
        engine: ExecutionEngine,
        text_to_find: str,
        region: Optional[tuple[int, int, int, int]] = None,
        match_mode: str = "exact"
) -> OcrResult:
    """在窗口的指定区域内查找单个文本实例。"""
    is_inspect_mode = engine.context.get("__is_inspect_mode__", False)
    capture = app.capture(rect=region)
    if not capture.success:
        logger.error("行为 'find_text' 失败：无法截图。")
        return OcrResult(found=False)

    source_image_for_debug = capture.image.copy()
    ocr_result = ocr.find_text(
        source_image=source_image_for_debug,
        text_to_find=text_to_find,
        match_mode=match_mode
    )

    if ocr_result.found:
        region_x_offset = region[0] if region else 0
        region_y_offset = region[1] if region else 0
        ocr_result.center_point = (
            ocr_result.center_point[0] + region_x_offset, ocr_result.center_point[1] + region_y_offset)
        ocr_result.rect = (
            ocr_result.rect[0] + region_x_offset, ocr_result.rect[1] + region_y_offset, ocr_result.rect[2],
            ocr_result.rect[3])

    if is_inspect_mode:
        ocr_result.debug_info.update({
            "source_image": source_image_for_debug,
            "params": {"text_to_find": text_to_find, "region": region, "match_mode": match_mode}
        })

    return ocr_result


@register_action(name="wait_for_text", public=True)
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def wait_for_text(
        app: AppProviderService,
        ocr: OcrService,
        engine: ExecutionEngine,
        text_to_find: str,
        timeout: float = 10.0,
        interval: float = 1.0,
        region: Optional[tuple[int, int, int, int]] = None,
        match_mode: str = "contains"
) -> OcrResult:
    """
    在指定时间内，周期性地查找某个文本，直到找到或超时。

    :return: 如果找到，返回 OcrResult，否则返回 found=False 的结果。
    """
    logger.info(f"开始等待文本 '{text_to_find}' 出现，最长等待 {timeout} 秒...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        # 复用强大的 find_text Action
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
def wait_for_text_to_disappear(
        app: AppProviderService,
        ocr: OcrService,
        engine: ExecutionEngine,
        text_to_monitor: str,
        timeout: float = 10.0,
        interval: float = 1.0,
        region: Optional[tuple[int, int, int, int]] = None,
        match_mode: str = "contains"
) -> bool:
    """
    在指定时间内，周期性地检查某个文本，直到它消失或超时。

    :return: 如果文本在超时前消失，返回 True，否则返回 False。
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





@register_action(name="get_text_in_region", read_only=True, public=True)
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def get_text_in_region(
        app: AppProviderService,
        ocr: OcrService,
        region: tuple[int, int, int, int],
        whitelist: Optional[str] = None,
        # 【修正】默认的连接符仍然是空格，但我们确保总会用它
        join_with: str = " "
) -> str:
    """
    识别指定区域内的所有文本，并将其处理成一个干净的字符串返回。

    :param region: 必须指定一个矩形区域 (x, y, width, height) 来进行识别。
    :param whitelist: 一个字符串，其中包含所有允许的字符。例如 "0123456789,"。
                      所有不在此列表中的字符将被移除。
    :param join_with: 如果识别出多行文本，使用什么字符将它们连接起来。
                      例如，使用 " " (空格) 或 "\\n" (换行符)。
    :return: 处理后的文本字符串。如果未识别到任何文本，则返回空字符串。
    """
    logger.info(f"正在读取区域 {region} 内的文本...")

    multi_ocr_result = recognize_all_text(app, ocr, region)

    # 【修正】如果找不到结果，直接返回空字符串，不再有分支
    if not multi_ocr_result.results:
        return ""

    detected_texts = [res.text for res in multi_ocr_result.results]

    if whitelist:
        pattern = f'[^{re.escape(whitelist)}]'
        # 在过滤前先移除换行符等，避免它们影响过滤
        cleaned_texts = [re.sub(r'[\n\r]', '', txt) for txt in detected_texts]
        filtered_texts = [re.sub(pattern, '', txt) for txt in cleaned_texts]
    else:
        filtered_texts = detected_texts

    # 【修正】移除了 if/else 分支，总是执行 join 操作并返回字符串
    result = join_with.join(filtered_texts)
    logger.info(f"识别并处理后的文本: '{result}'")
    return result


@register_action(name="assert_text_exists", read_only=True, public=True)
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def assert_text_exists(
        app: AppProviderService,
        ocr: OcrService,
        engine: ExecutionEngine,
        text_to_find: str,
        region: Optional[tuple[int, int, int, int]] = None,
        match_mode: str = "contains",
        message: Optional[str] = None
):
    """
    断言指定的文本必须存在。如果不存在，则任务失败。
    """
    ocr_result = find_text(app, ocr, engine, text_to_find, region, match_mode)
    if not ocr_result.found:
        error_message = message or f"断言失败：期望的文本 '{text_to_find}' 不存在。"
        logger.error(error_message)
        raise StopTaskException(error_message, success=False)

    logger.info(f"断言成功：文本 '{text_to_find}' 已确认存在。")
    return True


@register_action(name="assert_text_not_exists", read_only=True, public=True)
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def assert_text_not_exists(
        app: AppProviderService,
        ocr: OcrService,
        engine: ExecutionEngine,
        text_to_find: str,
        region: Optional[tuple[int, int, int, int]] = None,
        match_mode: str = "contains",
        message: Optional[str] = None
):
    """
    断言指定的文本必须不存在。如果存在，则任务失败。
    """
    ocr_result = find_text(app, ocr, engine, text_to_find, region, match_mode)
    if ocr_result.found:
        error_message = message or f"断言失败：不期望的文本 '{ocr_result.text}' 却存在了。"
        logger.error(error_message)
        raise StopTaskException(error_message, success=False)

    logger.info(f"断言成功：文本 '{text_to_find}' 已确认不存在。")
    return True


@register_action(name="recognize_all_text", read_only=True, public=True)
@requires_services(ocr='Aura-Project/base/ocr', app='Aura-Project/base/app')
def recognize_all_text(
        app: AppProviderService,
        ocr: OcrService,
        region: Optional[tuple[int, int, int, int]] = None
) -> MultiOcrResult:
    """识别窗口指定区域内的所有文本。"""
    capture = app.capture(rect=region)
    if not capture.success:
        logger.error("行为 'recognize_all_text' 失败：无法截图。")
        return MultiOcrResult()

    multi_ocr_result = ocr.recognize_all(source_image=capture.image)

    # 坐标转换
    region_x_offset = region[0] if region else 0
    region_y_offset = region[1] if region else 0
    for result in multi_ocr_result.results:
        result.center_point = (result.center_point[0] + region_x_offset, result.center_point[1] + region_y_offset)
        result.rect = (
            result.rect[0] + region_x_offset, result.rect[1] + region_y_offset, result.rect[2], result.rect[3])

    return multi_ocr_result


# ==============================================================================
# II. 键鼠控制原子行为
# ==============================================================================

@register_action(name="click", public=True)
@requires_services(app='Aura-Project/base/app')
def click(
        app: AppProviderService,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = 'left',
        clicks: int = 1,
        interval: float = 0.1
):
    """在窗口内的指定坐标进行鼠标点击。"""
    if x is not None and y is not None:
        app.click(x, y, button, clicks, interval)
    else:
        logger.info("在当前鼠标位置点击...")
        app.controller.click(button=button, clicks=clicks, interval=interval)
    return True


@register_action(name="move_to", public=True)
@requires_services(app='Aura-Project/base/app')
def move_to(app: AppProviderService, x: int, y: int, duration: float = 0.25):
    """平滑移动到窗口内的指定相对坐标。"""
    app.move_to(x, y, duration)
    return True


@register_action(name="drag", public=True)
@requires_services(app='Aura-Project/base/app')
def drag(app: AppProviderService, start_x: int, start_y: int, end_x: int, end_y: int, button: str = 'left',
         duration: float = 0.5):
    """在窗口内从一个相对坐标拖拽到另一个相对坐标。"""
    app.drag(start_x, start_y, end_x, end_y, button, duration)
    return True


@register_action(name="press_key", public=True)
@requires_services(app='Aura-Project/base/app')
def press_key(app: AppProviderService, key: str, presses: int = 1, interval: float = 0.1):
    """模拟一次按键。"""
    app.press_key(key, presses, interval)
    return True


@register_action(name="type_text", public=True)
@requires_services(app='Aura-Project/base/app')
def type_text(app: AppProviderService, text: str, interval: float = 0.01):
    """模拟真实的键盘输入来键入一段文本。"""
    logger.info(f"正在输入文本: '{text[:20]}...'")
    app.type_text(text, interval)
    return True


@register_action(name="scroll", public=True)
@requires_services(app='Aura-Project/base/app')
def scroll(app: AppProviderService, direction: str, amount: int):
    """在当前鼠标位置模拟鼠标滚轮滚动。"""
    direction_map = {"up": 1, "down": -1}
    if direction.lower() not in direction_map:
        logger.error(f"无效的滚动方向: '{direction}'。请使用 'up' 或 'down'。")
        return False
    # amount通常指滚动的“咔哒”数
    scroll_amount = amount * direction_map[direction.lower()]
    logger.info(f"向 {direction} 滚动 {amount} 单位。")
    app.scroll(scroll_amount)
    return True


@register_action(name="get_pixel_color", read_only=True, public=True)
@requires_services(app='Aura-Project/base/app')
def get_pixel_color(app: AppProviderService, x: int, y: int) -> tuple:
    """获取窗口内指定坐标的像素颜色 (R, G, B)。"""
    return app.get_pixel_color(x, y)


@register_action(name="mouse_move_relative", public=True)
@requires_services(app='Aura-Project/base/app')
def mouse_move_relative(app: AppProviderService, dx: int, dy: int, duration: float = 0.2):
    """从当前鼠标位置相对移动鼠标。"""
    logger.info(f"相对移动鼠标: dx={dx}, dy={dy}")
    app.move_relative(dx, dy, duration)
    return True


@register_action(name="key_down", public=True)
@requires_services(app='Aura-Project/base/app')
def key_down(app: AppProviderService, key: str):
    """按下并保持一个键盘按键。"""
    logger.info(f"按下按键: {key}")
    app.key_down(key)
    return True


@register_action(name="key_up", public=True)
@requires_services(app='Aura-Project/base/app')
def key_up(app: AppProviderService, key: str):
    """松开一个之前被按下的键盘按键。"""
    logger.info(f"松开按键: {key}")
    app.key_up(key)
    return True


# ==============================================================================
# III. 流程控制与数据处理行为
# ==============================================================================

@register_action(name="sleep", read_only=True, public=True)
def sleep(seconds: float):
    """暂停执行指定的秒数。"""
    logger.info(f"等待 {seconds} 秒...")
    time.sleep(seconds)
    return True


@register_action(name="log", read_only=True, public=True)
def log(message: str, level: str = "info"):
    """在框架的日志系统中记录一条消息。"""
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
    """停止当前任务的执行。"""
    raise StopTaskException(message, success)


@register_action(name="assert_condition", read_only=True, public=True)
def assert_condition(condition: bool, message: str = "断言失败"):
    """断言一个条件必须为真。如果为假，则立即停止任务并标记为失败。"""
    if not condition:
        raise StopTaskException(message, success=False)
    logger.info(f"断言成功: {message}")
    return True


@register_action(name="set_variable", public=True)
def set_variable(context: Context, name: str, value: any) -> bool:
    """
    在上下文中设置或覆盖一个变量。
    这个Action总是在成功时返回 True。
    """
    try:
        context.set(name, value)
        logger.info(f"设置上下文变量 '{name}' = {repr(value)}")
        # 【核心修复2】总是返回 True 来明确表示操作成功，无论设置的值是什么。
        return True
    except Exception as e:
        logger.error(f"设置变量 '{name}' 时失败: {e}", exc_info=True)
        return False


@register_action(name="string_format", read_only=True, public=True)
def string_format(template: str, *args, **kwargs) -> str:
    """使用 Python 的 .format() 方法格式化字符串。"""
    return template.format(*args, **kwargs)


@register_action("set_persistent_value", public=True)
def set_persistent_value(key: str, value, persistent_context: PersistentContext):
    """在长期上下文中设置一个值，但不会立即保存。"""
    if not isinstance(persistent_context, PersistentContext):
        logger.error("无法设置长期值，因为 'persistent_context' 未正确注入。")
        return False
    logger.info(f"在长期上下文中设置: '{key}' = '{value}' (尚未保存)")
    persistent_context.set(key, value)
    return True


@register_action("save_persistent_context", public=True)
def save_persistent_context(persistent_context: PersistentContext):
    """将当前所有的长期上下文更改保存到文件。"""
    if not isinstance(persistent_context, PersistentContext):
        logger.error("无法保存长期上下文，因为 'persistent_context' 未正确注入。")
        return False
    return persistent_context.save()


# ==============================================================================
# IV. 复合与高级行为
# ==============================================================================

@register_action(name="find_image_and_click", public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def find_image_and_click(
        app: AppProviderService,
        vision: VisionService,
        engine: ExecutionEngine,
        template: str,
        region: Optional[tuple[int, int, int, int]] = None,
        threshold: float = 0.8,
        button: str = 'left',
        move_duration: float = 0.2
) -> bool:
    """在窗口中查找指定图像，如果找到，则移动并点击其中心点。"""
    logger.info(f"正在查找图像 '{template}' 并准备点击...")
    match_result = find_image(app, vision, engine, template, region, threshold)  # 复用已有的Action
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
def find_text_and_click(
        app: AppProviderService,
        ocr: OcrService,
        engine: ExecutionEngine,
        text_to_find: str,
        region: Optional[tuple[int, int, int, int]] = None,
        match_mode: str = "contains",
        button: str = 'left',
        move_duration: float = 0.2
) -> bool:
    """在窗口中查找指定文本，如果找到，则移动并点击其中心点。"""
    logger.info(f"正在查找文本 '{text_to_find}' 并准备点击...")
    ocr_result = find_text(app, ocr, engine, text_to_find, region, match_mode)  # 复用已有的Action
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


@register_action(name="wait_for_image", public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def wait_for_image(
        app: AppProviderService,
        vision: VisionService,
        engine: ExecutionEngine,
        template: str,
        timeout: float = 10.0,
        interval: float = 1.0,
        region: Optional[tuple[int, int, int, int]] = None,
        threshold: float = 0.8
) -> MatchResult:
    """在指定时间内，周期性地查找某个图像，直到找到或超时。"""
    logger.info(f"开始等待图像 '{template}' 出现，最长等待 {timeout} 秒...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        match_result = find_image(app, vision, engine, template, region, threshold)  # 复用已有的Action
        if match_result.found:
            logger.info(f"成功等到图像 '{template}'！")
            return match_result
        logger.debug(f"尚未等到图像，将在 {interval} 秒后重试...")
        time.sleep(interval)
    logger.warning(f"超时 {timeout} 秒，未能等到图像 '{template}'。")
    return MatchResult(found=False)


@register_action(name="wait_for_any", public=True)
def wait_for_any(engine: ExecutionEngine, conditions: list, timeout: float = 10.0, interval: float = 1.0) -> dict:
    """等待多个条件中的任何一个满足。"""
    logger.info(f"等待 {len(conditions)} 个条件中的任意一个满足，超时 {timeout}s...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        for i, cond_step in enumerate(conditions):
            if engine._execute_single_action_step(cond_step):
                logger.info(f"条件 {i} 满足！")
                return {"found": True, "index": i}
        time.sleep(interval)
    logger.warning("等待超时，所有条件均未满足。")
    return {"found": False, "index": -1}


@register_action(name="wait_for_color_change", read_only=True, public=True)
@requires_services(app='Aura-Project/base/app')
def wait_for_color_change(
        app: AppProviderService,
        x: int,
        y: int,
        initial_color: tuple[int, int, int],
        timeout: float = 10.0,
        interval: float = 0.2,
        tolerance: int = 5
) -> bool:
    """
    等待指定坐标的像素颜色发生变化。
    它会持续检查一个点的颜色，直到它不再匹配初始颜色（在容差范围内），或超时。

    :param initial_color: 要监测的初始颜色 (R, G, B)。
    :param timeout: 最长等待时间（秒）。
    :param interval: 检查颜色的时间间隔（秒）。
    :param tolerance: 颜色容差，用于判断是否“等于”初始颜色。
    :return: 如果颜色在超时前发生变化，返回 True，否则返回 False。
    """
    logger.info(f"等待坐标 ({x},{y}) 的颜色从 {initial_color} 发生变化，最长等待 {timeout} 秒...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        current_color = app.get_pixel_color(x, y)

        # 使用之前 verify_color_at 的逻辑来判断颜色是否“等于”初始颜色
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
def scan_and_find_best_match(
        app: AppProviderService,
        vision: VisionService,
        engine: ExecutionEngine,
        template: str,
        region: tuple[int, int, int, int],
        # 新增参数: 'top', 'bottom', 'left', 'right'
        priority: str = 'top',
        threshold: float = 0.8
) -> MatchResult:
    """
    在指定区域扫描所有匹配项，并根据优先级返回“最佳”的一个。
    例如，在背包中找到最上面一排的物品，或在屏幕上找到最右边的敌人。

    :param priority: 优先级规则。
                     'top': Y坐标最小的 (最靠上)。
                     'bottom': Y坐标最大的 (最靠下)。
                     'left': X坐标最小的 (最靠左)。
                     'right': X坐标最大的 (最靠右)。
    :return: 最佳匹配的结果，如果一个都找不到则返回 found=False 的结果。
    """
    logger.info(f"扫描区域寻找最佳匹配项 '{template}'，优先级: {priority}")

    # 复用强大的 find_all_images
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


@register_action(name="drag_to_find", public=True)
@requires_services(vision='Aura-Project/base/vision', app='Aura-Project/base/app')
def drag_to_find(
        app: AppProviderService,
        vision: VisionService,
        engine: ExecutionEngine,
        drag_from_template: str,
        drag_to_template: str,
        # 新增参数: 允许指定拖拽源和目标的搜索区域
        from_region: Optional[tuple[int, int, int, int]] = None,
        to_region: Optional[tuple[int, int, int, int]] = None,
        threshold: float = 0.8,
        duration: float = 0.5
) -> bool:
    """
    找到一个对象，然后将其拖拽到另一个找到的对象上。

    :param drag_from_template: 要拖拽的起始物品的图像模板。
    :param drag_to_template: 要拖拽到的目标位置的图像模板。
    :return: 如果两个图像都找到并成功完成拖拽，返回 True。
    """
    logger.info(f"准备从 '{drag_from_template}' 拖拽到 '{drag_to_template}'...")

    # 查找起点
    source_match = find_image(app, vision, engine, drag_from_template, from_region, threshold)
    if not source_match.found:
        logger.error(f"拖拽失败：找不到起点图像 '{drag_from_template}'。")
        return False

    # 查找终点
    target_match = find_image(app, vision, engine, drag_to_template, to_region, threshold)
    if not target_match.found:
        logger.error(f"拖拽失败：找不到终点图像 '{drag_to_template}'。")
        return False

    start_x, start_y = source_match.center_point
    end_x, end_y = target_match.center_point

    logger.info(f"执行拖拽: 从 {start_x, start_y} 到 {end_x, end_y}")
    app.drag(start_x, start_y, end_x, end_y, duration=duration)

    return True


@register_action(name="verify_color_at", read_only=True, public=True)
@requires_services(app='Aura-Project/base/app')
def verify_color_at(
        app: AppProviderService,
        x: int,
        y: int,
        expected_color: tuple[int, int, int],
        # 新增参数: 允许颜色有一定的容差
        tolerance: int = 0
) -> bool:
    """
    验证窗口内指定坐标的像素颜色是否与预期颜色相符（在容差范围内）。

    :param expected_color: 预期的 (R, G, B) 颜色元组。
    :param tolerance: 颜色容差。每个颜色通道的实际值与预期值的差的绝对值之和
                     不能超过这个容差。
    :return: 如果颜色匹配，返回 True，否则返回 False。
    """
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


# --- 占位符与脚本执行行为 ---

@register_action(name="run_task", public=True)
def run_task(engine, task_name: str, plan_name: str = None):
    """调用并执行一个子任务 (由引擎实现)。"""
    pass


@register_action(name="press_sequence", public=True)
def press_sequence(engine: ExecutionEngine, sequence: list) -> bool:
    """按顺序执行一个由多个子行为组成的序列。"""
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
        if not  engine._execute_single_action_step(step_data):
            logger.error(f"序列在执行 '{action_name}' 时失败，序列中止。")
            return False
    logger.info("输入序列成功执行完毕。")
    return True


@register_action(name="run_python_script", public=True)
def run_python_script(
        engine: ExecutionEngine,
        context: Context,
        script_path: str,
        **kwargs
) -> Any:
    """执行一个外部Python脚本，并为其提供一个安全的 `aura` API 对象进行交互。"""
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
        logger.error(f"执行Python脚本 0'{script_path}' 时发生严重错误: {e}", exc_info=True)
        return False


@register_action(name="run_python", public=True)
@requires_services()  # 默认情况下，只注入 context
def run_python(context: Context, code: str) -> Any:
    """
    在受控环境中执行一小段 Python 代码字符串。

    这段代码可以访问和修改任务上下文。上下文变量被映射到一个名为 `ctx` 的字典中。
    代码的最后一条表达式的值或 `return` 语句的值将作为此 action 的返回值。

    :param context: 任务的执行上下文，由框架自动注入。
    :param code: 要执行的 Python 代码字符串。
    :return: 代码执行后的返回值。
    """
    if not isinstance(code, str):
        logger.error(f"'run_python' 的 'code' 参数必须是字符串，但收到了 {type(code)}。")
        return None

    logger.debug(f"准备执行 Python 代码:\n---\n{code}\n---")

    try:
        # 1. 创建一个安全的执行作用域
        # 我们将任务上下文的数据复制一份，作为可交互的 'ctx' 字典
        execution_scope = {
            'ctx': context._data
        }

        # 2. 解析代码，以确定是表达式还是语句块
        try:
            # 尝试将其作为单个表达式来解析和评估
            # ast.parse(code, mode='eval') 如果成功，说明它是一个可以被 eval 的表达式
            parsed_code = ast.parse(code.strip(), mode='eval')
            # 使用 compile 和 eval 来执行，这样可以获取表达式的值
            compiled_code = compile(parsed_code, '<string>', 'eval')
            return_value = eval(compiled_code, execution_scope)

        except SyntaxError:
            # 如果作为表达式失败，则将其作为语句块来处理
            # 这种情况下，我们需要找到 return 语句或最后一条表达式来获取返回值

            # 为了能捕获 return 的值，我们将代码包装在一个函数中
            wrapped_code = f"def __aura_py_executor__():\n"
            for line in code.strip().splitlines():
                wrapped_code += f"    {line}\n"

            # 如果代码块中没有 return，我们添加一个返回 None 的语句
            if 'return' not in wrapped_code:
                wrapped_code += "    return None\n"

            exec(wrapped_code, execution_scope)
            script_function = execution_scope['__aura_py_executor__']
            return_value = script_function()

        # 3. 将 'ctx' 字典中可能发生的更改同步回主上下文
        # 这允许 Python 代码修改任务状态
        for key, value in execution_scope['ctx'].items():
            # 只更新发生变化的或新增的键
            if key not in context._data or context._data[key] is not value:
                context.set(key, value)
                logger.debug(f"Python 代码更新了上下文变量: '{key}'")

        logger.debug(f"Python 代码执行完毕，返回: {repr(return_value)}")
        return return_value

    except Exception as e:
        logger.error(f"执行 Python 代码时发生错误: {e}", exc_info=True)
        # 在失败时返回 None，让上层可以判断
        return None


@register_action(name="log_test_step", read_only=True, public=True)
def log_test_step(message: str, context_vars: dict = None):
    """
    一个专门用于框架测试任务的日志记录行为。
    它会以统一的、易于追踪的格式打印消息和相关的上下文变量。
    """
    log_message = f"[FrameworkTest] >> {message}"

    if context_vars:
        var_str_list = []
        for key, value in context_vars.items():
            var_str_list.append(f"{key}={repr(value)}")
        log_message += f" ({', '.join(var_str_list)})"

    logger.info(log_message)
    return True


@register_action(name="set_state", public=True)
@requires_services(state_store='state_store')
def set_state(
        state_store: StateStore,
        key: str,
        value: Any,
        ttl: Optional[float] = None
) -> bool:
    """
    在全局状态存储中设置一个驻留信号（状态）。

    :param state_store: (由框架注入) StateStore服务实例。
    :param key: 状态的唯一标识符。
    :param value: 要存储的状态值。
    :param ttl: (可选) 状态的存活时间（秒）。如果未提供，则状态永不过期。
    :return: 操作是否成功。
    """
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
def get_state(
        state_store: StateStore,
        context: Context,
        key: str,
        default: Any = None,
        output_to: Optional[str] = None
) -> Any:
    """
    从全局状态存储中获取一个驻留信号（状态）的值。

    这个Action有两种用法：
    1. 如果提供了 `output_to`，它会将结果存入上下文并返回True/False表示是否找到。
    2. 如果没有提供 `output_to`，它会直接返回值本身。

    :param state_store: (由框架注入) StateStore服务实例。
    :param context: (由框架注入) 当前任务的上下文。
    :param key: 要获取的状态的键。
    :param default: (可选) 如果状态不存在，返回的默认值。
    :param output_to: (可选) 如果提供，则将结果存入此上下文变量名下。
    :return: 根据用法返回状态值或布尔值。
    """
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
def delete_state(
        state_store: StateStore,
        key: str
) -> bool:
    """
    从全局状态存储中删除一个驻留信号（状态）。

    :param state_store: (由框架注入) StateStore服务实例。
    :param key: 要删除的状态的键。
    :return: 如果成功删除或键原本就不存在，返回True。
    """
    try:
        deleted = state_store.delete(key)
        if deleted:
            logger.info(f"删除了驻留信号 '{key}'")
        else:
            logger.info(f"尝试删除驻留信号 '{key}'，但它不存在。")
        return True  # 即使键不存在，从逻辑上讲，也达到了“它不存在”的目标
    except Exception as e:
        logger.error(f"删除驻留信号 '{key}' 时失败: {e}", exc_info=True)
        return False


@register_action(name="publish_event", public=True)
@requires_services(event_bus='event_bus')
def publish_event(
        event_bus: EventBus,
        context: Context,
        name: str,
        payload: Dict[str, Any] = None,
        source: Optional[str] = None
) -> bool:
    """
    向事件总线发布一个瞬时信号（事件）。

    :param event_bus: (由框架注入) EventBus服务实例。
    :param context: (由框架注入) 当前任务的上下文，用于追踪调用链。
    :param name: 事件的名称 (例如 'orders:created', 'player:died')。
    :param payload: (可选) 附加到事件的数据字典。
    :param source: (可选) 事件的来源。如果未提供，会尝试从上下文中推断。
    :return: 操作是否成功。
    """
    try:
        # 准备调用链和深度
        causation_chain = []
        depth = 0
        triggering_event = context.get_triggering_event()  # 我们即将添加这个方法
        if triggering_event:
            causation_chain.extend(triggering_event.causation_chain)
            depth = triggering_event.depth + 1

        # 确定事件来源
        event_source = source or context.get('__task_name__', 'unknown_task')

        # 创建并发布事件
        new_event = Event(
            name=name,
            payload=payload or {},
            source=event_source,
            causation_chain=causation_chain,
            depth=depth
        )
        event_bus.publish(new_event)

        return True
    except Exception as e:
        logger.error(f"发布事件 '{name}' 时失败: {e}", exc_info=True)
        return False

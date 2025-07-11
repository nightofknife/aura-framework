# aura_official_packages/aura_base/actions/atomic_actions.py (最终合并版)

import time
from typing import Optional, Any
import cv2

# --- 核心导入 ---
from packages.aura_core.api import register_action, requires_services
from packages.aura_core.engine import ExecutionEngine, Context
from packages.aura_core.exceptions import StopTaskException
from packages.aura_core.persistent_context import PersistentContext
from packages.aura_shared_utils.utils.logger import logger

# --- 服务与数据模型导入 (来自本包) ---
from ..services.app_provider_service import AppProviderService
from ..services.vision_service import VisionService, MatchResult, MultiMatchResult
from ..services.ocr_service import OcrService, OcrResult, MultiOcrResult


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
            if engine._execute_single_step_logic(cond_step):
                logger.info(f"条件 {i} 满足！")
                return {"found": True, "index": i}
        time.sleep(interval)
    logger.warning("等待超时，所有条件均未满足。")
    return {"found": False, "index": -1}


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
        if not engine._execute_single_step_logic(step_data):
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
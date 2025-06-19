# src/notifier_actions/atomic_actions.py

import time
from typing import Optional, Any
import cv2

# 导入我们需要的服务和交互器类，主要用于类型提示
from packages.aura_core.exceptions import StopTaskException
from packages.aura_system_services.services.app_provider_service import AppProviderService
from packages.aura_system_services.services.vision_service import VisionService, MatchResult, MultiMatchResult
from packages.aura_system_services.services.ocr_service import OcrService, OcrResult, MultiOcrResult
from packages.aura_core.engine import ExecutionEngine, Context  # 假设异常定义在engine.py中
from packages.aura_shared_utils.utils.logger import logger
from packages.aura_system_actions.actions.decorators import register_action, requires_services
from packages.aura_core.persistent_context import PersistentContext


# --- 视觉相关原子行为 ---

@register_action(name="find_image", read_only=True)
@requires_services(vision='core/vision', app='core/app')
def find_image(
        app: AppProviderService,
        vision: VisionService,
        engine: ExecutionEngine,  # 【新增】注入引擎
        template: str,
        region: Optional[tuple[int, int, int, int]] = None,
        threshold: float = 0.8
) -> MatchResult:
    """
    在窗口内查找单个图像。

    这是框架中最核心的视觉行为之一。它会截取当前窗口的屏幕，
    并在截图上寻找与提供的模板图像最匹配的区域。

    :param template: 模板图片的相对路径 (相对于方案根目录)。
    :param region: (可选) 一个(x, y, w, h)元组，限定只在此区域内搜索。
    :param threshold: (可选) 图像匹配的置信度阈值，介于0.0到1.0之间。
    :return: 一个MatchResult对象，包含查找结果。
    """
    # 检查是否处于调试模式
    is_inspect_mode = engine.context.get("__is_inspect_mode__", False)

    capture = app.capture(rect=region)
    if not capture.success:
        logger.error("行为 'find_image' 失败：无法截图。")
        return MatchResult(found=False)

    # 【修改】直接将原始截图存入一个变量
    source_image_for_debug = capture.image.copy()

    # 加载模板图像的完整路径，以便读取它用于调试
    # 假设模板路径是相对于方案根目录的
    plan_path = engine.orchestrator.current_plan_path
    full_template_path = plan_path / template

    # 调用 vision service
    match_result = vision.find_template(
        source_image=source_image_for_debug,
        template_image=str(full_template_path),  # 确保传递路径字符串
        threshold=threshold
    )

    # --- 坐标转换逻辑 (保持不变) ---
    if match_result.found:
        region_x_offset = region[0] if region else 0
        region_y_offset = region[1] if region else 0
        match_result.top_left = (match_result.top_left[0] + region_x_offset, match_result.top_left[1] + region_y_offset)
        match_result.center_point = (
            match_result.center_point[0] + region_x_offset, match_result.center_point[1] + region_y_offset)
        match_result.rect = (
            match_result.rect[0] + region_x_offset, match_result.rect[1] + region_y_offset, match_result.rect[2],
            match_result.rect[3])

    # --- 【新增】打包调试信息 ---
    if is_inspect_mode:
        try:
            template_image_for_debug = cv2.imread(str(full_template_path))
            # 将所有调试信息打包到 MatchResult 的 debug_info 字段中
            match_result.debug_info.update({
                "source_image": source_image_for_debug,
                "template_image": template_image_for_debug,
                "params": {"template": template, "region": region, "threshold": threshold}
            })
        except Exception as e:
            logger.error(f"打包调试信息时出错: {e}")
            # 即使打包失败，也要继续返回结果

    return match_result


@register_action(name="find_all_images", read_only=True)
@requires_services(vision ='core/vision', app='core/app')
def find_all_images(
        app: AppProviderService,
        vision: VisionService,
        template: str,
        region: Optional[tuple[int, int, int, int]] = None,
        threshold: float = 0.8
) -> MultiMatchResult:
    """
    在窗口的指定区域内查找所有匹配的模板图像。
    """
    # 实现逻辑与 find_image 类似，但调用 vision.find_all_templates
    # ... (此处省略，实现方式与find_image类似，只是调用不同的vision方法并处理多结果的坐标转换)
    pass  # 留作练习或后续实现


# --- OCR相关原子行为 ---

@register_action(name="find_text", read_only=True)
@requires_services(ocr='ocr', app='app_provider')
def find_text(
        app: AppProviderService,
        ocr: OcrService,
        engine: ExecutionEngine,  # 【新增】注入引擎
        text_to_find: str,
        region: Optional[tuple[int, int, int, int]] = None,
        match_mode: str = "exact"
) -> OcrResult:
    """
      【修改后】在窗口的指定区域内查找单个文本实例。
      在调试模式下，会返回一个包含额外可视化信息的调试包。
      """
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

    # --- 坐标转换逻辑 (保持不变) ---
    if ocr_result.found:
        region_x_offset = region[0] if region else 0
        region_y_offset = region[1] if region else 0
        ocr_result.center_point = (
            ocr_result.center_point[0] + region_x_offset, ocr_result.center_point[1] + region_y_offset)
        ocr_result.rect = (
            ocr_result.rect[0] + region_x_offset, ocr_result.rect[1] + region_y_offset, ocr_result.rect[2],
            ocr_result.rect[3])

    # --- 【新增】打包调试信息 ---
    if is_inspect_mode:
        # 即使失败，也要把源图和参数打包回去
        ocr_result.debug_info.update({
            "source_image": source_image_for_debug,
            "params": {"text_to_find": text_to_find, "region": region, "match_mode": match_mode}
        })
        # 注意：OCR没有“模板图”，所以我们不打包 template_image

    return ocr_result


@register_action(name="recognize_all_text", read_only=True)
@requires_services(ocr='ocr', app='app_provider')
def recognize_all_text(
        app: AppProviderService,
        ocr: OcrService,
        region: Optional[tuple[int, int, int, int]] = None
) -> MultiOcrResult:
    """
    识别窗口指定区域内的所有文本。
    """
    # ... (实现方式与find_text类似，但调用ocr.recognize_all)
    pass


# --- 键鼠控制原子行为 ---

@register_action(name="click")
@requires_services( app='app_provider')
def click(
        app: AppProviderService,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = 'left',
        clicks: int = 1,
        interval: float = 0.1
):
    """
    在窗口内的指定坐标进行鼠标点击。

    :param x: 点击位置的X坐标。如果和y都未提供，则在当前鼠标位置点击。
    :param y: 点击位置的Y坐标。
    :param button: 'left', 'right', 或 'middle'。
    :param clicks: 点击次数。
    :param interval: 多次点击之间的间隔秒数。
    """
    if x is not None and y is not None:
        app.click(x, y, button, clicks, interval)
    else:
        # 如果坐标未提供，需要调用controller的无坐标点击
        # 这需要对Controller类稍作修改，或在这里直接调用win32api
        # 为保持封装，我们假设AppWindow未来会有一个app.click_current_pos()方法
        print("在当前位置点击...")
        app.controller.click(button=button, clicks=clicks, interval=interval)
    return True


@register_action(name="move_to")
@requires_services(app='app_provider')
def move_to(app: AppProviderService, x: int, y: int, duration: float = 0.25):
    """平滑移动到窗口内的指定相对坐标。"""
    app.move_to(x, y, duration)
    return True


@register_action(name="drag")
@requires_services(app='app_provider')
def drag(app: AppProviderService, start_x: int, start_y: int, end_x: int, end_y: int, button: str = 'left',
         duration: float = 0.5):
    """在窗口内从一个相对坐标拖拽到另一个相对坐标。"""
    app.drag(start_x, start_y, end_x, end_y, button, duration)
    return True


@register_action(name="press_key")
@requires_services(app='app_provider')
def press_key(app: AppProviderService, key: str, presses: int = 1, interval: float = 0.1):
    """模拟一次按键。"""
    app.press_key(key, presses, interval)
    return True


# --- 流程控制原子行为 ---

@register_action(name="sleep", read_only=True)
def sleep(seconds: float):
    """
    暂停执行指定的秒数。

    这是一个阻塞操作，会暂停当前任务线程。

    :param seconds: 需要等待的秒数，可以是浮点数。
    """
    print(f"等待 {seconds} 秒...")
    time.sleep(seconds)
    return True


# src/notifier_actions/atomic_actions.py


@register_action(name="press_sequence")
def press_sequence(engine: 'ExecutionEngine', sequence: list) -> bool:
    """
    按顺序执行一个由多个子行为组成的序列。
    这个行为本身是一个迷你编排器，可以调用任何已注册的行为。

    序列是一个列表，每一项都是一个标准的步骤字典。
    例如:
    - {action: 'press', params: {key: 'a'}}
    - {action: 'sleep', params: {seconds: 0.5}}
    - {action: 'my_custom_action', params: {foo: 'bar'}}

    :param engine: ExecutionEngine 实例 (由依赖注入提供)。
    :param sequence: 描述操作序列的列表，每个元素都是一个步骤字典。
    :return: 如果所有操作都成功执行，返回 True，否则返回 False。
    """
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

        # 【核心】调用引擎的内部动作分发器来执行子步骤
        success = engine._execute_single_step_logic(step_data)

        if not success:
            logger.error(f"序列在执行 '{action_name}' 时失败，序列中止。")
            return False

    logger.info("输入序列成功执行完毕。")
    return True


@register_action(name="stop_task", read_only=True)
def stop_task(message: str = "任务已停止", success: bool = True):
    """
    停止当前任务的执行。
    这个行为通过抛出特定的异常来工作，该异常会被执行引擎捕获。
    """
    raise StopTaskException(message, success)


@register_action(name="run_task")
def run_task(engine, task_name: str, plan_name: str = None):
    """
    调用并执行一个子任务。
    这个行为是一个占位符，它的实际逻辑在ExecutionEngine中实现，
    以避免循环依赖和简化逻辑。
    """
    # 这个函数体是空的，因为它的逻辑完全由引擎接管。
    # 它的存在只是为了让引擎能识别出这个特殊的action。
    pass


@register_action("set_persistent_value")
def set_persistent_value(key: str, value, persistent_context: PersistentContext):
    """
    在长期上下文中设置一个值，但不会立即保存。
    用于批量修改，最后用 save_persistent_context 一次性保存。
    """
    if not isinstance(persistent_context, PersistentContext):
        logger.error("无法设置长期值，因为 'persistent_context' 未正确注入。")
        return False

    logger.info(f"在长期上下文中设置: '{key}' = '{value}' (尚未保存)")
    persistent_context.set(key, value)
    return True


# 【修改】使用 @register_action("action_name_in_yaml") 的正确语法
@register_action("save_persistent_context")
def save_persistent_context(persistent_context: PersistentContext):
    """
    将当前所有的长期上下文更改保存到文件。
    这是一个关键的“检查点”操作。
    """
    if not isinstance(persistent_context, PersistentContext):
        logger.error("无法保存长期上下文，因为 'persistent_context' 未正确注入。")
        return False

    return persistent_context.save()


@register_action(name="log", read_only=True)
def log(message: str, level: str = "info"):
    """
    【修改后】在框架的日志系统中记录一条消息。
    增加了对 level 参数的类型健壮性处理。
    """
    # 【关键修改】在调用 .lower() 之前，先确保它是一个字符串。
    # 这使得该函数能够优雅地处理来自上下文的非字符串输入。
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


@register_action(name="type_text")
@requires_services(app='app_provider')
def type_text(app: AppProviderService, text: str, interval: float = 0.01):
    """模拟真实的键盘输入来键入一段文本。"""
    logger.info(f"正在输入文本: '{text[:20]}...'")
    app.type_text(text, interval)  # 假设AppWindow有这个方法
    return True


@register_action(name="scroll")
@requires_services(app='app_provider')
def scroll(app: AppProviderService, direction: str, amount: int):
    """在当前鼠标位置模拟鼠标滚轮滚动。"""
    direction_map = {"up": 1, "down": -1}
    if direction.lower() not in direction_map:
        logger.error(f"无效的滚动方向: '{direction}'。请使用 'up' 或 'down'。")
        return False

    # amount通常指滚动的“咔哒”数
    scroll_amount = amount * direction_map[direction.lower()]
    logger.info(f"向 {direction} 滚动 {amount} 单位。")
    app.scroll(scroll_amount)  # 假设AppWindow有这个方法
    return True


@register_action(name="assert_condition", read_only=True)
def assert_condition(condition: bool, message: str = "断言失败"):
    """
    断言一个条件必须为真。如果为假，则立即停止任务并标记为失败。
    """
    if not condition:
        raise StopTaskException(message, success=False)
    logger.info(f"断言成功: {message}")
    return True


# 这个更适合放在 composite_actions.py
@register_action(name="wait_for_any")
def wait_for_any(engine: ExecutionEngine, conditions: list, timeout: float = 10.0, interval: float = 1.0) -> dict:
    """等待多个条件中的任何一个满足。"""
    logger.info(f"等待 {len(conditions)} 个条件中的任意一个满足，超时 {timeout}s...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        for i, cond_step in enumerate(conditions):
            # 使用引擎来安全地执行每个条件检查
            if engine._execute_single_step_logic(cond_step):
                logger.info(f"条件 {i} 满足！")
                return {"found": True, "index": i}
        time.sleep(interval)

    logger.warning("等待超时，所有条件均未满足。")
    return {"found": False, "index": -1}


@register_action(name="get_pixel_color", read_only=True)
@requires_services(app='app_provider')
def get_pixel_color(app: AppProviderService, x: int, y: int) -> tuple:
    """获取窗口内指定坐标的像素颜色 (R, G, B)。"""
    return app.get_pixel_color(x, y)  # 假设AppWindow有这个方法


@register_action(name="string_format", read_only=True)
def string_format(template: str, *args, **kwargs) -> str:
    """使用 Python 的 .format() 方法格式化字符串。"""
    return template.format(*args, **kwargs)


@register_action(name="run_python_script")
def run_python_script(
        engine: ExecutionEngine,
        context: Context,
        script_path: str,
        **kwargs
) -> Any:
    """
    执行一个外部Python脚本，并为其提供一个安全的 `aura` API 对象进行交互。

    :param engine: ExecutionEngine 实例 (由注入器提供)。
    :param context: Context 实例 (由注入器提供)。
    :param script_path: 相对于方案根目录的脚本路径 (例如 'scripts/my_logic.py')。
    :param kwargs: 所有其他在YAML中定义的参数，都将通过 `aura.params` 传递给脚本。
    :return: Python脚本中 `return` 语句返回的值。
    """
    orchestrator = engine.orchestrator
    if not orchestrator:
        logger.error("'run_python_script' 无法执行，因为未关联到编排器。")
        return False

    # 1. 构建脚本的绝对路径
    full_script_path = orchestrator.current_plan_path / script_path
    if not full_script_path.is_file():
        logger.error(f"找不到Python脚本: {full_script_path}")
        return False

    logger.info(f"--- 开始执行Python脚本: {script_path} ---")

    try:
        # 2. 读取脚本内容
        with open(full_script_path, 'r', encoding='utf-8') as f:
            script_code = f.read()

        # 3. 创建 AuraApi 实例
        AuraApi_class = context.get('AuraApi')
        # `kwargs` 包含了所有从YAML传入的自定义参数
        aura_instance = AuraApi_class(orchestrator, engine, kwargs)

        # 4. 准备脚本的执行环境 (globals)
        # 我们只注入 'aura' 这一个对象，保持环境干净
        script_globals = {
            'aura': aura_instance
        }

        # 5. 为了捕获 return 值，我们需要将脚本包装成一个函数
        # 这是一种比直接 exec 更健壮、更安全的方法
        wrapped_code = f"def __aura_script_executor__():\n"
        wrapped_code += "".join(f"    {line}\n" for line in script_code.splitlines())

        exec(wrapped_code, script_globals)

        # 6. 执行被包装的函数并获取返回值
        script_function = script_globals['__aura_script_executor__']
        return_value = script_function()

        logger.info(f"--- Python脚本 '{script_path}' 执行完毕 ---")

        # 7. 返回脚本的返回值
        return return_value

    except Exception as e:
        logger.error(f"执行Python脚本 '{script_path}' 时发生严重错误: {e}", exc_info=True)
        return False


@register_action(name="mouse_move_relative")
@requires_services(app='app_provider')
def mouse_move_relative(app: AppProviderService, dx: int, dy: int, duration: float = 0.2):
    """
    从当前鼠标位置相对移动鼠标。
    这对于实现“拖拽感”或不依赖绝对坐标的移动非常有用。

    :param dx: X轴方向的移动距离。负数向左，正数向右。
    :param dy: Y轴方向的移动距离。负数向上，正数向下。
    :param duration: 移动过程的持续秒数，以实现平滑移动。
    """
    logger.info(f"相对移动鼠标: dx={dx}, dy={dy}")
    # 假设 AppProviderService 封装了底层的控制器，并提供了 move_relative 方法
    app.move_relative(dx, dy, duration)
    return True


# --- 【新增】按键按下与松开 ---
@register_action(name="key_down")
@requires_services(app='app_provider')
def key_down(app: AppProviderService, key: str):
    """
    按下并保持一个键盘按键。
    此行为需要与 key_up 配对使用，以模拟按住不放的操作。

    :param key: 要按下的键的名称 (例如 't', 'shift', 'ctrl', 'enter')。
    """
    logger.info(f"按下按键: {key}")
    # 假设 AppProviderService 封装了底层的控制器，并提供了 key_down 方法
    app.key_down(key)
    return True


@register_action(name="key_up")
@requires_services(app='app_provider')
def key_up(app: AppProviderService, key: str):
    """
    松开一个之前被按下的键盘按键。
    通常与 key_down 配对使用。

    :param key: 要松开的键的名称。
    """
    logger.info(f"松开按键: {key}")
    # 假设 AppProviderService 封装了底层的控制器，并提供了 key_up 方法
    app.key_up(key)
    return True

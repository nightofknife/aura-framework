# 文件: `plans/aura_base/actions/atomic_actions.py`

## 1. 核心目的

该文件是 `aura_base` 方案包的核心，定义了 Aura 框架中最基础、最常用的一系列**原子动作（Atomic Actions）**。这些动作构成了用户在 YAML 任务文件中可以直接使用的基本指令集。

它的核心职责是将底层服务（如 `VisionService`, `OcrService`, `AppProviderService`）提供的能力，封装成符合 Aura Action 规范的、可被 `ExecutionEngine` 调度执行的函数。每个 Action 都被设计为执行一个单一、明确的操作，例如“查找一张图片”、“点击一个坐标”或“打印一条日志”。

## 2. 关键组件与功能

该文件不包含类，而是由一系列被 `@register_action` 和 `@requires_services` 装饰器修饰的函数组成。这些函数按功能可以分为几大类：

*   **视觉与 OCR 行为 (Vision & OCR Actions)**
    *   **Find Actions**: 如 `find_image`, `find_text`。这些动作负责在屏幕的指定区域内查找视觉或文本目标，并返回一个包含详细信息（如坐标、置信度）的结果对象（`MatchResult` 或 `OcrResult`）。它们是**只读**操作。
    *   **Check Actions**: 如 `check_text_exists`, `check_image_exists`。它们内部调用对应的 `find_*` 动作，但只返回一个简单的布尔值（`True` 或 `False`），方便在 YAML 的 `when` 条件判断中使用。
    *   **Assert Actions**: 如 `assert_image_exists`, `assert_text_not_exists`。这些动作用于**断言**。如果条件不满足（例如，期望存在的图片不存在），它们会主动抛出 `StopTaskException` 异常来**中断**当前任务的执行。
    *   **Wait Actions**: 如 `wait_for_text`, `wait_for_image_to_disappear`。它们封装了轮询逻辑，在一个指定的时间内反复检查某个条件，直到条件满足或超时。

*   **键鼠控制行为 (I/O Control Actions)**
    *   如 `click`, `move_to`, `drag`, `press_key`, `type_text`。这些动作是对 `AppProviderService` 提供的高级交互能力的直接封装，允许用户在 YAML 中以声明的方式执行键鼠操作。

*   **流程控制与数据处理行为 (Flow & Data Actions)**
    *   `sleep`: 等待指定的秒数。
    *   `log`: 在框架的日志系统中打印一条消息。
    *   `stop_task`: 主动停止当前任务，并可以指定任务最终状态为成功或失败。
    *   **数据处理**: 如 `string_format`, `regex_search`, `math_compute` 等，提供了一些基本的数据处理能力，使得可以在 YAML 层面进行简单的数据操作。

*   **状态与系统行为 (State & System Actions)**
    *   `publish_event`: 向 Aura 的事件总线发布一个自定义事件。
    *   `file_read` / `file_write`: 在当前 Plan 的目录下安全地读写文件。

## 3. 核心逻辑解析

这个文件的核心逻辑在于**依赖注入**和**关注点分离**的设计模式，这通过两个关键的装饰器来实现：

### 1. `@requires_services(...)`

这个装饰器负责处理 Action 对底层服务的依赖。当 `ExecutionEngine` 准备执行一个 Action 时，它会检查这个装饰器。

例如，对于 `find_image` 的定义：
```python
@requires_services(vision='vision', app='app')
def find_image(app: AppProviderService, vision: VisionService, ...):
    ...
```

*   `vision='vision'`: 告诉引擎，这个 Action 需要一个别名为 `'vision'` 的服务。引擎会从服务注册表中查找这个服务，并将其作为 `vision` 关键字参数注入到函数调用中。
*   `app: AppProviderService`: Python 的类型提示 `AppProviderService` 提供了代码补全和静态分析的便利，使得开发体验更佳。

这种机制使得 Action 函数本身**无需关心如何获取服务实例**。它只需要声明自己的依赖，并在参数中接收它们即可。这使得 Action 变得高度可测试（可以轻松地注入模拟的服务）和可维护。

### 2. `@register_action(...)`

这个装饰器负责将一个普通的 Python 函数注册到 Aura 的全局 Action 注册表中，使其能够被 YAML 任务文件通过其名称调用。

例如：
```python
@register_action(name="find_image", read_only=True, public=True)
```

*   `name="find_image"`: 这是 Action 在 YAML 文件中被引用的名称。结合 Plan 的名称，它的完整 ID 就是 `aura_base.find_image`。
*   `read_only=True`: 这是一个元数据标志，向系统表明这个 Action 不会改变外部系统的状态。这对于未来的优化或调试功能可能很有用。
*   `public=True`: 标记这个 Action 是一个公开的、稳定的 API，应该被用户使用。

### 坐标系转换逻辑

另一个重要的逻辑点是在视觉相关的 Action（如 `find_image`, `find_text`）中处理**坐标系转换**。

*   底层服务（`VisionService`, `OcrService`）总是在给定的图像切片（`region`）内进行查找，并返回相对于**该切片左上角**的坐标。
*   然而，Action 的调用者期望得到的是相对于**整个窗口**的坐标。
*   因此，在这些 Action 的末尾，都有类似这样的逻辑：
    ```python
    region_x_offset = region[0] if region else 0
    region_y_offset = region[1] if region else 0
    match_result.center_point = (match_result.center_point[0] + region_x_offset, ...)
    ```
    这段代码将服务返回的相对坐标，加上用户传入的 `region` 的偏移量，从而计算出最终在整个窗口坐标系下的正确位置。这个转换对于确保复合操作（如查找后点击）的准确性至关重要。

总而言之，`atomic_actions.py` 文件是连接用户意图（YAML）和系统能力（Services）的核心桥梁，它通过清晰的封装和依赖注入，构建了一套强大而易于使用的自动化指令集。
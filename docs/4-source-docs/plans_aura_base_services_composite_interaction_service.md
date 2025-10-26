# 文件: `plans/aura_base/services/composite_interaction_service.py`

## 1. 核心目的

该文件定义了 `CompositeInteractionService`，这是一个更高层次的交互服务。它的核心职责是将多个**原子服务**（如 `AppProviderService`, `OcrService`, `VisionService`）的功能组合起来，形成**可复用的、面向业务场景的复合行为**。

这个服务的目标是封装那些在自动化脚本中频繁出现的、由多个步骤组成的通用交互模式（例如“查找文本并点击”、“等待某个图像出现”），从而极大地简化上层 Actions 的逻辑，提高代码的可读性和复用性。

## 2. 关键组件与功能

*   **`CompositeInteractionService`**:
    *   **`__init__(app, screen, ocr, vision)`**: 初始化服务。通过**依赖注入**接收所有它需要协调的底层服务实例。这是一个典型的**组合模式**应用，`CompositeInteractionService` 本身不实现任何原子操作，而是作为总指挥来调用其他服务。
    *   **`click_text_async(text, ...)`**: 实现了“查找并点击文本”的复合行为。它在一个超时循环中，不断地调用 `app.capture_async` 进行截图，然后调用 `ocr._find_text_async` 在截图中查找目标文本。一旦找到，它会计算出文本的中心点坐标，并调用 `app.click_async` 来执行点击。
    *   **`click_image_async(image_path, ...)`**: 实现了“查找并点击图像”的复合行为。其逻辑与 `click_text_async` 类似，但调用的是 `vision.find_template_async` 来进行图像匹配。
    *   **`wait_for_text_async(text, ...)`**: 实现了“等待直到某个文本出现”的复合行为。它在一个超时循环中，反复调用 `check_text_exists_async`（一个封装了截图和OCR查找的内部方法），直到文本被找到或超时。
    *   **`wait_for_text_to_disappear_async(text, ...)`**: 与 `wait_for_text_async` 逻辑相反，它等待直到指定的文本从屏幕上消失。
    *   **`wait_for_image_async(...)` / `wait_for_image_to_disappear_async(...)`**: 提供了与等待文本类似的功能，但用于图像目标。
    *   **同步接口 (如 `click_text`, `wait_for_image`)**: 与其他服务一样，它也为每一个核心的异步方法提供了一个**同名的同步封装**。这些同步方法通过 `_submit_to_loop_and_wait` 桥接器，使得上层的 Action 开发者可以像调用普通函数一样使用这些强大的复合行为，而无需处理异步编程的复杂性。

## 3. 核心逻辑解析

`CompositeInteractionService` 的核心逻辑在于其**异步轮询（Asynchronous Polling）**和**超时控制**的设计模式。几乎所有的核心方法都基于这个模式，这使得它能够高效地处理那些需要“等待”的自动化场景，而不会阻塞系统。

以 `click_text_async` 方法为例，其执行流程完美地展示了这一核心逻辑：

1.  **启动超时控制**: 整个逻辑被包裹在一个 `async with asyncio.timeout(timeout):` 块中。这利用了 Python `asyncio` 库的特性，创建了一个上下文，如果内部的代码块执行时间超过指定的 `timeout` 秒，它会自动引发一个 `TimeoutError` 异常。

2.  **异步 `while` 循环**: 紧接着是一个 `while True:` 循环，构成了轮询的基础。

3.  **非阻塞操作序列**: 在循环的每一次迭代中，服务会执行一系列 `await` 操作：
    *   `await self.app.capture_async(...)`: 等待一次非阻塞的截图。
    *   `await self.ocr._find_text_async(...)`: 等待一次非阻塞的 OCR 文本查找。
    *   如果找到文本：
        *   `await self.app.click_async(...)`: 等待一次非阻塞的点击操作。
        *   `return True`: 成功找到并点击，循环和函数都正常退出。
    *   如果未找到文本：
        *   `await asyncio.sleep(0.1)`: **这是关键**。它会非阻塞地暂停当前协程 `0.1` 秒，将执行权交还给事件循环，让CPU可以去处理其他任务（例如，响应 API 请求、执行其他并发的 Action 等）。`0.1` 秒后，事件循环会再次唤醒这个协程，开始下一次循环迭代。

4.  **异常处理**: 如果 `asyncio.timeout` 引发了 `TimeoutError`，`except TimeoutError:` 块会被触发，函数会记录一条警告日志并 `return False`，清晰地向上层报告操作失败。

这种**“超时上下文 + 异步循环 + 短暂休眠”**的模式，是构建健壮、高效的等待逻辑的黄金标准。它避免了使用 `time.sleep()` 这样的阻塞调用，确保了即使在执行长达数十秒的等待操作时，Aura 框架的事件循环也始终保持活跃和高响应性。
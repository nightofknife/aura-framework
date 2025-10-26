# 文件: `plans/aura_base/services/screen_service.py`

## 1. 核心目的

该文件定义了 `ScreenService`，一个专门用于与 Windows 桌面环境进行交互的服务。它的核心职责是提供**屏幕截图**、**窗口聚焦**和**像素颜色拾取**等底层图形界面操作的能力。这个服务的设计目标是封装 `win32api` 等底层库的复杂性，为上层的自动化动作（Actions）提供一个简单、可靠且高性能的接口。

## 2. 关键组件与功能

*   **`ScreenService`**:
    *   **`__init__(config: ConfigService)`**: 初始化服务。它会从配置服务中读取目标窗口的标题（`app.target_window_title`）。如果标题被设定，服务将工作在**窗口模式**；否则，它将工作在**全屏模式**。
    *   **`capture(rect=None)`**: 公开的截图接口。它是一个**同步方法**，但内部通过“同步/异步桥接器”将实际的截图操作委托给异步方法 `capture_async` 在后台线程中执行，从而避免阻塞主事件循环。它可以对整个目标窗口或指定的子区域进行截图。
    *   **`focus()`**: 公开的窗口聚焦接口。它同样是一个同步方法，内部调用 `focus_async` 来将目标窗口带到前台。
    *   **`get_client_rect()`**: 获取目标窗口客户区（即可交互区域）的全局屏幕坐标和尺寸。这是一个快速的同步调用。
    *   **`get_pixel_color_at(x, y)`**: 获取屏幕上指定全局坐标点的像素颜色值（RGB）。这也是一个快速的同步调用。
    *   **`capture_async(rect=None)`**: `capture` 方法的异步核心实现。它会处理窗口最小化的情况，并通过 `asyncio.to_thread` 将耗时且阻塞的 `_capture_window_sync` 或 `_capture_fullscreen_sync` 方法调度到线程池中执行。
    *   **`_capture_window_sync(...)` / `_capture_fullscreen_sync()`**: 这两个是实际执行截图操作的**同步方法**。它们直接调用 `win32gui`, `win32ui` 等库来获取屏幕或窗口的设备上下文（DC），创建位图，并将截图数据复制到内存中。
    *   **`_bitmap_to_numpy(...)`**: 一个静态工具方法，负责将 Windows GDI 位图对象（一个内存块）高效地转换为 `numpy.ndarray` 数组，并使用 `OpenCV` 转换为标准的 RGB 格式。这是连接底层 Windows API 和上层图像处理库（如 OpenCV）的关键桥梁。

*   **`CaptureResult`**: 一个 `dataclass`，用于封装截图操作的结果。它不仅包含了截图成功后的图像数据（`np.ndarray`），还包含了窗口的矩形区域、相对截图区域、操作是否成功以及错误信息等元数据，使得返回值结构清晰且易于使用。

## 3. 核心逻辑解析

`ScreenService` 最核心的设计是**同步/异步桥接模式**，以解决在 `asyncio` 框架中调用阻塞性原生 API（如 `win32gui` 的截图函数）的难题。

直接在异步事件循环中调用 `win32gui.BitBlt` 这样的函数会导致整个应用程序被阻塞，直到截图完成，这对于需要高响应性的自动化框架是致命的。该服务通过以下机制优雅地解决了这个问题：

1.  **统一的同步接口**: 对外（即对 Actions 调用者）暴露的接口如 `capture()` 和 `focus()` 都是标准的同步方法。这使得上层逻辑的编写者无需关心异步的复杂性。

2.  **异步核心实现**: 每个同步接口内部都对应一个 `..._async` 的异步方法（例如 `capture_async`）。

3.  **桥接器 `_submit_to_loop_and_wait()`**: 这是连接同步和异步世界的关键。当一个同步方法如 `capture()` 被调用时，它实际上是调用了 `_submit_to_loop_and_wait(self.capture_async(...))`。
    *   `_get_running_loop()`: 桥接器首先线程安全地从 `Scheduler` 获取到当前正在运行的 `asyncio` 事件循环。
    *   `asyncio.run_coroutine_threadsafe()`: 这是 Python `asyncio` 库提供的标准函数，用于从外部线程向事件循环提交一个协程任务。它会返回一个 `Future` 对象。
    *   `future.result()`: 这是一个**阻塞调用**。它会暂停当前线程（即调用 `capture()` 的那个线程，但**不是**主事件循环线程），直到事件循环执行完 `capture_async` 协程并返回结果。

4.  **将阻塞操作移至线程池**: 在 `capture_async` 协程内部，它并不会直接执行截图，而是使用 `await asyncio.to_thread(self._capture_window_sync, ...)`。`asyncio.to_thread` 会将 `_capture_window_sync` 这个包含阻塞 win32 API 调用的同步函数，提交给 `ThreadPoolExecutor` 来执行。这确保了即便是最耗时的操作也不会阻塞主事件循环。

通过这四层精巧的封装（**同步接口 -> 桥接器 -> 异步协程 -> 线程池**），`ScreenService` 成功地将一个天生阻塞的功能无缝地集成到了一个高性能的异步框架中，既保证了接口的易用性，又避免了对框架整体性能的影响。
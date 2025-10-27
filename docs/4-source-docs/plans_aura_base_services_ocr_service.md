# 文件: `plans/aura_base/services/ocr_service.py`

## 1. 核心目的

该文件定义了 `OcrService`，这是一个专用于**光学字符识别（OCR）**的服务。它的核心职责是封装强大的 `PaddleOCR` 引擎，为上层应用提供一个简单、高效且资源可控的接口，用于从图像中识别和查找文本。

该服务的关键设计目标是解决在并发自动化环境中有效管理**重资源（如GPU内存）**和**长耗时（引擎初始化）**的 OCR 引擎所带来的挑战。

## 2. 关键组件与功能

*   **`OcrService`**:
    *   **`__init__()`**: 初始化服务。它并不立即加载 OCR 引擎，而是初始化了几个关键的异步控制组件：
        *   `_engine`: 用于存储**单一共享**的 `PaddleOCR` 引擎实例。
        *   `_engine_lock`: 一个 `asyncio.Lock`，用于确保引擎的初始化过程是线程安全的，防止多个并发请求同时尝试初始化引擎。
        *   `_ocr_semaphore`: 一个值为 `1` 的 `asyncio.Semaphore`，这是**资源控制的核心**。它确保在任何时刻，只有一个 OCR 预测任务能够在 GPU 上运行，从而防止 GPU 显存溢出和因并发访问导致的冲突。
    *   **`_initialize_engine_async()`**: 异步的引擎初始化方法。它使用 `_engine_lock` 来保证单次初始化，并通过 `asyncio.to_thread` 将耗时的 `PaddleOCR()` 构造函数调用移至后台线程执行，避免阻塞主事件循环。
    *   **`_get_engine_async()`**: 一个辅助方法，确保在执行任何 OCR 操作之前，引擎实例已经被安全地初始化。
    *   **`_recognize_all_and_parse_async(source_image)`**: **所有 OCR 功能的核心入口**。它首先获取引擎实例，然后通过 `async with self._ocr_semaphore:` 来获取 GPU 的使用权。一旦获取到信号量，它就调用 `_run_ocr_sync` 在后台线程执行实际的 OCR 预测，完成后再释放信号量。
    *   **`_run_ocr_sync(engine, image)`**: 这是一个纯粹的、阻塞的同步函数，负责调用 `engine.predict()`。它被设计为专门在由 `asyncio.to_thread` 管理的线程池中运行。
    *   **接口方法 (如 `find_text`, `recognize_all`)**: 与其他服务一样，它为每个核心的异步功能（`_find_text_async` 等）都提供了一个同名的**同步接口**。这些同步接口通过 `_submit_to_loop_and_wait` 桥接器，使得上层 Action 可以简单地调用它们，而无需关心底层的异步和并发控制。

*   **`OcrResult` / `MultiOcrResult`**: 用于封装 OCR 结果的 `dataclass`。它们提供了结构化的数据，包含了识别到的文本、位置、中心点、置信度等信息，使得 OCR 结果易于被上层逻辑消费。

## 3. 核心逻辑解析

`OcrService` 的核心逻辑在于其**对共享资源的精细化异步管理**，主要体现在两个方面：**延迟初始化**和**并发控制**。

### 1. 延迟、线程安全的单例引擎初始化

传统的服务可能会在 `__init__` 中直接创建 `PaddleOCR` 实例。这种做法有两个弊端：
a. **拖慢启动速度**: `PaddleOCR` 初始化可能需要数秒钟，如果在框架启动时同步执行，会显著延长整体启动时间。
b. **资源浪费**: 如果在整个运行过程中都没有用到 OCR 功能，那么预先加载引擎就纯粹是浪费内存和显存。

`OcrService` 通过 `_get_engine_async` 完美地解决了这个问题：
*   **延迟加载 (Lazy Loading)**: 引擎实例 `self._engine` 初始为 `None`。只有在第一次真正需要执行 OCR 操作时，`_get_engine_async` 才会被调用。
*   **异步初始化**: 在 `_get_engine_async` 中，它会调用 `_initialize_engine_async`。此方法通过 `asyncio.to_thread` 将耗时的初始化过程抛到后台线程，当前任务会 `await` 等待其完成，但整个事件循环不会被阻塞。
*   **防止竞态条件**: 使用 `asyncio.Lock` (`_engine_lock`) 确保了即使有多个 Action 在同一时刻首次请求 OCR，也只有一个会真正执行初始化过程，其他的则会等待第一个完成，然后直接使用已经创建好的共享实例。

### 2. 基于信号量的 GPU 并发控制

`PaddleOCR` 在 GPU 上运行时会占用大量显存。如果不加控制地并发执行多个 OCR 预测，很容易导致显存溢出（OOM）错误，使整个应用崩溃。

`OcrService` 使用 `asyncio.Semaphore(1)` (`_ocr_semaphore`) 来作为访问 GPU 的“令牌”。
*   在 `_recognize_all_and_parse_async` 方法中，所有实际的 OCR 调用都被包裹在 `async with self._ocr_semaphore:` 代码块中。
*   `async with` 会自动执行 `acquire()` 和 `release()`。因为信号量的计数器为 `1`，所以任何时候只允许一个协程进入这个代码块。
*   当一个 OCR 任务正在执行时，其他所有尝试执行 OCR 的任务都会在 `async with` 处**异步地等待**，它们会暂停执行并将控制权交还给事件循环，直到当前任务完成并释放信号量。

这种设计确保了对 GPU 资源的访问是**串行**的，从根本上杜绝了并发冲突和资源超用的问题，同时又利用了 `asyncio` 的能力，使得等待中的任务不会阻塞其他非 OCR 相关的任务，从而在保证稳定性的前提下实现了高效的资源利用。
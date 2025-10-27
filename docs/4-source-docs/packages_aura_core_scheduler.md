# 文件: `packages/aura_core/scheduler.py`

## 1. 核心目的

该文件定义了 `Scheduler` 类，是整个 Aura 框架的**中央控制器和“大脑”**。它的核心职责是协调框架的所有组件，管理任务的完整生命周期（从接收、排队到执行和清理），维护系统的核心状态，并为外部接口（如 `api_server.py` 和 `cli.py`）提供一个统一、线程安全的交互入口。

可以说，`Scheduler` 是 Aura 框架中所有活动的起点和总指挥。

## 2. 关键组件与功能

*   **`Scheduler`**:
    *   **`__init__()`**: 构造函数负责**实例化**所有核心服务，包括 `PlanManager`, `ExecutionManager`, `EventBus`, `ConfigService` 等。它还会立即调用 `reload_plans()` 来执行首次的插件和任务加载，确保在框架启动前所有资源都已准备就绪。
    *   **`start_scheduler()` / `stop_scheduler()`**: 这两个方法管理着框架的**主运行线程**。`start_scheduler` 会创建一个新的后台线程来运行 `asyncio` 事件循环，并通过一个 `threading.Event` (`startup_complete_event`) 来同步启动过程，确保在所有后台服务都就绪后才返回。
    *   **`run()`**: 这是在后台线程中运行的主异步方法。它使用 `asyncio.TaskGroup` 来并发地启动和管理框架所有的**常驻后台协程**，包括多个任务队列的消费者、定时任务服务等。
    *   **队列消费者 (`_consume_..._queue`)**:
        *   `_consume_main_task_queue()`: 最核心的消费者，负责从主任务队列中取出 `Tasklet`，检查并发限制（`max_concurrency`），然后提交给 `ExecutionManager` 执行。
        *   `_consume_interrupt_queue()`: 处理中断事件，负责取消当前正在运行的任务并执行中断处理程序。
        *   `_event_worker_loop()`: 处理由事件触发的后台任务。
    *   **任务提交接口**:
        *   `run_ad_hoc_task(...)`: 用于接收并执行临时的、通过 API 或 CLI 提交的任务。它负责验证输入参数、创建 `Tasklet` 对象，并将其放入主任务队列。
        *   `run_manual_task(...)`: 用于执行一个在 `schedule.yaml` 中预定义的、带固定参数的任务。
    *   **状态管理与查询**: `Scheduler` 维护着多个关键的状态字典，如 `running_tasks`（跟踪正在执行的任务）、`schedule_items`（所有定时任务的定义）等，并提供了一系列 `get_*` 方法（如 `get_schedule_status`）来线程安全地查询这些状态。
    *   **热重载 (`HotReloadHandler`)**: 这是一个内嵌的 `watchdog` 事件处理器，用于监控 `plans/` 目录的文件变动。当检测到 `.py` 或 `.yaml` 文件被修改时，它会触发相应的热重载逻辑（`reload_plugin_from_py_file` 或 `reload_task_file`），实现动态更新。

## 3. 核心逻辑解析

`Scheduler` 的核心逻辑在于它如何作为一个**多线程、多队列的异步系统协调者**来工作的。

### 1. 线程模型与同步机制

Aura 框架被设计为一个在后台运行的服务。`Scheduler` 通过以下方式实现了这一点：
*   **主线程与调度器线程**: 当外部调用 `scheduler.start_scheduler()` 时，它会启动一个新的 `threading.Thread` (`_scheduler_thread`)。所有 `asyncio` 相关的代码，包括事件循环和所有协程，都运行在这个独立的**调度器线程**中。而调用 `start_scheduler` 的线程（例如，CLI 的主线程）则可以继续执行其他操作，不会被阻塞。
*   **线程安全接口**: `Scheduler` 的所有公共方法（如 `run_ad_hoc_task`）都被设计为线程安全的。它们通常通过 `asyncio.run_coroutine_threadsafe()` 函数，将一个需要**在事件循环中执行**的异步操作（如 `await self.task_queue.put(tasklet)`）从**外部线程**安全地提交给**调度器线程**的事件循环去执行。这种模式是连接同步世界和异步世界的桥梁。
*   **锁机制**: 为了保护共享状态（如 `running_tasks` 字典），`Scheduler` 同时使用了 `threading.RLock` (`fallback_lock`) 和 `asyncio.Lock` (`async_data_lock`)。前者用于保护可能从外部线程访问的数据，后者用于保护在事件循环内部可能被多个协程并发访问的数据。

### 2. 多队列消费者模型

`Scheduler` 不只有一个任务队列，而是维护了多个专用的队列，并通过并发的消费者协程来处理它们：
*   **`task_queue` (主任务队列)**: 用于处理用户手动触发或按计划执行的标准任务。它的消费者 `_consume_main_task_queue` 受 `max_concurrency` 并发数限制。
*   **`event_task_queue` (事件任务队列)**: 用于处理由 `EventBus` 上的事件触发的、通常需要快速响应的轻量级任务。它由多个 `_event_worker_loop` 消费者处理，通常有更高的并发能力。
*   **`interrupt_queue` (中断队列)**: 优先级最高的队列，用于处理紧急的中断事件。它的消费者 `_consume_interrupt_queue` 会立即暂停或取消主队列中的任务，并执行中断处理程序。

这种多队列、多消费者的架构，实现了任务的**优先级划分**和**关注点分离**。高优先级的或不同类型的任务（如事件响应）不会被主队列中可能存在的长耗时任务所阻塞，从而保证了整个框架的响应性和健壮性。
# 文件: `packages/aura_core/execution_manager.py`

## 1. 核心目的

该文件的核心职责是定义**执行管理器（`ExecutionManager`）**。在 Aura 框架中，`ExecutionManager` 是一个**全局单例**，扮演着所有任务执行的“总调度中心”和“资源管理器”的角色。它位于 `Scheduler` 之下，`Orchestrator` 之上，负责协调和管理任务从被调度到实际执行的整个过程。

其主要职责包括：

1.  **资源池管理**: 创建并管理用于执行 IO 密集型任务的**线程池**和用于执行 CPU 密集型任务的**进程池**。这是 Aura 框架高性能并发能力的基础。
2.  **并发控制**: 通过一个全局信号量（Semaphore）和多个基于资源的信号量，严格控制同时运行的任务数量，防止系统因过载而崩溃。
3.  **任务提交入口**: 提供统一的 `submit` 方法，接收来自 `Scheduler` 的任务单元（`Tasklet`），并负责其后续的执行流程。
4.  **状态规划协调**: 在任务正式执行前，负责调用 `StatePlanner` 来进行**前置状态规划**，确保系统处于任务所需的正确初始状态。
5.  **生命周期管理与钩子**: 在任务执行的各个关键阶段（开始前、成功、失败、结束后），触发全局钩子（Hooks），允许其他插件对任务执行过程进行干预或监控。
6.  **健壮的错误处理**: 统一处理任务执行过程中可能出现的各种异常，如超时（`TimeoutError`）、取消（`CancelledError`）和状态规划失败等，确保框架的健壮性。

## 2. 关键类与函数

*   **`ExecutionManager` (Class)**:
    *   **作用**: 封装了所有与任务执行、并发控制和资源管理相关的功能。
    *   **`scheduler` (Attribute)**: 持有对 `Scheduler` 主实例的引用，以便在需要时回调调度器的方法（如更新任务状态）。
    *   **`_io_pool` / `_cpu_pool` (Attributes)**: 分别是 `ThreadPoolExecutor` 和 `ProcessPoolExecutor` 的实例，是执行任务的“劳动力”。
    *   **`_global_sem` / `_resource_sems` (Attributes)**: `asyncio.Semaphore` 实例，是实现并发控制的关键工具。
    *   **`startup()` / `shutdown()`**:
        *   **作用**: 管理执行池生命周期的方法。`startup` 在应用启动时创建池，`shutdown` 在应用关闭时优雅地销毁它们。

    *   **`submit(tasklet, ...)`**:
        *   **作用**: **核心公共入口方法**。这是执行管理器最重要的方法，它接收一个 `Tasklet` 并编排其完整的执行生命周期。

    *   **`_handle_state_planning(tasklet)`**:
        *   **作用**: 一个专门的私有方法，负责处理所有与状态规划相关的复杂逻辑。它与 `Orchestrator` 的 `StatePlanner` 协作，确保任务的前置条件得到满足。

    *   **`_run_execution_chain(tasklet)`**:
        *   **作用**: 任务执行链的最后一步。它负责从 `tasklet` 中解析出 `plan_name` 和 `task_name`，找到对应的 `Orchestrator` 实例，并最终调用 `orchestrator.execute_task` 来启动 YAML 任务的执行。

*   **`StatePlanningError` (Exception Class)**:
    *   **作用**: 一个自定义的异常类。当状态规划过程发生不可恢复的错误时，会抛出此异常，以便在 `submit` 方法中被专门捕获和处理。

## 3. 核心逻辑解析

`ExecutionManager.submit` 方法是该模块的逻辑核心，它通过一个精心设计的、包含多层 `try...except...finally` 结构的异步上下文管理流程，确保了任务执行的健壮性和资源的正确管理。

其核心流程可以分解为：

1.  **获取信号量 (并发控制)**:
    *   `semaphores = await self._get_semaphores_for(tasklet)`: 首先，它会根据任务的资源标签获取所有需要的信号量。
    *   `async with AsyncExitStack() as stack: for sem in semaphores: await stack.enter_async_context(sem)`: 这是实现并发控制的关键。代码会 `await` 直到**所有**必需的信号量都可用。如果全局并发已满，或者特定资源（如某个 App）的并发已满，执行会在这里被异步阻塞，直到有其他任务完成并释放信号量。`AsyncExitStack` 确保无论后续发生什么，所有被获取的信号量最终都会被释放。

2.  **状态规划 (前置条件)**:
    *   `planning_success = await self._handle_state_planning(tasklet)`: 在获得执行权（即获取了所有信号量）之后，它会立即处理状态规划。
    *   `_handle_state_planning` 内部会调用 `StatePlanner` 的一系列方法来感知、规划和执行状态转移。这是一个**带重试的循环**，如果一次转移失败，它会重新规划并尝试，直到成功或达到最大重试次数。
    *   如果最终规划失败，它会直接抛出 `StatePlanningError`，跳过主任务的执行。

3.  **主任务执行 (核心业务)**:
    *   `async with asyncio.timeout(tasklet.timeout):`: 整个任务的执行被一个 `asyncio.timeout` 上下文管理器包裹。如果任务执行时间超过了 `tasklet` 中定义的超时秒数，它会自动抛出 `asyncio.TimeoutError`。
    *   **触发钩子**: `await hook_manager.trigger('before_task_run', ...)`: 在执行前触发 `before_task_run` 钩子。
    *   **委派执行**: `result = await self._run_execution_chain(tasklet)`: 调用内部方法，最终将执行权交给对应的 `Orchestrator`。
    *   **触发钩子**: `await hook_manager.trigger('after_task_success', ...)`: 如果任务成功，触发 `after_task_success` 钩子。

4.  **统一的异常处理**:
    *   `except (asyncio.TimeoutError, asyncio.CancelledError, StatePlanningError) as e:`: 这是一个多异常捕获块，专门处理**可预见的、非致命的**执行失败情况（超时、被外部取消、规划失败）。它会记录相应的错误日志，更新任务状态，并触发 `after_task_failure` 钩子。
    *   `except Exception as e:`: 这是一个捕获所有其他意外异常的“兜底”块。它处理代码 bug 等**不可预见的**错误，记录更高级别的 `critical` 日志，并同样触发失败钩子。

5.  **资源释放 (确保执行)**:
    *   `finally:`: `finally` 块确保无论 `try` 块中发生了什么（成功、可预见的失败、意外的失败），最终的清理工作都会被执行。
    *   `await hook_manager.trigger('after_task_run', ...)`: 触发 `after_task_run` 钩子，这是一个无论成功失败都会执行的钩子。
    *   信号量的释放由 `AsyncExitStack` 自动处理。

通过这个层次分明、逻辑严谨的执行流程，`ExecutionManager` 确保了每个提交给它的任务都能在满足并发和状态约束的前提下被安全、可靠地执行，并且无论结果如何，系统的状态和资源都能得到正确的更新和释放。
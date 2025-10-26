# 文件: `packages/aura_core/asynccontext.py`

## 1. 核心目的

该文件的核心目的是提供一个专门用于管理**异步上下文**的工具。具体来说，它定义了一个名为 `plan_context` 的**异步上下文管理器**，用于在 `asyncio` 环境中安全地设置、使用和重置一个关键的上下文变量——`current_plan_name`。

在像 Aura 这样需要同时执行多个不同任务（可能来自不同的 Plan）的并发框架中，区分每个任务的“身份”至关重要。这个文件提供的工具正是为了解决这个问题，确保框架的各个部分（尤其是像 `ConfigService` 这样的共享服务）能够准确地知道当前正在执行的代码片段隶属于哪一个 Plan。

## 2. 关键组件与功能

*   **`@asynccontextmanager`**: 这是一个来自 Python `contextlib` 库的装饰器，它允许通过一个简单的 `async def` 生成器函数来创建一个异步上下文管理器，而无需编写一个完整的类并实现 `__aenter__` 和 `__aexit__` 方法。

*   **`plan_context(plan_name: str)`**:
    *   **目的**: 这是该文件提供的唯一功能。它是一个异步上下文管理器，当在一个 `async with` 语句中使用时，它会将 `current_plan_name` 这个上下文变量（`ContextVar`）的值临时设置为传入的 `plan_name`。
    *   **用法**:
        ```python
        from packages.aura_core.asynccontext import plan_context
        from plans.aura_base.services.config_service import current_plan_name

        async def some_task_execution():
            async with plan_context("my_plan"):
                # 在这个代码块内部，任何对 current_plan_name.get() 的调用
                # 都会返回 "my_plan"。
                # ConfigService 在这里调用 get() 就能找到 my_plan 的专属配置。
                ...
            # 当代码块结束时（无论是正常结束还是因为异常），
            # current_plan_name 的值会自动恢复到进入 async with 之前的状态。
        ```

## 3. 核心逻辑解析

`plan_context` 的核心逻辑在于它如何正确地使用 `ContextVar` 的 `get`, `set`, 和 `reset` 方法来确保上下文的隔离和安全恢复。

让我们分解 `plan_context` 函数的内部工作流程：

1.  **获取当前值**: `current = current_plan_name.get()`。在进入上下文之前，它首先获取并保存 `current_plan_name` 在当前上下文中的值。

2.  **检查与设置**: `if current != plan_name:`。它会检查当前的值是否已经是要设置的值。
    *   **如果值不同**:
        *   `token = current_plan_name.set(plan_name)`: 它调用 `.set()` 方法来设置新的值。这个方法非常关键，因为它**不会**改变变量在其他并发任务中的值，只会影响当前的异步上下文。同时，它返回一个 `token` 对象，这个 `token` 稍后可以用来将变量**精确地**恢复到调用 `.set()` 之前的状态。
        *   `try...yield...finally`: 这是一个标准的上下文管理器模式。
            *   `yield`: 这个关键字将控制权交还给 `async with` 块内部的代码。此时，`current_plan_name` 的值已经是新的 `plan_name`。
            *   `finally`: **这部分是保证健壮性的关键**。无论 `async with` 块内部的代码是正常执行完毕，还是因为 `return`, `break`, `continue` 或**抛出异常**而退出，`finally` 块中的代码都**保证会被执行**。
            *   `current_plan_name.reset(token)`: 它使用之前获取的 `token` 来调用 `.reset()`。这会将 `current_plan_name` 的值**精确地**恢复到调用 `.set()` 之前的那一刻的状态，从而避免了上下文的“泄露”。

    *   **如果值相同**:
        *   `else: yield`: 如果当前上下文的值已经是期望的值，那么就无需进行任何 `set` 或 `reset` 操作。这是一种性能优化，可以避免不必要的上下文切换开销，尤其是在可能出现嵌套调用 `plan_context` 的情况下。

通过这种严谨的设计，`plan_context` 为 Aura 框架提供了一个强大而安全的工具。它使得像 `Orchestrator` 这样的核心组件可以在执行来自特定 Plan 的任务时，简单地用 `async with plan_context(plan.name):` 将整个执行过程包裹起来，从而确保在这个任务的所有执行路径上（包括所有深层嵌套的函数调用和 await），框架都能正确地识别出其“身份”，实现配置、日志、资源等的精确隔离。
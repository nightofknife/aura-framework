# 文件: `packages/aura_core/orchestrator.py`

## 1. 核心目的

该文件的核心职责是定义**编排器（`Orchestrator`）**。在 Aura 框架中，`Orchestrator` 是与**单个自动化方案（Plan）**紧密绑定的执行核心。每一个 Plan 在被加载时，都会拥有一个自己专属的 `Orchestrator` 实例。

`Orchestrator` 扮演着“项目经理”的角色，它不亲自执行具体的原子操作（Action），而是负责管理一个 Plan 内部**所有任务（Task）的完整生命周期**。其职责包括：

1.  **任务执行入口**: 作为执行 Plan 内任务的统一入口，负责加载任务定义（YAML 文件）、初始化执行上下文。
2.  **引擎委派**: 将解析好的任务数据和上下文交给 `ExecutionEngine`，由引擎负责实际的步骤（step）执行。
3.  **生命周期管理**: 在任务开始和结束时，通过 `EventBus` 发布标准化的生命周期事件（`task.started`, `task.finished`），供其他系统部分监听。
4.  **结果封装**: 将任务的执行结果（无论成功、失败还是错误）都封装成一个标准化的**任务最终结果对象（TFR, Task Final Result）**。
5.  **安全沙箱**: 提供一系列文件系统操作的接口，但将所有操作严格限制在当前 Plan 的目录内，防止任务越权访问其他文件，确保安全性。

## 2. 关键类与函数

*   **`Orchestrator` (Class)**:
    *   **作用**: 封装了与单个 Plan 相关的所有任务执行和管理逻辑。
    *   **`plan_name` (Attribute)**: 标识此 `Orchestrator` 实例所服务的 Plan 的名称。
    *   **`current_plan_path` (Attribute)**: 当前 Plan 在文件系统中的绝对路径，是实现文件操作沙箱的根目录。
    *   **`task_loader` (Attribute)**: 一个 `TaskLoader` 实例，专门负责按需从磁盘加载和缓存任务的 YAML 定义文件。
    *   **`state_planner` (Attribute)**: 一个可选的 `StatePlanner` 实例。如果当前 Plan 是一个基于状态的 Plan，这里会持有对应的状态规划器。
    *   **`event_bus`, `state_store`, `services` (Attributes)**: 从全局 `service_registry` 中获取的核心服务实例的快捷方式，供任务执行时使用。

    *   **`execute_task(task_name_in_plan, ...)`**:
        *   **作用**: **核心公共入口方法**。框架的其他部分（如 `Scheduler`）通过调用此方法来请求执行一个任务。它负责整个任务执行流程的编排。

    *   **`perform_condition_check(condition_data)`**:
        *   **作用**: 一个专门用于执行条件检查的辅助方法。它通常被中断规则（Interrupt Rules）使用，以判断是否满足中断条件。它会动态创建一个临时的执行上下文来运行条件中的 `action`。

    *   **`_resolve_and_validate_path(relative_path)`**:
        *   **作用**: **安全沙箱机制的核心**。这是一个私有方法，负责将用户提供的相对路径解析为安全的绝对路径，并进行严格的验证，以防止任何形式的路径穿越攻击（Path Traversal）。

    *   **`get_file_content`, `save_file_content`, `delete_path`, etc.**:
        *   **作用**: 一系列提供给 Action 使用的、**异步的、沙箱化的文件系统操作接口**。所有这些方法在执行操作前，都会调用 `_resolve_and_validate_path` 来确保路径的安全性。

## 3. 核心逻辑解析

`Orchestrator.execute_task` 是该模块中最为核心的方法，它清晰地展示了一个任务从被调用到返回结果的全过程。其逻辑可以分解为以下几个关键阶段：

1.  **上下文设置与唯一 ID 生成**:
    *   `token = current_plan_name.set(self.plan_name)`: 在任务执行的最开始，它使用 `ContextVar` 将当前的 Plan 名称设置到异步上下文中。这确保了在任务执行期间，任何地方调用的共享服务（如 `ConfigService`）都能正确地读取到专属于此 Plan 的配置。
    *   `run_id = f"{...}:{_run_ms}"`: 为本次任务执行创建一个全局唯一的 `run_id`，用于在日志和事件中追踪整个任务的生命周期。

2.  **发布 `task.started` 事件**:
    *   `await self.event_bus.publish(...)`: 立即发布一个 `task.started` 事件，通知系统的其他部分（如 UI、日志系统）一个新的任务已经开始执行。

3.  **初始化执行环境**:
    *   `task_data = self.task_loader.get_task_data(...)`: 使用 `TaskLoader` 加载任务的 YAML 定义。
    *   `root_context = ExecutionContext(...)`: 创建一个根执行上下文（`ExecutionContext`），并将外部传入的 `inputs` 存入其中。
    *   `engine = ExecutionEngine(...)`: 实例化执行引擎 `ExecutionEngine`，并将 `Orchestrator` 自身的引用 (`self`) 传递给它，同时还提供了一个 `step_event_callback` 用于在每个步骤执行前后发布事件。

4.  **委派执行**:
    *   `final_context = await engine.run(...)`: **这是责任的交接点**。`Orchestrator` 将任务数据和根上下文交给 `engine.run` 方法，并 `await` 其执行完成。`Orchestrator` 不关心 `run` 方法内部是如何循环执行步骤的，它只等待最终的结果。

5.  **结果处理与 TFR 构建**:
    *   **状态判断**: 任务结束后，`Orchestrator` 会仔细检查返回的 `final_context`，特别是 `framework_data` 中的 `nodes` 状态，以确定任务的最终状态是 `SUCCESS` 还是 `FAILED`。
    *   **返回值渲染**: 如果任务成功并且定义了 `returns` 模板，它会使用 `TemplateRenderer` 来渲染最终的返回值 (`user_data`)。
    *   **异常捕获**: 整个执行过程被一个巨大的 `try...except` 块包裹。任何在执行引擎或渲染阶段发生的异常都会被捕获，并将任务的最终状态设置为 `ERROR`，同时记录详细的错误信息。

6.  **发布 `task.finished` 事件与上下文清理**:
    *   `finally:`: 无论任务执行成功、失败还是出错，`finally` 块中的代码都保证会被执行。
    *   `await self.event_bus.publish(...)`: 发布 `task.finished` 事件，并附带上完整的 TFR 对象。
    *   `current_plan_name.reset(token)`: **至关重要的一步**。它使用之前保存的 `token` 将异步上下文恢复到任务执行前的状态，避免了上下文“泄露”，确保了系统的隔离性和稳定性。

通过这个严谨的、结构化的流程，`Orchestrator` 确保了每个任务的执行都是可预测、可追踪、有始有终且与其他任务隔离的。
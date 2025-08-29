 好的，这是根据所有更新后的模块文档，为您编写的全新、最终版的**Aura 核心架构概览**。

---

# **Aura 核心架构概览 (Aura Core Architecture Overview)**

Aura 框架的核心 (`aura_core`) 被设计成一个高度模块化、可扩展、完全异步的系统。它由一系列各司其职、通过明确定义的异步接口和队列进行通信的服务与组件构成。理解这些组件如何协同工作，是深入掌握 Aura、进行二次开发或问题排查的关键。

## **模块化组件概览**

以下是 `aura_core` 包中所有核心模块的简要职责说明。

*   **[scheduler.py](./scheduler.md)**: **异步核心与服务门面**。协调所有核心服务的生命周期，运行一个基于 `asyncio.TaskGroup` 的并发消费者模型来处理所有任务队列，并为外部（如UI、API）提供统一的API门面。
*   **[plan_manager.py](./plan_manager.md)**: **方案管理器**。负责管理所有已加载方案（Plan）的生命周期，并为每个方案创建和持有一个专属的 `Orchestrator` 实例。
*   **[plugin_manager.py](./plugin_manager.md)**: **插件生命周期管理器**。负责发现、解析、排序和加载所有插件，构建起框架的运行时功能（填充服务与行为注册表）。它现在只负责功能注册，不负责运行时实例的创建。
*   **[execution_manager.py](./execution_manager.md)**: **并发执行中心**。接收所有类型的 `Tasklet`，并根据其元数据（如 `execution_mode`, `resource_tags`）安全地调度执行。它管理着 `asyncio` 任务、线程池和进程池，并处理资源限制与并发控制。
*   **[scheduling_service.py](./scheduling_service.md)**: **时间调度服务 (闹钟)**。独立的异步后台服务，专职处理 `cron` 定时任务，并将到期任务异步放入主任务队列。
*   **[interrupt_service.py](./interrupt_service.md)**: **中断监控服务**。独立的异步后台服务，专职监控中断条件，并在条件满足时发出中断信号。
*   **[orchestrator.py](./orchestrator.md)**: **方案级异步编排器**。负责单个方案（Plan）内的任务协调，管理 `go_task` 任务链，处理 `on_failure` 和 `returns` 逻辑，并提供对方案内资源的异步访问。
*   **[engine.py](./engine.md)**: **异步任务执行引擎**。负责异步执行单个任务（Task）中的所有步骤（Steps），管理任务级的上下文和参数渲染。
*   **[action_injector.py](./action_injector.md)**: **异步行为注入与执行器**。框架的最底层执行单元，负责准备并异步调用一个具体的 Action 函数，处理服务依赖注入和中间件调用。
*   **[middleware.py](./middleware.md)**: **异步中间件管理器**。实现了“洋葱模型”，允许在 Action 执行前后注入可插拔的异步逻辑，并兼容在线程池中运行旧的同步中间件。
*   **[state_planner.py](./state_planner.md)**: **状态规划器 (GPS)**。使用 Dijkstra 算法，根据 `states_map.yaml` 计算出从当前状态到目标状态的、成本最低的任务执行路径。
*   **[api.py](./api.md)**: **核心注册表**。定义了框架中所有核心的全局注册表，如 `service_registry`, `ACTION_REGISTRY` 等，是框架解耦的核心。
*   **[hook_manager.py](./hook_manager.md)**: **钩子管理器**。提供事件驱动的扩展点，允许插件在框架生命周期的特定时刻执行代码。
*   **[event_bus.py](./event_bus.md)**: **异步事件总线**。实现了发布-订阅（Pub/Sub）模式，用于在框架各组件之间进行异步、解耦的通信。
*   **[context_manager.py](./context_manager.md)**: **异步上下文管理器**。负责异步创建和管理任务执行时的上下文（Context），整合了持久化数据和临时数据。
*   **[persistent_context.py](./persistent_context.md)**: **异步持久化上下文**。提供了与 `persistent_context.json` 文件绑定的、非阻塞的、基于 JSON 的数据持久化机制。
*   **[state_store.py](./state_store.md)**: **全局状态存储**。一个线程安全的、支持 TTL 的内存键值存储，用于管理跨任务的临时状态（驻留信号）。
*   **[task_loader.py](./task_loader.md)**: **任务加载与规范化器**。专职从文件系统加载、解析、缓存任务定义，并为任务数据填充默认值（如 `execution_mode`）。
*   **[task_queue.py](./task_queue.md)**: **异步任务队列**。定义了信息丰富的 `Tasklet` 数据结构和支持优先级、有界容量（背压）的 `asyncio.TaskQueue`。
*   **[plugin_provider.py](./plugin_provider.md)**: **插件提供者 (适配器)**。为 `resolvelib` 库提供适配器，使其能够理解 Aura 的插件依赖关系。
*   **[builder.py](./builder.md)**: **插件构建器**。当插件没有预构建的 `api.yaml` 时，负责从源码扫描并生成该文件。

## **架构分层与交互流程**

Aura 的核心架构可以被看作一个分层的、以并发为中心设计的系统。

1.  **协调与 API 层**: `Scheduler` 作为最高协调者和 API 门面，其生命周期管理着所有核心后台服务。
2.  **核心服务与生产者层**: `SchedulingService`、`InterruptService` 和 `EventBus` 作为“生产者”，向不同的异步队列中提交 `Tasklet`。`PlanManager` 负责准备好所有可执行的方案。
3.  **并发执行层**: `ExecutionManager` 是所有任务执行的唯一入口和“交通枢纽”。它从 `Scheduler` 接收任务，并根据任务的元数据，安全地调度它们到 `asyncio` 事件循环、线程池或进程池中执行。
4.  **逻辑执行链**: 对于单个任务，`Orchestrator` -> `ExecutionEngine` -> `ActionInjector` 构成了一条清晰的异步执行链，粒度从“方案”到“任务”再到“行为”，逐级细化。
5.  **数据与资源层**: `TaskLoader`, `ContextManager`, `StateStore`, `StatePlanner` 等为执行层提供所需的数据、状态和规划。
6.  **注册与扩展层**: `ServiceRegistry`, `ACTION_REGISTRY`, `MiddlewareManager`, `HookManager` 等作为框架的“结缔组织”，将所有组件松散地耦合在一起，并提供扩展能力。

## **核心架构交互图**

```mermaid
graph TD
    subgraph "UI / API (外部接口)"
        UI_API["UI / API Calls"]
    end

    subgraph "协调与 API 层 (Coordination & API Layer)"
        Scheduler(Scheduler)
        style Scheduler fill:#f8d7da,stroke:#c82333,stroke-width:2px
    end

    subgraph "异步核心与消费者 (Async Core & Consumers)"
        AsyncCore["Scheduler.run() <br> (asyncio.TaskGroup)"]
        MainConsumer["_consume_main_task_queue()"]
        InterruptConsumer["_consume_interrupt_queue()"]
        EventConsumer["_event_worker_loop()"]
    AsyncCore -- "包含" --> MainConsumer
    AsyncCore -- "包含" --> InterruptConsumer
    AsyncCore -- "包含" --> EventConsumer
    end
    
    subgraph "并发执行中心 (Concurrency & Execution Hub)"
        ExecutionManager(ExecutionManager)
        style ExecutionManager fill:#cce5ff,stroke:#004085,stroke-width:2px
    end
    
    subgraph "逻辑执行链 (Logical Execution Chain)"
        Orchestrator(Orchestrator)
        style Orchestrator fill:#fff2cc,stroke:#856404,stroke-width:2px
        Engine(ExecutionEngine)
        ActionInjector(ActionInjector)
        MiddlewareManager(MiddlewareManager)
        ActionFunc["最终 Action 函数"]
    end
    
    subgraph "数据、资源与规划层 (Data, Resource & Planning Layer)"
        PlanManager(PlanManager)
        StatePlanner(StatePlanner)
        ContextManager(ContextManager)
        TaskLoader(TaskLoader)
        StateStore(StateStore)
        FileSystem["文件系统"]
    end
    
    subgraph "注册与扩展层 (Registry & Extension Layer)"
        PluginManager(PluginManager)
        Registries["api.py (全局注册表)<br>ServiceRegistry<br>ACTION_REGISTRY"]
        HookManager(HookManager)
        EventBus(EventBus)
    end
    
    %% --- 生产者 -> 队列 -> 消费者 ---
    SchedulingService(SchedulingService) -- "提交定时任务" --> TaskQueue
    InterruptService(InterruptService) -- "提交中断信号" --> InterruptQueue
    EventBus -- "触发事件任务" --> EventTaskQueue
    
    MainConsumer["_consume_main_task_queue()"] -- "await get()" --> TaskQueue
    InterruptConsumer["_consume_interrupt_queue()"] -- "await get()" --> InterruptQueue
    EventConsumer -- "await get()" --> EventTaskQueue
    
    %% --- 消费者 -> 执行中心 ---
    MainConsumer -- "委托执行" --> ExecutionManager
    InterruptConsumer -- "委托执行" --> ExecutionManager
    EventConsumer -- "委托执行" --> ExecutionManager
    
    %% --- 执行中心 -> 逻辑链 & 规划 ---
    ExecutionManager -- "获取Orchestrator" --> PlanManager
    ExecutionManager -- "进行状态规划" --> StatePlanner
    ExecutionManager -- "1. 启动" --> Orchestrator
    
    %% --- 逻辑链内部流 ---
    Orchestrator -- "2. 运行任务" --> Engine
    Engine -- "3. 运行步骤" --> ActionInjector
    ActionInjector -- "4. 委托执行链" --> MiddlewareManager
    MiddlewareManager -- "5. await 调用" --> ActionFunc
    
    %% --- 数据与注册表依赖 ---
    PlanManager -- "管理" --> Orchestrator
    Orchestrator -- "获取任务数据" --> TaskLoader
    Orchestrator -- "创建上下文" --> ContextManager
    ActionFunc -- "读/写全局状态" --> StateStore
    PluginManager -- "发现/解析" --> FileSystem
    PluginManager -- "注册服务/Action" --> Registries
    ActionInjector -- "注入服务/获取Action" --> Registries
    ActionFunc -- "发布事件" --> EventBus
    HookManager -- "触发钩子" --> ActionFunc


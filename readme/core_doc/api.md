
---

# **核心模块: `api.py`**

## **1. 概述 (Overview)**

`api.py` 是 Aura 框架的**公共应用程序接口 (Public API) 入口**。它定义了所有插件开发者与 Aura 核心交互的“契约”。任何希望为 Aura 扩展新功能（如自定义 Action、Service 或响应框架事件）的开发者，都应该从这个模块导入所需的装饰器和全局注册中心。

此模块的设计遵循**注册中心模式 (Registry Pattern)**，为框架的三个核心可扩展点提供了统一的接口：

1.  **Action API**: 用于定义新的可执行行为，支持同步和异步函数。
2.  **Service API**: 用于定义可复用的、有状态的后端服务，并提供强大的依赖注入功能。
3.  **Hook API**: 用于在框架生命周期的特定节点执行自定义逻辑，并原生支持异步操作。

## **2. 在框架中的角色 (Role in the Framework)**

`api.py` 是框架的“中央枢纽”和“公告板”。在框架加载阶段，`PluginLoader` 会扫描所有插件，并使用此模块中的注册函数（如 `@register_action`, `@register_service`）将插件提供的功能“公告”到全局的注册中心单例（`ACTION_REGISTRY`, `service_registry`, `hook_manager`）。

在任务运行时，框架的核心组件（如 `ExecutionEngine` 和 `ActionInjector`）则会从这些注册中心查询和获取所需的功能来执行任务。

```mermaid
graph TD
    subgraph "加载阶段 (Loading)"
        direction LR
        PluginA["Plugin A <br> (actions.py, services.py)"]
        PluginB["Plugin B <br> (actions.py, hooks.py)"]
        Loader[PluginLoader]
        
        PluginA -- "发现功能" --> Loader
        PluginB -- "发现功能" --> Loader
        Loader -- "调用 @register_action 等" --> API_MODULE
    end

    subgraph "运行阶段 (Runtime)"
        direction LR
        Engine[ExecutionEngine]
        Injector[ActionInjector]
        
        Engine -- "请求执行" --> Injector
        Injector -- "查询/获取" --> API_MODULE
    end

    subgraph "api.py (中央枢纽)"
        API_MODULE{ACTION_REGISTRY<br>service_registry<br>hook_manager}
    end

    style API_MODULE fill:#ccf,stroke:#333,stroke-width:2px
```

## **3. Action API**

Action API 允许开发者将普通的 Python 函数（无论是同步还是异步）封装成可被 `ExecutionEngine` 调用的原子操作。

### **3.1. 核心组件 (Core Components)**

*   **`@register_action(name, ...)`**: 装饰器。将一个函数标记为 Action，并附加元数据。
    *   **参数**: `name` (插件内唯一的行为名), `read_only` (布尔值), `public` (可见性标志)。
*   **`@requires_services(...)`**: 装饰器。用于为 Action 声明其所需的服务依赖，支持通过关键字参数（`db='core/database'`）或位置参数（`'vision'`）进行声明。
*   **`ActionDefinition`**: 数据类。一个内部数据结构，用于封装 Action 函数及其所有元数据。
    *   `is_async`: 一个关键的布尔标志，如果被装饰的函数是 `async def`，此值为 `True`。`ActionInjector` 使用此标志来决定是以异步方式 (`await`) 还是在线程池中执行该函数。
    *   `fqid`: 完全限定ID（Fully Qualified ID），格式为 `plugin_id/action_name`，提供了全局唯一的标识。
*   **`ACTION_REGISTRY`**: 全局单例。`ActionRegistry` 类的实例，负责存储所有已注册的 `ActionDefinition`。
    *   **交互**: `PluginLoader` 在加载时调用其 `register` 方法。`ActionInjector` 在运行时调用其 `get` 方法来查找 Action。
    *   **冲突处理**: `register` 方法在遇到同名 Action 时会发出警告，并以后加载的为准。

## **4. Service API**

Service API 是 Aura 框架的核心部分，它提供了一个完善的**依赖注入 (Dependency Injection)** 和**服务生命周期管理**系统。

### **4.1. 核心组件 (Core Components)**

*   **`@register_service(alias, ...)`**: 装饰器。将一个 Python 类标记为 Service。
    *   **参数**: `alias` (服务的短别名，在整个框架中应具备高辨识度), `public` (可见性标志)。
*   **`ServiceDefinition`**: 数据类。封装了 Service 类及其元数据。关键属性包括：
    *   `fqid`: 全局唯一ID，格式为 `plugin_id/alias`。
    *   `status`: 服务的生命周期状态 (`defined`, `resolving`, `resolved`, `failed`)。
    *   `is_extension`, `parent_fqid`: 用于支持服务继承。
*   **`service_registry`**: 全局单例。`ServiceRegistry` 类的实例，是整个服务系统的核心。

### **4.2. `ServiceRegistry` 的功能与机制**

`ServiceRegistry` 负责服务的完整生命周期，从定义到销毁。

#### **注册 (`register`)**

*   **功能**: 将一个 `ServiceDefinition` 添加到注册中心。
*   **核心逻辑**:
    1.  **冲突检测**: 检查 `fqid` 是否已存在。
    2.  **别名处理与意图声明**: 检查服务的 `alias` 是否已被占用。如果被占用，框架会检查插件的 `plugin.yaml` 中是否明确声明了 `extends` (扩展) 或 `overrides` (覆盖) 意图。
        *   若声明 `extends`，新服务将作为现有服务的**扩展**。
        *   若声明 `overrides`，新服务将**替换**现有服务的别名映射。
        *   若未声明意图但别名冲突，则抛出异常，强制开发者明确其设计。

#### **实例化 (`get_service_instance`)**

*   **功能**: 按需创建并返回服务的单例实例。
*   **核心机制**:
    1.  **懒加载 (Lazy Loading)**: 服务只有在第一次被请求时才会被实例化。
    2.  **单例模式 (Singleton)**: 一旦实例化， 该实例将被缓存，后续所有对该服务的请求都将返回同一个实例。
    3.  **线程安全 (Thread-Safety)**: `ServiceRegistry` 内部使用 `threading.RLock` 来保护其状态，使其所有公共方法（如 `register`, `get_service_instance`）都是线程安全的。这确保了在多线程环境（如 UI 线程与后台任务线程并发访问）或从异步代码调用时，注册中心的状态保持一致。
    4.  **循环依赖检测**: 通过 `resolution_chain` 列表跟踪实例化链，如果发现循环依赖（如服务 A 依赖服务 B，服务 B 又依赖服务 A），则会抛出 `RecursionError`，防止无限递归。
    5.  **自动依赖注入 (`_resolve_constructor_dependencies`)**: 这是框架实现“约定优于配置”的关键。当实例化一个服务时，它会自动解析其构造函数 (`__init__`) 的参数，并注入所需的其他服务实例。解析顺序为：
        *   **优先按类型注解**: 如果参数有类型提示，且该类型对应一个已注册的服务，则注入该服务。
        *   **回退到参数名**: 如果类型注解无法解析，则将参数名本身作为服务别名去查找并注入。
    6.  **服务继承实现**: 当实例化一个扩展服务 (`is_extension=True`) 时，它会先实例化父服务。然后，它将父服务实例通过 `InheritanceProxy` 与子服务实例组合起来。`InheritanceProxy` 会优先使用子服务的方法和属性，如果子服务中不存在，则回退到父服务，从而实现方法的无缝继承和覆盖。

#### **服务生命周期状态图**

```mermaid
stateDiagram-v2
    [*] --> defined: register()
    defined --> resolving: get_service_instance()
    resolving --> resolved: 实例化成功
    resolving --> failed: 实例化失败
    resolved --> resolved: 后续 get_service_instance()
    failed --> failed: 后续 get_service_instance()
```

## **5. Hook API**

Hook API 提供了一个异步的发布-订阅系统，允许插件在框架运行的关键时刻（如“任务开始前”、“任务结束后”）注入自己的逻辑。

### **5.1. 核心组件 (Core Components)**

*   **`@register_hook(name)`**: 装饰器。将一个函数注册为特定事件钩子的监听器。
    *   **参数**: `name` (钩子的名称，如 `before_task_run`)。
*   **`HookManager`**: 一个支持异步的事件分发器。
    *   `register(hook_name, func)`: 将函数 `func` 添加到 `hook_name` 事件的监听者列表中。
    *   `trigger(hook_name, ...)`: **异步地**触发一个钩子事件。它会收集所有注册到该事件的监听函数（无论是同步还是异步），并通过 `asyncio.gather` 并发执行它们。
    *   `_execute_hook`: 内部辅助方法，用于智能执行单个钩子函数。如果函数是 `async def`，则直接 `await`；如果是普通 `def` 函数，则通过 `loop.run_in_executor` 在线程池中运行，避免阻塞事件循环。
*   **`hook_manager`**: 全局单例。`HookManager` 类的实例。

### **5.2. 异步执行模型**

`HookManager` 的核心优势在于其对异步的原生支持。当 `trigger` 被调用时，所有监听该钩子的函数都会被并发调度。这意味着多个耗时的 I/O 操作（如在 `on_task_complete` 钩子中进行网络通知和写日志文件）可以并行执行，而不会相互等待，显著提高了事件处理的效率。

## **6. 总结 (Summary)**

`api.py` 是 Aura 框架可扩展性的基石。它通过提供一组清晰、一致且支持异步的装饰器和全局注册中心，为插件开发者定义了一个稳定的开发接口。其内部实现，特别是 `ServiceRegistry` 中复杂的依赖注入、生命周期管理和继承/覆盖逻辑，以及 `HookManager` 和 `ActionDefinition` 对异步操作的无缝支持，是 Aura 框架强大功能、灵活性和高性能的核心体现。任何对 Aura 进行深度定制或插件开发的工程师，都必须首先理解并掌握此模块提供的公共 API。




# 文件: `plans/aura_base/services/config_service.py`

## 1. 核心目的

该文件定义了 `ConfigService`，一个用于在整个 Aura 框架中进行**分层配置管理**的核心服务。它的主要职责是提供一个统一的接口，让框架的其他部分（特别是 Actions 和 Services）能够方便地获取配置项，同时将配置的来源（环境变量、全局配置文件、方案包内部配置文件）与消费者解耦。

这个服务的最新版本（v4.0）解决了一个关键的**配置隔离**问题，确保在一个多 Plan 的复杂项目中，不同 Plan 的配置不会相互冲突或覆盖。

## 2. 关键组件与功能

*   **`current_plan_name: ContextVar`**: 这是一个全局的**上下文变量**，是实现配置隔离的核心机制。在任务执行期间，`Orchestrator` (任务编排器) 会将当前正在执行的 Plan 的名称设置到这个变量中。由于 `ContextVar` 的特性，这个值是与当前的异步任务上下文绑定的，因此即使有多个任务在并发执行，每个任务也能正确地获取到自己所属的 Plan 名称。

*   **`ConfigService`**:
    *   **`__init__()`**: 初始化服务。它创建了三个独立的字典来存储不同层级的配置：
        1.  `_env_config`: 存储来自环境变量（`AURA_...`）和 `.env` 文件的配置，具有**最高优先级**。
        2.  `_global_config`: 存储来自项目根目录下 `config.yaml` 文件的全局配置，优先级居中。
        3.  `_plan_configs`: 这是一个**字典的字典**，用于按 Plan 名称**隔离存储**每个 Plan 包内部的 `config.yaml` 文件内容。这是 v4.0 的关键改动。
    *   **`load_environment_configs(base_path)`**: 在框架启动时调用，负责加载环境变量和全局 `config.yaml` 文件。
    *   **`register_plan_config(plan_name, config_data)`**: 当 `PlanManager` 加载每个 Plan 时，会调用此方法将该 Plan 的 `config.yaml` 内容注册到 `_plan_configs` 字典中，以 `plan_name` 作为键。
    *   **`get(key_path, default=None)`**: 这是服务最核心的公共接口。它负责根据给定的键路径（例如 `'app.target_window_title'`）查找并返回值。

## 3. 核心逻辑解析

`ConfigService` v4.0 的核心逻辑在于其 `get` 方法如何利用 `ContextVar` 和 `ChainMap` 实现**动态的、上下文感知的配置查找链**。

当一个 Action 或 Service 调用 `config.get('some.key')` 时，`get` 方法内部的执行流程如下：

1.  **感知当前上下文**: 它首先调用 `current_plan_name.get()`。`ContextVar` 会自动返回在当前异步执行上下文中设置的 Plan 名称。例如，如果正在执行 `my_plan/my_task`，这里就会返回 `'my_plan'`。如果不在任何任务执行上下文中（例如在框架启动阶段），它会返回默认值 `None`。

2.  **动态构建查找链**: 接着，它会**即时地**创建一个查找列表 `maps_to_chain`。这个列表的顺序至关重要，因为它定义了配置的覆盖优先级：
    *   它首先将 `self._env_config` 和 `self._global_config` 添加到列表中。
    *   然后，它检查从 `ContextVar` 获取到的 `plan_name` 是否有效，以及该 Plan 是否有注册过配置。如果都满足，它**才**会将该特定 Plan 的配置字典 `self._plan_configs[plan_name]` 添加到列表中。

3.  **创建 `ChainMap` 并查找**: 它使用 `collections.ChainMap(*maps_to_chain)` 来创建一个 `ChainMap` 对象。`ChainMap` 是一个非常高效的数据结构，它能将多个字典链接成一个单一的可查找视图，而无需进行实际的数据合并。当在 `ChainMap` 中查找一个键时，它会按顺序（也就是我们定义的优先级顺序）在每个字典中查找，并返回第一个找到的值。

4.  **返回结果**: 最后，它在 `ChainMap` 中查找用户请求的 `key_path`。

通过这种设计，`ConfigService` 实现了完美的配置隔离。例如，当 `plan_A` 中的一个 Action 调用 `config.get('database.host')` 时，查找链将是 `[env, global, plan_A_config]`；而当 `plan_B` 中的 Action 调用相同的代码时，查找链会自动变为 `[env, global, plan_B_config]`。这确保了每个 Plan 都能优先获取自己的配置，同时又能回退到全局配置或被环境变量覆盖，实现了强大、灵活且无冲突的配置管理。
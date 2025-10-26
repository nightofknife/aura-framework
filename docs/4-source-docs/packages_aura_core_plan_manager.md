# 文件: `packages/aura_core/plan_manager.py`

## 1. 核心目的

该文件的核心职责是作为 Aura 框架中所有**自动化方案（Plans）的顶层管理器**。它扮演着“总指挥”的角色，负责在框架启动时**发现、加载、并初始化**所有定义好的 Plan。

`PlanManager` 的主要工作是为每一个 Plan 创建并配置其所需的专属执行资源，特别是 `Orchestrator`（负责执行任务）和 `StatePlanner`（负责状态管理和规划）。它确保了每个 Plan 都是一个独立的、功能完备的单元，随时可以被 `Scheduler` 调用来执行任务。

## 2. 关键类与函数

*   **`PlanManager` (Class)**:
    *   **作用**: 这是该文件的核心类，封装了所有与 Plan 管理相关的功能。
    *   **`plugin_manager` (Attribute)**: 一个 `PluginManager` 的实例。`PlanManager` **委托** `PluginManager` 去实际地扫描和加载磁盘上的插件目录。这体现了**关注点分离**的设计原则：`PluginManager` 负责“加载”，而 `PlanManager` 负责在加载之后进行“业务层面的初始化”。
    *   **`plans` (Attribute)**: 一个字典，用于存储初始化完成的 Plan。它的键是 Plan 的名称（字符串），值是为该 Plan 创建的 `Orchestrator` 实例。这个字典是框架其他部分（如 `Scheduler`）访问特定 Plan 执行能力的入口。

    *   **`__init__(base_dir, pause_event)`**:
        *   **作用**: 初始化 `PlanManager`。它接收项目的基础目录 `base_dir` 以便知道从哪里开始扫描插件，以及一个全局的 `pause_event`，这个事件将被传递给所有创建的 `Orchestrator`，从而实现对所有任务的全局暂停和恢复控制。

    *   **`initialize()`**:
        *   **作用**: 这是 `PlanManager` 最核心的方法，执行所有 Plan 的完整初始化流程。它是有序地、一步步地构建起整个 Plan 生态。

    *   **`get_plan(plan_name)`**:
        *   **作用**: 一个简单的访问器方法，允许外部代码根据 Plan 的名称从 `plans` 字典中安全地获取对应的 `Orchestrator` 实例。

    *   **`list_plans()`**:
        *   **作用**: 提供所有已加载和初始化的 Plan 的名称列表，常用于 API 或 UI 展示。

## 3. 核心逻辑解析

`PlanManager.initialize()` 方法的逻辑是理解该模块如何工作的关键。它并非简单地循环创建对象，而是采用了一种**分步构建和依赖回填**的策略，以优雅地解决 `Orchestrator` 和 `StatePlanner` 之间的循环依赖问题。

其核心流程如下：

1.  **加载所有插件**:
    *   `self.plugin_manager.load_all_plugins()`: 初始化流程的第一步是将任务委托给 `PluginManager`。`PluginManager` 会扫描 `plans` 目录，找到所有合法的插件（包含 `plugin.yaml` 的目录），解析它们的元数据，并将结果存储在自己的 `plugin_registry` 中。

2.  **遍历并筛选 Plan**:
    *   `for plugin_def in self.plugin_manager.plugin_registry.values():`: 遍历所有已加载的插件。
    *   `if plugin_def.plugin_type == 'plan':`: 它只关心那些在 `plugin.yaml` 中被明确标识为 `type: plan` 的插件，忽略其他类型的插件（如 `library`）。

3.  **为每个 Plan 创建核心资源（两步法）**:
    *   **步骤 1: 创建 `Orchestrator` 实例**:
        *   `orchestrator = Orchestrator(...)`: 对于每个 Plan，首先创建一个 `Orchestrator` 实例。这是 Plan 的执行核心。
        *   **关键点**: 在这一步，传递给 `Orchestrator` 构造函数的 `state_planner` 参数被设置为 `None`。这是因为 `StatePlanner` 自身在创建时需要一个 `Orchestrator` 实例作为参数，如果同时创建会导致死锁。

    *   **步骤 2: 检查并创建 `StatePlanner` (可选)**:
        *   `state_map_path = plan_path / 'states_map.yaml'`: 接着，它会检查该 Plan 的目录下是否存在一个名为 `states_map.yaml` 的文件。
        *   如果该文件存在，意味着这个 Plan 是一个**基于状态的 Plan**。
        *   `state_planner_instance = StatePlanner(state_map, orchestrator)`: 它会加载和解析 `states_map.yaml` 文件，然后用解析出的状态地图（`state_map`）和**刚刚在步骤 1 中创建的 `orchestrator` 实例**来创建一个 `StatePlanner`。这就解决了 `StatePlanner` 对 `Orchestrator` 的依赖。

    *   **步骤 3: 依赖回填**:
        *   `orchestrator.state_planner = state_planner_instance`: 这是整个逻辑闭环的关键一步。将在步骤 2 中创建的 `state_planner_instance` **回填**到步骤 1 创建的 `orchestrator` 对象的 `state_planner` 属性中。
        *   至此，`Orchestrator` 拥有了 `StatePlanner` 的引用，`StatePlanner` 也拥有了 `Orchestrator` 的引用，两者之间的双向关系被完美建立，而没有在构造函数中产生循环依赖的问题。

这个“先创建、再回填”的初始化策略，清晰地展示了 `PlanManager` 作为顶层协调者的作用，它精心编排了各个组件的实例化顺序，确保了整个系统的稳定和正确启动。
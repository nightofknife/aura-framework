
---

### **Aura 自动化框架 - 架构概览 (v5.2 - 修正版)**

#### **1. 核心设计理念**

*   **服务化 (Service-Oriented)**: 框架的核心功能（如配置、状态管理、事件总线）和扩展功能（如应用控制、视觉识别）都被封装为可独立测试、可热插拔的**服务 (Services)**。
*   **依赖注入 (Dependency Injection)**: 框架的“动词”——**行为 (Actions)**——通过声明式的方式获取所需的服务实例，无需手动管理服务生命周期，实现了极致的解耦。
*   **插件化一切 (Plugin-based)**: 所有的代码（包括框架自带的核心功能）都通过统一的**插件包 (Packages)**机制进行组织和加载。一个插件包可以贡献服务、行为、钩子等多种能力。
*   **配置驱动 (Configuration-Driven)**: 通过结构化的 YAML 文件来定义任务流程 (`tasks/*.yaml`)、调度规则 (`schedule.yaml`) 和中断处理 (`interrupts.yaml`)，将业务逻辑与底层代码彻底分离。

---

### **2. 框架目录结构与文件职责**

```
Aura/
│
├── plans/                      # 【插件区】存放所有方案包和能力包
│   │
│   ├── aura_base/              # 【核心能力包】框架提供的基础能力 (应用控制, 视觉等)
│   │   ├── plugin.yaml
│   │   ├── services/
│   │   │   ├── app_provider_service.py
│   │   │   └── screen_service.py
│   │   └── actions/
│   │       └── app_actions.py
│   │
│   └── MyTestPlan/             # 【用户方案包】示例：一个针对特定应用的方案
│       ├── plugin.yaml         # 【必需】插件定义文件，可声明对 aura_base 的依赖
│       ├── config.yaml         # (可选) 方案的静态配置文件
│       ├── schedule.yaml       # (可选) 定义此方案的自动化调度规则
│       ├── interrupts.yaml     # (可选) 定义此方案的中断处理规则
│       ├── tasks/              # (可选) 存放该方案的所有任务YAML文件
│       │   └── daily.yaml
│       └── ...                 # (其他可选目录: services, actions, resources)
│
└── packages/                   # 【框架核心区】存放框架的核心运行时
    │
    └── aura_core/              # 框架的核心运行时，提供最基础的插件和执行机制
        ├── plugin_manager.py
        ├── scheduler.py        # 框架总指挥和门面
        ├── execution_manager.py
        ├── engine.py           # 任务YAML解释器
        ├── orchestrator.py     # 单个方案包的运行时实例
        └── ...                 # 其他核心组件 (Context, API, Services...)

```

---

### **3. 各模块如何联动 (The Data Flow)**

这个流程基本保持不变，但对插件加载的描述更准确了。

1.  **启动与加载 (Scheduler)**:
    *   用户启动框架，`Scheduler` 被实例化。
    *   `Scheduler` 命令 `PluginManager` 开始工作。
    *   `PluginManager` 扫描 `plans/` 和 `packages/` 目录，找到所有 `plugin.yaml` 文件，解析它们的身份和依赖关系（例如，`MyTestPlan` 依赖 `aura_base`）。
    *   `PluginManager` 根据依赖关系，按正确的顺序加载所有插件包（例如，先加载 `aura_base`，再加载 `MyTestPlan`）。
        *   加载过程中，每个包的 `services/` 和 `actions/` 目录中的服务和行为被发现并注册到中央的 `ServiceRegistry` 和 `ActionRegistry`。
        *   对于方案包，`PluginManager` 会为其创建一个专属的 `Orchestrator` 实例。
    *   `Scheduler` 加载所有方案的 `schedule.yaml` 和 `interrupts.yaml`，并启动后台的调度和中断监控服务。

2.  **用户请求执行任务**:
    *   用户在UI上点击运行 "MyTestPlan" 下的 "test/draw_star/main" 任务。
    *   UI 调用 `Scheduler.run_ad_hoc_task(plan_name='MyTestPlan', task_name='test/draw_star/main')`。

3.  **任务派发 (Scheduler -> ExecutionManager)**:
    *   `Scheduler` 创建一个 `Tasklet` 并放入主任务队列。
    *   `Scheduler` 的主循环将任务交给 `ExecutionManager`。

4.  **任务执行准备 (ExecutionManager -> Orchestrator)**:
    *   `ExecutionManager` 解析任务ID，找到 `MyTestPlan` 对应的 `Orchestrator` 实例。
    *   调用 `orchestrator.execute_task('test/draw_star/main')`。

5.  **任务加载与执行 (Orchestrator -> TaskLoader -> Engine)**:
    *   `Orchestrator` -> `TaskLoader` 加载 `tasks/test/draw_star.yaml` 文件中的 `main` 任务。
    *   `Orchestrator` 创建 `Context` 和 `ExecutionEngine`，并调用 `engine.run()`。

6.  **单步执行 (Engine -> ActionInjector)**:
    *   `Engine` 将 `action: move_to` 委托给 `ActionInjector`。
    *   `ActionInjector` 在 `ActionRegistry` 中查找到由 `aura_base` 包注册的 `move_to` 行为。
    *   它分析该行为需要注入 `app: AppProviderService`。
    *   `ActionInjector` 从 `ServiceRegistry` 请求一个由 `aura_base` 注册的 `AppProviderService` 实例。
    *   它将服务实例和YAML中的 `params` 一起传给 `move_to` 函数并调用。

7.  **行为内部逻辑**:
    *   `move_to` 函数内部调用 `app.move_to()` 方法。

8.  **循环与结束**:
    *   `Engine` 根据结果继续执行或中止任务。

---

### **4. 当前框架状态**

**已完成的关键特性 (√):**
*   **完整的插件系统**: 基于 `plugin.yaml` 的依赖解析和按序加载。
*   **服务化与依赖注入**: `ServiceRegistry` 和 `ActionInjector` 配合，实现了干净的 `action` 编写体验。
*   **强大的执行引擎**: 支持 `if/for/while/go_step/go_task` 等复杂的流程控制。
*   **分体式后台服务**: `SchedulingService` 和 `InterruptService` 作为独立的后台线程运行。
*   **健壮的任务加载**: `TaskLoader` 支持灵活的多任务文件结构，并带有缓存机制。
*   **清晰的门面API**: `Scheduler` 类为外部调用者提供了一套稳定、高级的接口。
。


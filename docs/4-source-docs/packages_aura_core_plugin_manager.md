# 文件: `packages/aura_core/plugin_manager.py`

## 1. 核心目的

该文件的核心职责是作为 Aura 框架的**插件管理器**。它是框架模块化和可扩展架构的基石。`PluginManager` 负责在应用启动时，完成一个至关重要的、分为三个阶段的引导流程：

1.  **发现 (Discovery)**: 扫描项目中的 `plans` 和 `packages` 目录，找到所有包含 `plugin.yaml` 元数据文件的插件。
2.  **解析与排序 (Resolution & Sorting)**: 读取每个插件的 `plugin.yaml`，理解其元数据（特别是依赖关系），然后构建一个依赖关系图，并进行**拓扑排序**以确定一个**绝对安全**的加载顺序。
3.  **加载 (Loading)**: 按照排定的顺序，逐一加载每个插件，将其暴露的 Services, Actions, 和 Hooks 注册到 Aura 框架的全局注册表中，使其对框架的其他部分可用。

简而言之，`PluginManager` 确保了无论插件有多少、依赖关系多复杂，它们都能以正确的顺序被加载，从而保证整个系统的稳定启动和运行。

## 2. 关键类与函数

*   **`PluginManager` (Class)**:
    *   **作用**: 封装了插件管理的所有逻辑。
    *   **`plugin_registry` (Attribute)**: 一个字典，用于存储所有被发现和解析后的 `PluginDefinition` 对象。这是进行依赖解析和排序的数据基础。

    *   **`load_all_plugins()`**:
        *   **作用**: **核心公共入口方法**。它按顺序编排了整个插件加载流程（清理 -> 发现 -> 排序 -> 加载），是应用启动时必须调用的关键函数。

    *   **`_clear_plugin_registries()`**:
        *   **作用**: 一个内部的“重置”函数。在加载开始前，它会清空所有旧的 Service, Action, 和 Hook 注册信息，确保每次启动都是一个干净的状态，这对于热重载功能至关重要。

    *   **`_discover_and_parse_plugins()`**:
        *   **作用**: 实现加载流程的**阶段一**。它递归地扫描插件目录，读取 `plugin.yaml` 的内容，并将其转换为结构化的 `PluginDefinition` 对象存入 `plugin_registry`。

    *   **`_resolve_dependencies_and_sort()`**:
        *   **作用**: 实现加载流程的**阶段二**。这是技术上最复杂的部分，它利用图论算法来解决插件间的依赖关系。

    *   **`_load_plugins_in_order(load_order)`**:
        *   **作用**: 实现加载流程的**阶段三**。它接收排序好的插件 ID 列表，并按顺序逐一加载。

    *   **`_load_package_from_api_file(...)`**:
        *   **作用**: 负责从每个插件的 `api.yaml` 文件中读取其暴露的 Services 和 Actions 的元数据，并通过 Python 的动态导入机制（`importlib`）将相应的类和函数加载到内存中，并注册到全局的 `service_registry` 和 `ACTION_REGISTRY`。

    *   **`_load_hooks_for_package(...)`**:
        *   **作用**: 专门处理插件的钩子。它会检查插件目录下是否存在 `hooks.py` 文件，如果存在，则加载其中的钩子函数并注册到 `hook_manager`。

    *   **`_lazy_load_module(file_path)`**:
        *   **作用**: 一个高效的模块加载工具函数。它使用 `importlib` 来根据文件路径动态加载 Python 模块，并会缓存已加载的模块，避免重复加载。

## 3. 核心逻辑解析

`PluginManager` 的核心在于其 `load_all_plugins` 方法所编排的三阶段加载流程，其中**阶段二：依赖解析与排序 (`_resolve_dependencies_and_sort`)** 是保证系统稳定性的关键。

这个过程的逻辑如下：

1.  **构建依赖图**:
    *   `graph = {pid: set(pdef.dependencies.keys()) ...}`: 首先，它会遍历 `plugin_registry` 中的所有插件定义，并构建一个字典来表示依赖关系图。这个字典的**键**是插件的 ID（如 `aura_base`），**值**是一个集合，包含了该插件所依赖的其他插件的 ID。例如 `{'my_plan': {'aura_base', 'aura_ocr'}}`。

2.  **进行拓扑排序**:
    *   `ts = TopologicalSorter(graph)`: 它使用 Python 标准库 `graphlib` 中的 `TopologicalSorter` 类。这是一个专门用于处理有向无环图（DAG）的强大工具。`PluginManager` 将上一步构建的依赖图传给它。
    *   `return list(ts.static_order())`: `static_order()` 方法会返回一个线性的插件 ID 列表。这个列表的顺序经过精心安排，**确保对于列表中的任何一个插件，它所依赖的所有其他插件都排在它的前面**。这就是“拓扑序”。

3.  **处理循环依赖 (健壮性)**:
    *   `try...except CycleError as e:`: 拓扑排序有一个前提，就是图中不能存在循环依赖（例如，A 依赖 B，同时 B 又依赖 A）。如果 `TopologicalSorter` 在处理图时发现了这种循环，它会抛出 `CycleError` 异常。
    *   `PluginManager` 精心捕获了这个异常，并会从中提取出导致循环的插件路径（`" -> ".join(e.args[1])`），然后以一个清晰、明确的错误信息（`"检测到插件间的循环依赖，无法启动: a -> b -> a"`）来中断应用的启动。**这是一种故障快速失败（Fail-fast）的设计**，它避免了在运行时因无法解决的依赖关系而导致各种难以预料的、隐蔽的错误。

通过这个严谨的、基于图论的排序过程，`PluginManager` 确保了后续的加载阶段（`_load_plugins_in_order`）能够在一个绝对安全和可预测的顺序下进行。当加载 `my_plan` 时，可以百分之百地确定 `aura_base` 和 `aura_ocr` 已经加载完毕，它们提供的所有服务和功能都已在注册表中准备就绪，从而彻底杜绝了“依赖未找到”这类常见的运行时错误。
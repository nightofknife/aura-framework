# 文件: `packages/aura_core/plugin_definition.py`

## 1. 核心目的

该文件的核心目的是定义 Aura 框架中**插件（Plugin）的数据模型**。它提供了一组 `dataclass` 类，用于以结构化的、面向对象的方式来表示从每个插件的 `plugin.yaml` 配置文件中解析出来的所有元数据和依赖关系。

这个文件本身不执行任何动态的加载或扫描逻辑，它纯粹是一个**静态的数据结构定义**，为 `PluginManager` 等其他核心组件提供了一个清晰、可靠的数据模型来使用。

## 2. 关键组件与功能

*   **`Dependency` (dataclass)**:
    *   **目的**: 专门用于表示插件之间的一种特定依赖关系，即**扩展（extends）**。
    *   **属性**:
        *   `service`: 被扩展的目标服务的别名。
        *   `from_plugin`: 提供该目标服务的插件的规范 ID（`author/name`）。
    *   **场景**: 当一个插件A需要向另一个插件B提供的某个服务中添加或修改功能时，就会在 `plugin.yaml` 中定义一个 `extends` 依赖，这个依赖就会被解析成一个 `Dependency` 对象。

*   **`PluginDefinition` (dataclass)**:
    *   **目的**: 这是该文件的核心，代表了一个**插件的完整描述**。它将 `plugin.yaml` 中所有可能存在的字段都映射为强类型的类属性。
    *   **属性分类**:
        *   **身份信息**: `author`, `name` (插件的作者和名称)。
        *   **元数据**: `version`, `description`, `homepage` (版本、描述、主页URL)。
        *   **结构信息**: `path` (插件在文件系统中的 `Path` 对象)，`plugin_type` (插件类型，如 `'plan'` 或 `'library'`)。
        *   **依赖与扩展**:
            *   `dependencies`: 一个字典，表示该插件对外部 Python 包的依赖（类似于 `requirements.txt`）。
            *   `extends`: 一个 `Dependency` 对象的列表，定义了该插件扩展了哪些其他服务。
            *   `overrides`: 一个字符串列表，定义了该插件完全**覆盖**了哪些其他服务的 FQID（完全限定ID）。
    *   **`canonical_id` (property)**:
        *   这是一个计算属性，它根据 `author` 和 `name` 动态生成插件的**规范ID**，格式为 `author/name`。这个 ID 是插件在整个 Aura 框架中的**唯一标识符**，用于解决依赖、注册服务和动作。
    *   **`from_yaml(cls, data, ...)` (classmethod)**:
        *   这是一个**工厂方法**，是连接 YAML 文件和 `PluginDefinition` 对象的桥梁。它接收一个从 `plugin.yaml` 文件解析出来的字典 `data`，然后负责从中提取所有字段，进行必要的校验（例如，确保 `author` 和 `name` 存在），并构造出一个完整的 `PluginDefinition` 实例。这种设计将数据解析和对象创建的逻辑封装在一起，使得 `PluginManager` 的代码更加清晰。

## 3. 核心逻辑解析

该文件的核心逻辑在于它如何通过 `dataclass` 和工厂模式，将**非结构化的 YAML 数据**转化为**结构化的、可预测的 Python 对象**。

以 `PluginDefinition.from_yaml` 工厂方法为例，其处理流程清晰地展示了这一点：

1.  **接收原始数据**: `PluginManager` 在扫描文件系统时，会找到一个 `plugin.yaml` 文件，使用 `pyyaml` 库将其加载成一个 Python 字典，然后将这个字典传递给 `PluginDefinition.from_yaml` 方法。

2.  **安全的数据提取**: 方法内部不直接访问字典的键，而是使用 `.get(key, default_value)` 的方式来安全地提取数据。例如，`version = identity_data.get('version', '0.0.0')` 确保了即使 YAML 文件中没有 `version` 字段，程序也能获得一个合理的默认值 `'0.0.0'`，而不会因为 `KeyError` 而崩溃。

3.  **结构校验**: 方法会对关键数据进行校验。例如，它会检查 `identity` 字段是否存在且为一个字典，并确保 `author` 和 `name` 两个子字段是存在的。如果校验失败，它会 `raise ValueError` 并提供清晰的错误信息，指出哪个插件的配置文件有问题，这对于开发者排错至关重要。

4.  **嵌套对象创建**: 当处理 `extends` 字段时，它会遍历列表中的每一项，并为每一项创建一个 `Dependency` 对象，最终将这些对象收集到一个列表中。这体现了**组合**的设计思想，`PluginDefinition` 对象内部包含了 `Dependency` 对象。

5.  **实例化**: 最后，它调用 `cls(...)` (即 `PluginDefinition(...)`) 来实例化主对象，将所有提取和处理过的数据作为参数传入。

通过这种方式，`plugin_definition.py` 成功地在框架的数据层面建立起了一道**防线**。无论 `plugin.yaml` 文件的内容多么不规范（例如，缺少字段、字段类型错误），`from_yaml` 方法都能在早期阶段捕捉到这些问题，并将其转化为结构清晰、类型正确的 `PluginDefinition` 对象。这使得框架的其他部分可以放心地使用这些对象，而无需在各处重复进行数据校验，大大提高了代码的健壮性和可维护性。
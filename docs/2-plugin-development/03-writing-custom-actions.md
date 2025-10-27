# 3. 编写自定义 Actions

Action 是 Aura 任务中的基本执行单元。本教程将详细讲解如何使用 Python 编写一个自定义 Action，并将其集成到 Aura 框架中。

## 1. Action 的基本结构

一个 Action 本质上是一个被 `@action` 装饰器修饰的 Python 函数。这个函数需要放在你的 Plan 的 `actions/` 目录下。

让我们来看一个完整的例子。假设我们正在创建一个名为 `string_utils` 的 Plan，我们想在其中添加一个 Action，用于拼接两个字符串。

**文件路径:** `plans/string_utils/actions/string_actions.py`

```python
import logging
from aura_core.actions import action # 1. 导入 @action 装饰器

# 2. 获取一个 logger 实例，用于在 Action 内部打印日志
logger = logging.getLogger(__name__)

# 3. 使用 @action 装饰器来定义一个 Action
@action
def concat_strings(first_string: str, second_string: str) -> str:
    """
    拼接两个字符串并返回结果。

    :param first_string: 第一个字符串。
    :param second_string: 第二个字符串，将拼接到第一个的末尾。
    :return: 拼接后的新字符串。
    """

    # 4. 在 Action 内部打印日志
    logger.info(f"正在拼接 '{first_string}' 和 '{second_string}'...")

    # 5. 实现 Action 的核心逻辑
    result = f"{first_string}{second_string}"

    # 6. 返回结果
    return result

```

在 YAML 任务文件中，你可以这样调用这个 Action：

```yaml
steps:
  - name: "combine_names"
    action: "string_utils.concat_strings" # Action 的 ID 是 <plan_name>.<function_name>
    params:
      first_string: "Hello, "
      second_string: "Aura!"
```

## 2. 关键点解析

### 2.1. `@action` 装饰器

`@action` 是定义一个 Action 的唯一方式。Aura 的 Plan 管理器会自动扫描所有 Plan 的 `actions/` 目录，并注册所有被此装饰器标记的函数。

你可以向 `@action` 装饰器传递一个可选的 `name` 参数来指定 Action 的名称。如果不提供，则函数名将作为其名称。

```python
@action(name="combine")
def concat_strings(first_string: str, second_string: str) -> str:
    # ...
```

在 YAML 中调用时，就需要使用 `string_utils.combine`。

### 2.2. 参数和类型提示

Action 的参数直接从 YAML 任务文件的 `params` 块中获取。我们**强烈推荐**为所有参数和返回值使用 Python 的类型提示（Type Hinting）。

*   **参数映射**: `params` 中的 key 会按名称匹配到函数的参数。
*   **类型校验**: Aura 会在执行前尝试根据你的类型提示对输入参数进行校验和转换，这能有效避免许多运行时错误。
*   **文档清晰**: 类型提示让你的 Action 更易于理解和使用。

### 2.3. 访问日志 (Logger)

在 Action 内部打印日志是调试和监控任务执行的重要手段。

你应该始终使用 Python 内置的 `logging` 模块。通过 `logging.getLogger(__name__)` 获取一个 logger 实例，它会自动与 Aura 的主日志系统集成。你在 Action 中打印的任何日志，都会根据其级别（`INFO`, `WARNING`, `ERROR` 等）显示在 Web UI 的任务执行日志中。

### 2.4. 返回值

Action 可以返回任何 Python 对象。这个返回值可以被任务中的后续步骤通过 `{{ steps.step_name.output }}` 语法来引用。

如果一个 Action 没有明确的 `return` 语句，它将默认返回 `None`。

## 3. 完整的 Plan 示例

为了让你更好地理解，这里提供一个包含此 Action 的、可运行的 `string_utils` Plan 的完整目录结构和文件内容。

**目录结构:**
```
plans/
└── string_utils/
    ├── __init__.py
    └── actions/
        ├── __init__.py
        └── string_actions.py
```

**`plans/string_utils/__init__.py`**: (空文件)

**`plans/string_utils/actions/__init__.py`**: (空文件)

**`plans/string_utils/actions/string_actions.py`**: (内容如上文所示)

将这个 `string_utils` 目录放入你的 `plans/` 文件夹并重启 Aura，`string_utils.concat_strings` 这个 Action 就会立即可用。

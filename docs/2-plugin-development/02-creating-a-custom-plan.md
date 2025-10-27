# 2. 创建一个自定义 Plan

创建一个新的 Plan 是扩展 Aura 功能的第一步。一个组织良好的 Plan 目录结构不仅能让 Aura 正确加载你的功能，也能让其他开发者更容易理解和维护你的代码。

## 1. Plan 的标准目录结构

Aura 会自动扫描 `plans/` 目录下的所有子目录，并将每一个子目录识别为一个独立的 Plan。Plan 的名称就是其目录的名称。

以下是一个推荐的、功能完备的 Plan 目录结构：

```
plans/
└── my_custom_plan/
    ├── __init__.py
    ├── actions/
    │   ├── __init__.py
    │   └── my_actions.py
    ├── services/
    │   ├── __init__.py
    │   └── my_services.py
    ├── tasks/
    │   └── my_task.yaml
    ├── config.yaml
    └── schedule.yaml
```

让我们来详细解释每个文件和目录的作用：

*   **`my_custom_plan/`**: Plan 的根目录，其名称 `my_custom_plan` 将作为这个 Plan 的唯一标识符。

*   **`__init__.py`**: 一个空的 Python 文件，它告诉 Aura 这个目录是一个 Python 包。这对于后续导入 `actions` 和 `services` 中的代码至关重要。

*   **`actions/`**: 这个目录用于存放所有与该 Plan 相关的 Python 代码，其中定义了具体的 Actions。
    *   `__init__.py`: 同样，将 `actions` 目录标记为一个 Python 包。
    *   `my_actions.py`: 你编写 Action 函数的具体文件。你可以根据功能将 Actions 分散在多个 `.py` 文件中。

*   **`services/`**: 这个目录用于存放该 Plan 的 Service 类。
    *   `__init__.py`: 将 `services` 目录标记为一个 Python 包。
    *   `my_services.py`: 你编写 Service 类的具体文件。

*   **`tasks/`**: 这个目录存放所有预定义的 YAML 任务文件。当 Plan 加载时，这里的任务会自动出现在 Web UI 中。
    *   `my_task.yaml`: 一个 YAML 任务文件。

*   **`config.yaml`** (可选): Plan 的配置文件。你可以在这里定义一些该 Plan 特有的配置项，例如 API 密钥、主机名等。在 Action 中，你可以通过特定的方式来读取这些配置。

*   **`schedule.yaml`** (可选): 任务调度文件。你可以在这里定义一个或多个定时触发的任务，Aura 的调度器会自动根据这里定义的 cron 表达式来执行相应的任务。

## 2. 最小化的 Plan 结构

对于一个非常简单的 Plan，你并不需要创建所有的目录。例如，如果你的 Plan 只包含一两个 Action，且没有任何 Service 或预定义任务，那么一个最小化的结构可能如下：

```
plans/
└── my_simple_plan/
    ├── __init__.py
    └── actions/
        └── __init__.py
        └── basic_actions.py
```

## 3. 重要提示

*   **命名约定**: Plan 的名称（即目录名）应该是唯一的，并且最好使用小写字母和下划线 (`snake_case`) 的命名方式。
*   **自动加载**: 只要目录结构符合规范，Aura 会在启动时自动发现并加载你的 Plan，无需任何手动注册。如果是在开发模式下，Aura 还能动态地监测文件变化并热重载 Plan。
*   **代码组织**: 建议将功能相关的 Actions 和 Services 组织在同一个 Plan 中，这有助于保持代码的模块化和高内聚。

在下一章节，我们将深入学习如何在 `actions/` 目录下编写你的第一个自定义 Action。

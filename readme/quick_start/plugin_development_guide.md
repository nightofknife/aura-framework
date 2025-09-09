
---

# **Aura 插件开发指南 (v6)**

欢迎来到 Aura 插件开发的世界！插件是扩展 Aura 框架功能的核心方式。通过创建自己的插件，您可以将任何应用程序、API 或自定义逻辑集成到 Aura 的自动化工作流中。

本指南将引导您完成从创建插件项目到编写、注册和使用自定义“行为 (Action)”和“服务 (Service)”的全过程，内容完全基于 Aura v6 的最新架构。

## 章节 1: 插件的核心理念

### 什么是插件？

一个 Aura 插件是一个遵循特定结构的 Python 项目，它向 Aura 框架注册可复用的功能单元。一个插件主要提供两种东西：

1.  **行为 (Actions)**: 插件的核心。这是一个可被任务 (`tasks/*.yaml`) 调用的 Python 函数，用于执行具体的操作（例如，`app.click`, `http.get`）。
2.  **服务 (Services)**: 一个长期存在的类实例，它封装了状态或连接（例如，一个数据库连接池，一个 OCR 引擎实例）。服务可以被多个 Action 共享和使用。

### 插件的生命周期

1.  **发现**: Aura 在启动时会扫描 `plans/` 和 `packages/` 目录，通过 `plugin.yaml` 文件识别所有插件。
2.  **依赖解析与排序**: `PluginManager` 使用 `resolvelib` 和 `graphlib` 验证所有插件的依赖关系，并计算出一个无冲突的加载顺序。
3.  **构建 (如果需要)**: 如果插件没有预构建的 `api.yaml` 文件，Aura 的 `Builder` 会扫描插件的 Python 源代码，分析装饰器 (`@register_action`, `@register_service`, `@requires_services`)，并自动生成 `api.yaml`。
4.  **加载与注册**: `PluginManager` 按照排好的顺序，读取每个插件的 `api.yaml`，将其中定义的 Service 类注册到 `ServiceRegistry`，将 Action 函数注册到 `ACTION_REGISTRY`。
5.  **注入与执行**: 当任务执行到一个 Action 时，Aura 的 `ActionInjector` 会：
    *   找到注册的 Action 函数。
    *   自动从 `ServiceRegistry` 中获取该 Action 所需的服务实例。
    *   将服务实例和其他所需参数（如 `context`）**注入**到 Action 函数中。
    *   执行该函数。

## 章节 2: 创建你的第一个插件

我们将创建一个名为 `Echo` 的简单插件。它将提供一个 `echo.say` 行为，该行为接收一个 `message` 参数并将其打印到日志中。

### 1. 创建插件项目

在您的工作区根目录下，运行 Aura 的插件创建命令：

```bash
aura plugin create Echo
```

这个命令会在 `plugins/` 目录（或者您指定的其他目录）下生成一个完整的插件项目结构：

```
plugins/
└── Echo/
    ├── echo/
    │   ├── __init__.py
    │   ├── actions.py      # 你的 Action 函数将在这里定义
    │   └── services.py     # 你的服务类将在这里定义
    ├── plugin.yaml         # 插件的“身份证”
    └── setup.py            # (可选) 用于将插件打包和分发
```

### 2. 定义插件元数据 (`plugin.yaml`)

打开 `plugins/Echo/plugin.yaml`。这个文件是插件的入口点，用于声明元数据和依赖。

```yaml
# plugins/Echo/plugin.yaml

# 插件的唯一名称，格式：作者/插件名
name: "MyOrg/Echo"
version: "0.1.0"
description: "一个简单的插件，提供 echo 功能作为示例。"
author: "Your Name"

# 如果你的插件依赖其他插件提供的服务，在这里声明
# 例如，我们的 Echo 插件需要使用 base 插件的日志功能
requires:
  - "Aura-Project/base" # 这将允许我们注入 LogService
```

**注意**: 在 Aura v6 中，`plugin.yaml` **不再需要** `provides` 字段。Aura 会通过扫描代码中的装饰器自动发现 Action 和 Service。

## 章节 3: 编写你的第一个行为 (Action)

Action 是通过在 Python 函数上使用 `@register_action` 装饰器来定义的。

打开 `plugins/Echo/echo/actions.py` 文件，并用以下代码替换其内容：

```python
# plugins/Echo/echo/actions.py

# 导入 Aura API 中的装饰器
from packages.aura_core.api import register_action, requires_services

# 从 base 插件中导入 LogService，以便我们可以注入它
# 注意：你需要知道服务的完整 FQID (Fully Qualified ID)
# 或者在 requires_services 中使用它的别名
from aura_official_packages.aura_base.services.log_service import LogService

@register_action(name="echo.say", public=True)
@requires_services(log='Aura-Project/base/log')
def say(
    # --- 1. 这是从 YAML 的 `params` 中获取的用户参数 ---
    message: str,

    # --- 2. 这是通过 @requires_services 注入的服务 ---
    # 参数名 'log' 必须与装饰器中的键名匹配
    log: LogService
) -> str:
    """
    一个简单的 echo action，记录一条消息并返回它。

    :param message: (来自YAML) 要回显的消息。
    :param log: (已注入) 日志服务实例。
    :return: 原始消息。
    """
    # 使用注入的服务来执行操作
    log.info(f"The Echo plugin says: '{message}'")
    
    # Action 的返回值可以在任务中通过 `steps.node_id.result` 捕获
    return message
```

#### **代码剖析 - 装饰器的魔力**

1.  **`@register_action(name="echo.say", public=True)`**:
    *   `name`: **必需**。这是在 `tasks/*.yaml` 文件中调用此 Action 时使用的唯一名称。
    *   `public`: **必需**。设为 `True` 以便其他方案或插件可以使用此 Action。

2.  **`@requires_services(log='Aura-Project/base/log')`**:
    *   这是实现**依赖注入**的关键。
    *   字典的**键** (`log`) 是你希望在函数参数中使用的**变量名**。
    *   字典的**值** (`Aura-Project/base/log`) 是你需要的服务的**完全限定ID (FQID)** 或其**公共别名**。

3.  **函数签名 (`def say(...)`)**:
    *   **用户参数** (`message: str`): 这些参数直接从任务 YAML 的 `params` 块中获取。
    *   **注入参数** (`log: LogService`): 参数名必须与 `@requires_services` 中的键匹配。类型提示 (`LogService`) 是可选的，但强烈推荐，因为它能提供代码补全和类型检查。
    *   **同步 vs 异步**: Aura 的 `ActionInjector` 会智能地处理同步 (`def`) 和异步 (`async def`) 函数。如果你编写的是 I/O 密集型操作，请使用 `async def`；对于 CPU 密集型或阻塞操作，使用普通的 `def`，Aura 会自动在线程池中运行它，防止阻塞主事件循环。

## 章节 4: 编写一个服务 (Service)

现在，让我们为 `Echo` 插件添加一个简单的服务，它会记录被 `echo.say` 调用了多少次。

### 1. 定义服务类

打开 `plugins/Echo/echo/services.py` 并粘贴以下代码：

```python
# plugins/Echo/echo/services.py

from packages.aura_core.api import register_service

@register_service(alias="echo_counter", public=True)
class EchoCounterService:
    """
    一个简单的服务，用于计算 echo.say 被调用的次数。
    """
    def __init__(self):
        self.count = 0
        print("EchoCounterService has been initialized!")

    def increment(self):
        self.count += 1
        return self.count

    def get_count(self) -> int:
        return self.count
```
**`@register_service(alias="echo_counter", public=True)`**:
*   `alias`: **必需**。这是该服务的公共别名，其他插件可以通过这个别名来请求注入此服务。
*   `public`: **必需**。设为 `True` 以便其他插件可以使用。

当 Aura 加载此插件时，它会自动创建 `EchoCounterService` 的**单例实例**并将其注册。

### 2. 在 Action 中使用服务

现在，我们来修改 `echo/actions.py` 来使用我们的新服务。

```python
# plugins/Echo/echo/actions.py (修改后)

from packages.aura_core.api import register_action, requires_services
from aura_official_packages.aura_base.services.log_service import LogService

# 导入我们自己的服务
from .services import EchoCounterService

@register_action(name="echo.say", public=True)
@requires_services(
    log='Aura-Project/base/log',
    # 添加对我们自己服务 'echo_counter' 的依赖
    # 插件的 FQID 是 MyOrg/Echo
    counter='MyOrg/Echo/echo_counter'
)
def say(
    message: str,
    log: LogService,
    # 注入我们的计数器服务
    counter: EchoCounterService
) -> str:
    # 调用服务的方法
    new_count = counter.increment()

    log.info(f"The Echo plugin says: '{message}' (This is call #{new_count})")
    
    return message
```

## 章节 5: 使用你的新插件

我们已经创建了包含 Action 和 Service 的插件，现在是时候在 `HelloWorld` 方案中使用它了！

### 1. 在方案中声明依赖

打开 `plans/HelloWorld/plugin.yaml` 文件，确保它依赖于我们的新插件：

```yaml
# plans/HelloWorld/plugin.yaml
name: "HelloWorld"
version: "0.1.0"
requires:
  - "MyOrg/Echo"
  - "Aura-Project/base" # Echo 插件自身需要 base，最佳实践是也在这里声明
```

### 2. 在任务中调用 Action

修改 `HelloWorld/tasks/greeting.yaml` 来调用我们的 `echo.say` Action：

```yaml
# HelloWorld/tasks/greeting.yaml
say_hello_and_echo:
  steps:
    echo_the_greeting:
      name: "Use the Echo Plugin"
      action: "echo.say" # 调用我们注册的 Action
      params:
        message: "Hello from my custom plugin, {{ config('user.name') }}!"
```

### 3. 运行！

在运行之前，Aura 需要先构建你的新插件以生成 `api.yaml`。你可以手动构建，或者让 Aura 在下次启动时自动构建。

**手动构建 (推荐)**:
```bash
aura plugin build plugins/Echo
```

然后，运行任务：
```bash
aura run HelloWorld/greeting/say_hello_and_echo
```
您应该会看到类似以下的日志：
```
...
INFO: EchoCounterService has been initialized!
...
INFO: The Echo plugin says: 'Hello from my custom plugin, Aura Explorer!' (This is call #1)
...
```
如果您再次运行该任务，计数将会增加到 #2，证明了服务的单例和持久性！

## 结论

您现在已经掌握了 Aura 插件开发的核心流程。通过组合使用 `@register_service`、`@register_action` 和 `@requires_services`，您可以轻松地将任何功能封装成模块化、可注入、可复用的插件，极大地扩展 Aura 的能力。




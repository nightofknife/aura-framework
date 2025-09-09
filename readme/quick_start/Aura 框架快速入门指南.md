
---

# **Aura 框架快速入门指南**

欢迎来到 Aura！本指南将引导您在 10 分钟内，从零开始构建并运行您的第一个自动化任务。我们将一起创建一个简单的“Hello World”方案，并让它自动运行。

准备好了吗？让我们开始吧！

## **章节 1: 欢迎来到 Aura**

### Aura 是什么？

Aura 是一个现代化的自动化编排器。您可以把它想象成一个智能的“数字管家”，它能根据时间、事件或您的直接指令，指挥您的各种数字工具（我们称之为“插件”）来完成复杂的任务。

无论是自动处理日常的重复性工作，还是编排复杂的跨应用工作流，Aura 都旨在让这一切变得简单、可靠且强大。

### 核心概念简介 (The Big Picture)

在深入之前，让我们先了解四个核心概念，这将帮助您快速建立对 Aura 的心智模型：

1.  **方案 (Plan)**: 您的自动化项目的“蓝图”或“文件夹”。它包含了实现一个特定自动化目标所需的所有配置和任务。
2.  **任务 (Task)**: 一份具体的“待办事项清单”，以 YAML 文件的形式存在，详细描述了要完成一个目标需要执行哪些步骤。
3.  **行为 (Action)**: 清单上的一个具体步骤，例如“点击按钮”、“发送API请求”或“打印一条日志”。
4.  **插件 (Plugin)**: 提供一系列相关“行为”的“工具箱”。例如，一个 `http` 插件可能提供 `http.get` 和 `http.post` 行为。

## **章节 2: 安装与环境初始化**

### 先决条件

*   Python 3.10 或更高版本。
*   `pip` (通常随 Python 一起安装)。

### 安装 Aura

打开您的终端或命令提示符，运行以下命令来安装 Aura 框架：

```bash
pip install aura-framework
```

### 初始化工作区

安装完成后，我们需要创建一个工作区。这是您所有自动化项目的“家”。

运行以下命令：

```bash
aura init my-automation-workspace
```

这个命令会创建一个名为 `my-automation-workspace` 的新目录，并包含以下结构：

```
my-automation-workspace/
├── plans/          # 存放您所有自动化方案的地方
├── plugins/        # 存放您下载或开发的插件的地方
└── aura_config.yaml  # Aura 的主配置文件
```

太棒了！您的 Aura 环境现在已经准备就绪。

## **章节 3: 创建你的第一个方案 (Plan)**

接下来，让我们创建第一个自动化方案。一个方案是一个自包含的自动化单元。

首先，进入我们刚刚创建的工作区目录：

```bash
cd my-automation-workspace
```

然后，使用 `aura` 命令行工具创建一个名为 `HelloWorld` 的新方案：

```bash
aura plan create HelloWorld
```

Aura 会在 `plans/` 目录下为您生成一个标准的方案结构：

```
plans/
└── HelloWorld/
    ├── plugin.yaml       # 方案的“身份证”
    ├── config.yaml       # 方案的“设置面板”
    ├── tasks/            # 存放所有任务的地方
    │   └── (空)
    └── ... (其他可选文件)
```

这三个核心文件是您需要首先关注的：
*   `plugin.yaml`: 声明了方案的名称、版本等元数据。
*   `config.yaml`: 存放所有可配置的数据，如用户名、密码、API密钥等，让您的任务代码和配置分离。
*   `tasks/`: 存放所有 `.yaml` 格式的任务文件。

## **章节 4: 编写你的第一个任务**

我们的目标是创建一个任务，它能从 `config.yaml` 中读取一个用户名，并打印一条 "Hello, [用户名]!" 的日志。

### 1. 配置数据

首先，让我们为任务提供一些数据。打开方案中的 `HelloWorld/config.yaml` 文件，并用以下内容替换它：

```yaml
# HelloWorld/config.yaml
user:
  name: "Aura Explorer"
```

### 2. 创建任务文件

现在，在 `HelloWorld/tasks/` 目录下创建一个新文件，命名为 `greeting.yaml`。

### 3. 编写任务内容

打开您刚刚创建的 `HelloWorld/tasks/greeting.yaml` 文件，并粘贴以下代码：

```yaml
# HelloWorld/tasks/greeting.yaml

# 这是任务键 (Task Key)，是此文件内任务的唯一标识
say_hello:
  # 'steps' 定义了任务的执行图
  steps:
    # 'greet_user' 是图中一个节点的唯一ID
    greet_user:
      name: "Say Hello to the User"
      # 'action' 指定要执行的行为。'log.info' 是Aura内置的行为。
      action: "log.info"
      # 'params' 是传递给 action 的参数
      params:
        # 使用 Jinja2 模板和 config() 函数从配置中动态获取数据
        message: "Hello, {{ config('user.name') }}!"
```

让我们快速分解一下这段代码：
*   `say_hello`: 我们为这个任务起的名字，它在此文件内是唯一的。
*   `steps`: 在 Aura v6 中，`steps` 是一个字典，定义了任务的执行图。
*   `greet_user`: 是图中一个节点的唯一 ID。对于简单的线性任务，我们只需要一个节点。
*   `action: "log.info"`: 我们告诉 Aura 执行内置的 `log.info` 行为，它会在控制台打印一条信息日志。
*   `message: "Hello, {{ config('user.name') }}!"`: 这是最有趣的部分。我们使用 Jinja2 模板语法 (`{{ ... }}`) 和 Aura 的内置函数 `config('user.name')` 来动态地从 `config.yaml` 文件中读取 `user.name` 的值。

## **章节 5: 手动执行任务**

我们已经创建了任务，现在是时候运行它了！

### 任务的完整ID

要告诉 Aura 运行哪个任务，我们需要提供它的完整 ID。任务 ID 的格式是：`{plan_name}/{file_path_in_tasks}/{task_key}`。

根据我们的文件结构，任务的完整 ID 是：`HelloWorld/greeting/say_hello`。

### 执行命令

在您的终端中（确保您仍在 `my-automation-workspace` 目录下），运行以下命令：

```bash
aura run HelloWorld/greeting/say_hello
```

### 验证结果

按下回车后，您应该会立即在控制台上看到 Aura 的日志输出，其中包含我们期望的消息：

```
...
INFO: [Node]: Starting 'Say Hello to the User' (ID: greet_user)
INFO: Hello, Aura Explorer!
INFO: [Node]: Finished 'Say Hello to the User' successfully.
...
```

恭喜！您刚刚完成了从配置到代码再到执行的完整闭环！

## **章节 6: 让它自动化 - 添加调度**

手动运行任务很酷，但 Aura 的真正威力在于自动化。现在，让我们设置一个调度规则，让这个任务每分钟自动运行一次。

### 1. 创建 `schedule.yaml`

在您的 `HelloWorld` 方案的根目录下（与 `plugin.yaml` 同级），创建一个名为 `schedule.yaml` 的新文件。

### 2. 编写调度规则

打开 `schedule.yaml` 并粘贴以下内容：

```yaml
# HelloWorld/schedule.yaml
- task: "HelloWorld/greeting/say_hello"  # 要调度的任务的完整ID
  schedule: "* * * * *"                  # Cron 表达式，代表“每分钟”
  enabled: true                          # 确保此条规则是激活的
```

*   `task`: 指定要自动运行的任务。
*   `schedule`: 使用标准的 [Cron 表达式](https://crontab.guru/)来定义调度时间。`* * * * *` 是最简单的一种，表示每分钟执行。
*   `enabled`: 允许您快速地启用或禁用某条调度规则，而无需删除它。

### 3. 启动 Aura 调度器

为了让调度生效，我们需要启动 Aura 的“守护进程”。这个长期运行的进程会持续监控所有方案的调度规则，并在时间到达时触发相应的任务。

在终端中运行：

```bash
aura start
```

您会看到 Aura 启动，加载您的 `HelloWorld` 方案，并进入等待状态。现在，请耐心等待一分钟。当系统时间进入下一分钟时，您将看到 Aura 自动执行了我们的任务，并在控制台打印出 "Hello, Aura Explorer!" 的日志。这个过程会每分钟重复一次。

要停止调度器，只需在终端中按下 `Ctrl+C`。

## **章节 7: 下一步做什么？**

🎉 **祝贺您！** 您已经成功地创建、配置、手动执行并自动化了您的第一个 Aura 任务。您现在已经掌握了 Aura 最核心的工作流程。

这仅仅是个开始。Aura 的世界充满了更多强大的功能等待您去探索。准备好深入学习了吗？以下是为您推荐的后续阅读文档：

*   **深入任务编写**:
    *   想学习所有任务文件的强大功能，例如并发执行 (`graph`)、循环 (`for_each`, `while`)、条件分支 (`switch`) 和高级错误处理 (`try/catch`)？
    *   请阅读: **[任务文件 (`tasks/*.yaml`) 参考手册](./tasks_reference.md)**

*   **理解框架架构**:
    *   想知道 Aura 是如何组织和运行的？各个核心模块（如 `Scheduler`, `ExecutionManager`）是如何协同工作的？
    *   请查看: **[Aura 核心架构概览](./core_architecture_overview.md)**

*   **状态与流程自动化**:
    *   对 Aura 如何像 GPS 一样自动规划任务路径以达到特定系统状态（例如，从“未登录”自动导航到“已登录”）感到好奇吗？
    *   请学习: **[声明式状态管理 (`states_map.yaml`) 指南](./state_management_guide.md)**

*   **扩展 Aura**:
    *   想为 Aura 添加与您最喜欢的 App 或 API 交互的新功能吗？
    *   学习如何: **[插件开发指南](./plugin_development_guide.md)**




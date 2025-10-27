# 文件: `cli.py`

## 1. 核心目的

该文件使用业界标准的 `click` 库，为 Aura 框架构建了一个功能强大且用户友好的**命令行接口（Command Line Interface, CLI）**。它的主要目的是为开发者和系统管理员提供一个**脱离 Web UI** 的、自动化的、可脚本化的方式来与 Aura 框架的核心功能进行交互。

与 `main.py` 提供的交互式菜单不同，`cli.py` 遵循标准的 CLI 设计模式（如 `git`, `docker`），将功能组织在不同的命令组下，并通过参数和选项来接收输入，使其非常适合在自动化脚本、CI/CD 流水线或终端中直接使用。

## 2. 关键组件与功能

*   **`get_scheduler()`**: 与 `main.py` 中的函数类似，它以**单例模式**负责在任何命令执行之前初始化并返回全局唯一的 `Scheduler` 实例。这确保了所有 CLI 命令都运行在同一个加载了完整框架上下文的环境中。

*   **`@click.group()` / `@click.command()`**: 这些是 `click` 库的装饰器，用于定义命令的层次结构。
    *   `@click.group()` 创建一个命令组，作为一个命名空间来容纳相关的子命令。
    *   `@click.command()` 定义一个具体的可执行命令。

*   **`aura` (根命令组)**: 所有 CLI 命令的根入口点。`@aura.group()` 装饰的函数 `aura()` 会在任何子命令执行前被调用，它通过调用 `get_scheduler()` 来触发框架的初始化。

*   **`package` (命令组)**: 用于管理 Aura 插件包的子命令集合。
    *   `build`: 一个具体的命令，用于强制从源代码构建一个指定的插件包。它会扫描包内的 Python 代码，提取 Action 和 Service 的定义，并生成或更新 `api.yaml` 文件。这对于插件的分发和部署至关重要。

*   **`task` (命令组)**: 用于管理和执行任务的子命令集合。
    *   `run`: 允许用户通过任务的完全限定 ID (FQID, e.g., `my_plan/my_task`) 来直接、临时地运行任何已定义的任务。它还提供了一个 `--wait` 选项，可以让命令阻塞并等待任务执行完成，这在需要同步获取任务结果的脚本中非常有用。

*   **`service` (命令组)**: 用于检查和监控系统内部状态的子命令集合。
    *   `list`: 列出所有在服务注册表中注册的服务，并以不同颜色高亮显示它们的状态（例如，`defined`, `resolved`），为系统调试和状态监控提供了极大的便利。

## 3. 核心逻辑解析

`cli.py` 的核心逻辑在于其**框架加载机制**和**命令分派**。

### 框架加载机制

CLI 工具的一个关键要求是，无论用户在哪个目录下执行命令（例如 `python cli.py package build ...`），它都必须能正确地找到并加载 Aura 框架的核心模块。`cli.py` 在文件开头通过以下代码段来确保这一点：

```python
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
```

1.  `Path(__file__).resolve().parent`: 这一行代码获取 `cli.py` 文件所在的目录，也就是项目的根目录。
2.  `sys.path.insert(0, ...)`: 它将项目根目录**添加**到 Python 解释器的模块搜索路径列表 `sys.path` 的**最前面**。

这确保了后续的 `from packages.aura_core.scheduler import Scheduler` 等导入语句总是能够成功找到正确的模块，而不会受到当前工作目录的干扰。

随后，通过 `get_scheduler()` 函数的单例模式，确保了只有在执行第一个命令时才会触发框架的（可能耗时的）初始化过程，后续的命令则可以复用已经加载好的框架实例，从而提高了执行效率。

### 命令分派与执行

`click` 库极大地简化了命令的定义和参数解析。以 `task run` 命令为例：

```python
@task.command(name="run")
@click.argument('task_fqid')
@click.option('--wait', is_flag=True, ...)
def run_task(task_fqid: str, wait: bool):
    # ...
```

1.  **定义**: `@task.command(name="run")` 将 `run_task` 函数注册为 `task` 命令组下的一个名为 `run` 的子命令。
2.  **参数解析**: `@click.argument` 和 `@click.option` 装饰器会自动处理命令行的解析。当用户执行 `python cli.py task run my_plan/my_task --wait` 时，`click` 会自动将 `'my_plan/my_task'` 赋值给 `task_fqid` 参数，并将 `True` 赋值给 `wait` 参数。
3.  **委托执行**: 在 `run_task` 函数内部，它只是简单地解析 `task_fqid`，然后直接调用 `scheduler.run_ad_hoc_task()`。与 `api_server.py` 一样，CLI 层本身不包含业务逻辑，它只是一个将命令行输入转化为对核心服务调用的“翻译器”。

这种清晰的分层设计，使得 `cli.py` 专注于处理命令行交互（参数解析、用户反馈、输出格式化），而将所有核心的自动化逻辑都保留在框架内部，实现了高度的模块化和可维护性。
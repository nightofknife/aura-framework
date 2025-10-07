# Aura: 高度模块化、可扩展的异步自动化框架

[简体中文](#简体中文) | [English](#english)

---

## 简体中文

### 目录
- [项目目标](#项目目标)
- [核心架构](#核心架构)
- [安装与设置](#安装与设置)
- [快速开始](#快速开始)
- [配置](#配置)
- [问题排查/FAQ](#问题排查faq)
- [版本与兼容性](#版本与兼容性)
- [贡献](#贡献)
- [许可证](#许可证)

### 项目目标

Aura 是一个为复杂自动化任务而设计的、高度模块化、可扩展的 Python 异步框架。它旨在提供一个健壮的平台，用于构建、管理和执行由多个步骤、服务和插件组成的自动化方案（Plans）。其核心特性是完全异步、事件驱动、插件化和状态感知，使其能够优雅地处理长时间运行、I/O 密集型和需要与外部系统交互的复杂工作流。

### 核心架构

Aura 的核心 (`aura_core`) 采用分层、解耦的微服务架构思想，所有组件都通过明确定义的异步接口和队列进行通信。

- **协调与 API 层 (`Scheduler`)**: 作为最高协调者和 API 门面，管理所有核心服务的生命周期。
- **并发执行中心 (`ExecutionManager`)**: 安全地调度所有任务到 `asyncio` 事件循环、线程池或进程池中执行，处理资源限制与并发。
- **逻辑执行链 (`Orchestrator` -> `Engine` -> `ActionInjector`)**: 将自动化方案（Plan）逐级分解为任务（Task）和行为（Action），并管理其执行逻辑和上下文。
- **数据、资源与规划层**: 包括`TaskLoader`（任务加载）、`ContextManager`（上下文管理）、`StateStore`（状态存储）和`StatePlanner`（路径规划）等。
- **插件化与扩展层 (`PluginManager`, `EventBus`, `MiddlewareManager`)**: 允许通过插件动态添加新的服务和行为，通过事件总线进行解耦通信，并通过中间件注入横切关注点。

更多详细信息，请参考 `readme/core_doc/index.md`。

### 安装与设置

1.  **克隆仓库**:
    ```bash
    git clone https://github.com/your-repo/aura.git
    cd aura
    ```

2.  **安装依赖**:
    建议在虚拟环境中使用 `pip` 安装依赖。
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```

### 快速开始

通过命令行界面（CLI）运行一个自动化方案：

```bash
python cli.py run-plan <plan_name>
```

例如，要运行示例方案 `hello_world`：

```bash
python cli.py run-plan hello_world
```

### 配置

Aura 的核心配置位于 `config` 目录中。主要配置文件包括：

-   `config/core.yaml`: 框架核心参数，如日志级别、插件目录等。
-   `config/states_map.yaml`: 定义了状态转换图，供 `StatePlanner` 使用。

插件和方案也可以有自己的本地配置文件。

### 问题排查/FAQ

-   **Q: 如何查看详细的执行日志？**
    A: 在 `config/core.yaml` 中将日志级别（`log_level`）设置为 `DEBUG`。日志将输出到控制台和指定的日志文件中。

-   **Q: 任务执行失败怎么办？**
    A: 检查控制台输出的错误信息和堆栈跟踪。大多数任务失败都与 Action 的实现或外部资源（如网络、文件权限）有关。

### 版本与兼容性

当前版本为 1.0.0。框架遵循语义化版本（Semantic Versioning）。

### 贡献

我们欢迎社区的贡献！请遵循以下步骤：

1.  Fork 本仓库。
2.  创建您的特性分支 (`git checkout -b feature/AmazingFeature`)。
3.  提交您的更改 (`git commit -m 'feat: Add some AmazingFeature'`)。
4.  将您的更改推送到分支 (`git push origin feature/AmazingFeature`)。
5.  提交一个 Pull Request。

请确保您的代码通过了 `black` 格式化和 `ruff` 检查。

### 许可证

本项目使用 [MIT License](LICENSE) 许可证。

---

## English

### Table of Contents
- [Project Goal](#project-goal)
- [Core Architecture](#core-architecture)
- [Installation & Setup](#installation--setup)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Troubleshooting/FAQ](#troubleshootingfaq)
- [Versioning & Compatibility](#versioning--compatibility)
- [Contributing](#contributing)
- [License](#license)

### Project Goal

Aura is a highly modular, extensible, and asynchronous Python framework designed for complex automation tasks. It aims to provide a robust platform for building, managing, and executing automation "Plans" composed of multiple steps, services, and plugins. Its core features are being fully asynchronous, event-driven, plugin-based, and state-aware, enabling it to gracefully handle complex workflows that are long-running, I/O-bound, and require interaction with external systems.

### Core Architecture

Aura's core (`aura_core`) is designed with a layered, decoupled, microservices-like architecture where all components communicate through well-defined asynchronous interfaces and queues.

-   **Coordination & API Layer (`Scheduler`)**: Acts as the top-level coordinator and API facade, managing the lifecycle of all core services.
-   **Concurrency & Execution Hub (`ExecutionManager`)**: Safely dispatches all tasks to the `asyncio` event loop, thread pools, or process pools, handling resource limits and concurrency.
-   **Logical Execution Chain (`Orchestrator` -> `Engine` -> `ActionInjector`)**: Breaks down an automation Plan into Tasks and Actions, managing their execution logic and context.
-   **Data, Resource & Planning Layer**: Includes `TaskLoader`, `ContextManager`, `StateStore`, and `StatePlanner` for pathfinding.
-   **Plugin & Extension Layer (`PluginManager`, `EventBus`, `MiddlewareManager`)**: Allows dynamic addition of new services and actions via plugins, decoupled communication through an event bus, and cross-cutting concerns via middleware.

For more details, please refer to `readme/core_doc/index.md`.

### Installation & Setup

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/your-repo/aura.git
    cd aura
    ```

2.  **Install dependencies**:
    It is recommended to use a virtual environment and `pip`.
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```

### Quick Start

Run an automation plan via the Command Line Interface (CLI):

```bash
python cli.py run-plan <plan_name>
```

For example, to run the `hello_world` example plan:

```bash
python cli.py run-plan hello_world
```

### Configuration

Aura's core configuration resides in the `config` directory. Key files include:

-   `config/core.yaml`: Core framework parameters like log level, plugin directories, etc.
-   `config/states_map.yaml`: Defines the state transition graph used by the `StatePlanner`.

Plugins and plans can also have their own local configuration files.

### Troubleshooting/FAQ

-   **Q: How can I see detailed execution logs?**
    A: Set the `log_level` to `DEBUG` in `config/core.yaml`. Logs will be output to the console and the specified log file.

-   **Q: What should I do if a task fails?**
    A: Check the error message and stack trace in the console output. Most task failures are related to the Action's implementation or external resources (e.g., network, file permissions).

### Versioning & Compatibility

The current version is 1.0.0. The framework adheres to Semantic Versioning.

### Contributing

Community contributions are welcome! Please follow these steps:

1.  Fork the repository.
2.  Create your feature branch (`git checkout -b feature/AmazingFeature`).
3.  Commit your changes (`git commit -m 'feat: Add some AmazingFeature'`).
4.  Push to the branch (`git push origin feature/AmazingFeature`).
5.  Open a Pull Request.

Please ensure your code passes `black` formatting and `ruff` checks.

### License

This project is licensed under the [MIT License](LICENSE).
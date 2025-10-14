# Aura: 异步自动化框架

[简体中文](#简体中文) | [English](#english)

---

## 简体中文

### 目录
- [简介](#简介)
- [核心架构](#核心架构)
- [安装与设置](#安装与设置)
- [快速开始](#快速开始)
- [配置指南](#配置指南)
- [常见问题 (FAQ)](#常见问题-faq)
- [版本与兼容性](#版本与兼容性)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

### 简介
Aura 是一个基于 Python 的异步自动化框架，专为构建模块化、可扩展和事件驱动的自动化工作流而设计。其核心理念是通过插件化的方式轻松集成和编排各种任务（Actions），并由一个强大的调度器（Scheduler）根据预定义的方案（Plans）来执行。

### 核心架构
Aura 采用分层和模块化的架构：
- **核心层 (`aura_core`)**: 提供框架的基础功能，如调度器、事件总线、状态管理、插件管理等。
- **插件层 (`packages`)**: 包含各种功能插件，每个插件可以是一个独立的 `plan` 或一组 `actions`。
- **应用层**: 最终用户通过命令行界面 (`cli.py`) 或 API 服务 (`api_server.py`) 与框架交互。

### 安装与设置
1.  **克隆仓库**:
    ```bash
    git clone https://github.com/your-repo/aura.git
    cd aura
    ```
2.  **安装依赖**:
    ```bash
    pip install -r requirements.txt
    ```
    *(注意: `requirements.txt` 文件当前可能不存在，需要根据实际依赖创建)*

### 快速开始
通过交互式命令行启动 Aura：
```bash
python main.py
```
启动后，你将看到一个菜单，可以：
- **启动/停止调度器**: 开始或停止后台任务执行。
- **添加任务**: 将预定义的任务加入执行队列。
- **查看状态**: 列出所有加载的 `Plans` 和 `Actions`。

### 配置指南
- **`plans/`**: 在此目录下定义你的自动化方案。每个方案是一个独立的目录，包含 `plan.yaml` 和相关的任务脚本。
- **`schedule.yaml`**: (如果存在) 定义了哪些任务应该按计划自动执行。

### 常见问题 (FAQ)
**Q: 如何创建自己的 `Action`?**
**A:** 在你的插件包中，创建一个 Python 函数，并使用 `@action` 装饰器（如果框架提供）进行注册。

### 版本与兼容性
当前版本为 `1.0.0`。与 Python 3.8+ 兼容。

### 贡献指南
我们欢迎社区贡献！请遵循以下步骤：
1.  Fork 本仓库。
2.  创建新分支 (`git checkout -b feature/your-feature`)。
3.  提交你的更改 (`git commit -m 'feat: Add some feature'`)。
4.  推送至分支 (`git push origin feature/your-feature`)。
5.  创建 Pull Request。

### 许可证
本项目根据 [MIT License](LICENSE) 授权。

---

## English

### Table of Contents
- [Introduction](#introduction)
- [Core Architecture](#core-architecture)
- [Installation & Setup](#installation--setup)
- [Quick Start](#quick-start)
- [Configuration Guide](#configuration-guide)
- [Frequently Asked Questions (FAQ)](#frequently-asked-questions-faq)
- [Versioning & Compatibility](#versioning--compatibility)
- [Contributing](#contributing)
- [License](#license)

### Introduction
Aura is an asynchronous automation framework built in Python, designed for creating modular, extensible, and event-driven automation workflows. Its core philosophy is to easily integrate and orchestrate various tasks (Actions) via a plugin-based system, executed by a powerful Scheduler according to predefined Plans.

### Core Architecture
Aura uses a layered and modular architecture:
- **Core Layer (`aura_core`)**: Provides the foundational features of the framework, such as the Scheduler, Event Bus, State Management, and Plugin Manager.
- **Plugin Layer (`packages`)**: Contains various functional plugins. Each plugin can be an independent `plan` or a set of `actions`.
- **Application Layer**: End-users interact with the framework through the command-line interface (`cli.py`) or an API server (`api_server.py`).

### Installation & Setup
1.  **Clone the repository**:
    ```bash
    git clone https://github.com/your-repo/aura.git
    cd aura
    ```
2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: A `requirements.txt` file may not currently exist and would need to be created based on actual dependencies.)*

### Quick Start
Launch Aura via the interactive command line:
```bash
python main.py
```
After launching, you will see a menu that allows you to:
- **Start/Stop the Scheduler**: Begin or halt background task execution.
- **Add Tasks**: Add predefined tasks to the execution queue.
- **View Status**: List all loaded `Plans` and `Actions`.

### Configuration Guide
- **`plans/`**: Define your automation plans in this directory. Each plan is a separate directory containing a `plan.yaml` and related task scripts.
- **`schedule.yaml`**: (If it exists) Defines which tasks should be executed automatically on a schedule.

### Frequently Asked Questions (FAQ)
**Q: How do I create my own `Action`?**
**A:** In your plugin package, create a Python function and register it using the `@action` decorator (if provided by the framework).

### Versioning & Compatibility
The current version is `1.0.0`. It is compatible with Python 3.8+.

### Contributing
We welcome community contributions! Please follow these steps:
1.  Fork this repository.
2.  Create a new branch (`git checkout -b feature/your-feature`).
3.  Commit your changes (`git commit -m 'feat: Add some feature'`).
4.  Push to the branch (`git push origin feature/your-feature`).
5.  Create a Pull Request.

### License
This project is licensed under the [MIT License](LICENSE).
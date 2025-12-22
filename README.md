# Aura: 异步自动化框架

[简体中文](#简体中文) | [English](#english)

---

## 简体中文
### 目录
- [简介](#简介)
- [快速开始](#快速开始)
- [目录结构](#目录结构)
- [文档](#文档)
- [FAQ](#faq)
- [许可](#许可)

### 简介
Aura 是一个基于 Python 的异步自动化框架，面向模块化、可扩展、事件驱动的自动化工作流。核心由 Scheduler
协调，Plan 定义任务，Action/Service 提供可复用能力。

### 快速开始
1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
2. 启动后端 API（自动启动 Scheduler）：
   ```bash
   python backend/run.py
   ```
   默认地址：`http://127.0.0.1:18098/api/v1`
3. 交互式控制台：
   ```bash
   python main.py
   ```
4. GUI（可选）：
   ```bash
   cd aura_gui
   npm install
   npm run dev
   ```

### 目录结构
- `plans/`: Plan 插件（含 `plugin.yaml` / `tasks/` / `schedule.yaml` / `interrupts.yaml`）
- `packages/`: 功能插件（actions/services）
- `backend/`: FastAPI 后端（`/api/v1`，WebSocket 默认 `/ws/v1/events`）
- `readme/quick_start/`: 入门文档
- `readme/core_doc/`: 核心模块文档

### 文档
- 入门指南：`readme/quick_start/Aura 框架快速入门指南.md`
- 任务语法：`readme/quick_start/tasks_reference.md`
- 核心架构：`readme/core_doc/index.md`

### FAQ
- 如何编写 Action/Service？
  使用 `@register_action` / `@register_service` 并在 `plugin.yaml` 中声明插件身份。
- 如何运行单个任务？
  通过 API `/tasks/run` 或 `python cli.py task run <plan>/<task>`。

### 许可
本项目使用 [MIT License](LICENSE)。

---

## English
### Table of Contents
- [Introduction](#introduction)
- [Quick Start](#quick-start)
- [Project Layout](#project-layout)
- [Docs](#docs)
- [FAQ](#faq-1)
- [License](#license)

### Introduction
Aura is an asynchronous automation framework in Python. It is built for modular, extensible, event-driven workflows,
coordinated by a central Scheduler. Plans define tasks, and Actions/Services provide reusable capabilities.

### Quick Start
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the backend API (starts Scheduler automatically):
   ```bash
   python backend/run.py
   ```
   Default base URL: `http://127.0.0.1:18098/api/v1`
3. Interactive console:
   ```bash
   python main.py
   ```
4. GUI (optional):
   ```bash
   cd aura_gui
   npm install
   npm run dev
   ```

### Project Layout
- `plans/`: Plan plugins (`plugin.yaml`, `tasks/`, `schedule.yaml`, `interrupts.yaml`)
- `packages/`: Capability plugins (actions/services)
- `backend/`: FastAPI backend (`/api/v1`, WebSocket default `/ws/v1/events`)
- `readme/quick_start/`: Quick start docs
- `readme/core_doc/`: Core module docs

### Docs
- Quick start: `readme/quick_start/Aura 框架快速入门指南.md`
- Task syntax: `readme/quick_start/tasks_reference.md`
- Core architecture: `readme/core_doc/index.md`

### FAQ
- How do I write Actions/Services?
  Use `@register_action` / `@register_service` and declare plugin identity in `plugin.yaml`.
- How do I run a single task?
  Use the `/tasks/run` API or `python cli.py task run <plan>/<task>`.

### License
This project is licensed under the [MIT License](LICENSE).

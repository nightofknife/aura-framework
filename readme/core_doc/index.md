---
# Aura 核心架构概览

Aura 的核心执行链路可以概括为：
`Scheduler` -> `ExecutionManager` -> `Orchestrator` -> `ExecutionEngine` -> `ActionInjector` -> Action。

## 模块索引
### 调度与执行
- `readme/core_doc/scheduler.md`
- `readme/core_doc/execution_manager.md`
- `readme/core_doc/plan_manager.md`
- `readme/core_doc/orchestrator.md`
- `readme/core_doc/engine.md`
- `readme/core_doc/action_injector.md`

### 插件与注册
- `readme/core_doc/plugin_manager.md`
- `readme/core_doc/plugin_provider.md`
- `readme/core_doc/builder.md`
- `readme/core_doc/api.md`
- `readme/core_doc/inheritance_proxy.md`

### 配置与模板
- `readme/core_doc/config_loader.md`
- `readme/core_doc/dependency_manager.md`
- `readme/core_doc/template_renderer.md`

### 数据与状态
- `readme/core_doc/context.md`
- `readme/core_doc/persistent_context.md`
- `readme/core_doc/state_store.md`
- `readme/core_doc/state_planner.md`
- `readme/core_doc/task_loader.md`
- `readme/core_doc/task_queue.md`

### 事件与扩展
- `readme/core_doc/event_bus.md`
- `readme/core_doc/middleware.md`
- `readme/core_doc/interrupt_service.md`
- `readme/core_doc/scheduling_service.md`
- `readme/core_doc/logger.md`
- `readme/core_doc/context_manager.md`

### 异常
- `readme/core_doc/exceptions.md`
- `readme/core_doc/exception_manager.md`

## 配置补充
- `config.yaml` + 环境变量 `AURA_` 作为全局配置来源
- Plan 专属配置放在 `plans/<plan>/config.yaml`

## 入口文档
- 入门文档: `readme/quick_start/Aura 框架快速入门指南.md`
- 任务语法: `readme/quick_start/tasks_reference.md`

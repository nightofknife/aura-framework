---
# 核心模块: `orchestrator.py`

## 概览
`Orchestrator` 与单个 Plan 绑定，负责加载任务、创建执行上下文、驱动 `ExecutionEngine`，并封装结果。

## 关键职责
- 使用 `TaskLoader` 读取任务定义
- 构建 `ExecutionContext` 并执行 `ExecutionEngine`
- 通过 `EventBus` 发布 `task.started` / `task.finished`
- 处理 `returns` 模板并生成 `user_data`
- 提供安全的文件读写 API（限制在 plan 目录）

## Task Final Result (TFR)
`execute_task` 返回结构：
- `status`: `SUCCESS` / `FAILED` / `ERROR`
- `user_data`: 由 `returns` 渲染得到
- `framework_data`: 任务执行上下文（含 `nodes`）
- `error`: 异常详情（如有）

## 条件检查
`perform_condition_check` 使用 Action 执行条件（用于中断规则等）。

## 文件系统安全
所有文件/目录操作通过 `_resolve_and_validate_path`，防止路径穿越。

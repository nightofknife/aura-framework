---
# 核心模块: `middleware.py`

## 概览
提供可插拔的中间件链，用于在 Action 执行前后插入逻辑。

## 结构
- `Middleware.handle(action_def, context, params, next_handler)`
- `MiddlewareManager.add()` / `process()`

## 当前状态
中间件链当前未在 `ActionInjector` 中默认启用，如需全局中间件请在调用路径中显式接入。

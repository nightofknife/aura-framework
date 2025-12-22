---
# 核心模块: `asynccontext.py`

## 概览
提供 `plan_context` 异步上下文管理器，用于设置当前执行的 Plan 名称，实现配置隔离。

## 作用
- `plan_context(plan_name)` 会设置 `current_plan_name` (ContextVar)
- `ConfigService` 会根据当前 plan 自动读取对应 `config.yaml`

## 使用
```python
from packages.aura_core.asynccontext import plan_context

async with plan_context("my_plan"):
    ...
```

## 相关模块
- `SchedulingService` / `InterruptService` 在检查任务时使用
- `ConfigService` 通过该上下文隔离配置

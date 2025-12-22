---
# 核心模块: `exceptions.py`

## 概览
定义 Aura 的异常体系，涵盖控制流、执行错误、配置错误与资源错误。

## 主要异常
- `AuraException`：基类，包含 `details` / `cause` / `severity`
- `TaskControlException`：控制流异常基类
  - `JumpSignal`：跳转信号（如 break/continue）
  - `StopTaskException`：正常停止任务
- `ExecutionError`：执行时错误
  - `TaskExecutionError` / `ActionExecutionError` / `TaskNotFoundError`
- `ConfigurationError`
  - `StatePlanningError` / `DependencyError`
- `ResourceError`
  - `ResourceAcquisitionError`
- `TimeoutError`

## 工厂函数
提供 `create_task_error` / `step_failed` / `create_jump_signal` / `create_stop_task` 等快捷创建方法。

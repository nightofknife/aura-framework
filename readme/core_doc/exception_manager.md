---
# 异常处理流程

## 概览
项目中没有独立的 `exception_manager` 模块。异常按执行链路分层处理。

## 分层处理
- `ExecutionEngine`：节点级异常 -> 标记 FAILED 写入 `run_state`
  - `JumpSignal` / `StopTaskException` 用于控制流
- `ExecutionManager`：处理超时、取消、规划失败，并触发 Hook
- `Orchestrator`：封装 Task Final Result（`status` / `user_data` / `framework_data` / `error`）

## 建议
- Action 失败直接抛出异常即可
- 需要提前终止任务，可使用 `StopTaskException` 或 `JumpSignal`

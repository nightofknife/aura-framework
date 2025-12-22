---
# 核心模块: `execution_manager.py`

## 概览
`ExecutionManager` 负责并发执行与资源控制，协调状态规划与任务生命周期 Hook。

## 主要能力
- 线程池 / 进程池：区分 IO 与 CPU 任务
- 全局并发限制与资源标签信号量
- 统一任务提交入口：`submit(tasklet, is_interrupt_handler=False)`
- 状态规划：读取 `meta.requires_initial_state` 并调用 `StatePlanner`
- 生命周期 Hook：`before_task_run` / `after_task_success` / `after_task_failure` / `after_task_run`

## 执行链路
Tasklet -> Orchestrator.execute_task -> ExecutionEngine -> ActionInjector

## 配置相关
- `execution.max_concurrent_tasks`
- `execution.io_workers` / `execution.cpu_workers`
- `execution.state_planning.*`

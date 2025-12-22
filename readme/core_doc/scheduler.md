---
# 核心模块: `scheduler.py`

## 概览
Scheduler 是 Aura 的入口与总协调者，负责启动事件循环、加载 Plan、管理队列、调度执行。

## 主要职责
- 初始化核心服务并注册到 `service_registry`
- 加载 Plan、任务、schedule、interrupts
- 维护主队列 / 事件队列 / 中断队列
- 启动消费者协程与后台服务（SchedulingService / InterruptService）
- 对外提供状态查询与任务调度 API
- 支持热重载（watchdog）

## 核心队列
- `task_queue`: 普通任务
- `event_task_queue`: 事件触发任务
- `interrupt_queue`: 中断处理任务

## 任务来源
- API/CLI 手动触发
- `schedule.yaml` 定时任务
- Task `triggers` 的事件订阅
- `interrupts.yaml` 中断规则

## 运行模式
- Scheduler 在独立线程中运行 `asyncio` 事件循环
- 任务实际执行委托给 `ExecutionManager`

## Hot Reload
`enable_hot_reload()` 监控 `plans/**/tasks/*.yaml` 与插件 `.py` 文件，自动刷新任务/插件。

# Scheduler 与 Runtime Profile

## 1. Scheduler 的角色

`Scheduler` 是 Aura 运行时的外观层，负责：

- 初始化核心服务
- 维护 control loop
- 管理 queue、event bus、state store、plan manager、execution manager
- 对外暴露调度、查询、热重载、文件操作等接口

## 2. 生命周期

### 创建

- `runtime.bootstrap` 会创建 runtime 单例
- API 层 `get_core_scheduler()` 也会懒创建一个 scheduler singleton
- 创建 scheduler 不等于启动 scheduler

### 启动

- `start_scheduler()` 通过 `LifecycleManager` 启动独立线程
- 新线程内运行 asyncio control loop
- 启动后会拉起 consumer、worker、schedule loop、interrupt loop、observability cleanup 等子任务

### 停止

- `stop_scheduler()` 会停止 schedule / interrupt 服务
- 取消主 loop 任务
- 清理 registry、running task 和 executor 资源

## 3. API 中的 singleton 语义

API 依赖层维护一个进程内 singleton：

- 第一次访问依赖时惰性创建
- `system/stop` 后会 reset 引用
- 应用 lifespan 结束时若 scheduler 仍在运行，会尝试 stop

## 4. Runtime Profile

当前内置：

### `api_full`

- `enable_schedule_loop = true`
- `enable_interrupt_loop = true`
- `enable_event_triggers = true`

### `tui_manual`

- `enable_schedule_loop = false`
- `enable_interrupt_loop = false`
- `enable_event_triggers = false`

## 5. scheduler 未运行时的行为

这点很重要：

- ad-hoc task 仍可被 API 放入 pre-start buffer
- 返回结果通常仍是“queued”
- 真正执行要等 scheduler 启动并 flush 缓冲任务

因此：

- 如果希望请求后立即执行，应先调用 `POST /api/v1/system/start`
- 如果只是预先排队，可以在 stop 状态下先 dispatch

## 6. 关键队列

- `task_queue`
- `event_task_queue`
- `interrupt_queue`
- `ui_event_queue`
- `api_log_queue`

## 7. 关键子服务

- `LifecycleManager`
- `RuntimeLifecycleService`
- `DispatchService`
- `ExecutionManager`
- `RunQueryService`
- `HotReloadControlService`
- `TaskletIdentityService`

## 8. 常见问题

- scheduler 已创建但没启动
- dispatch 成功但任务不执行
- 误以为 API 请求成功就代表任务已完成

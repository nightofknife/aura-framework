# Queue 与 Runs

Aura 当前在调度器内部已经有完整的 queue 和 run 查询能力，但并非全部通过 REST API 暴露。

## 1. Queue 模型

当前有三类主要队列：

- `task_queue`
- `event_task_queue`
- `interrupt_queue`

`TaskQueue` 支持：

- `put`
- `get`
- `insert_at`
- `remove_by_cid`
- `move_to_front`
- `move_to_position`
- `list_all`
- `clear`
- `reorder`

## 2. Tasklet

队列里的最小执行单元是 `Tasklet`。

关键字段：

- `task_name`
- `cid`
- `trace_id`
- `trace_label`
- `source`
- `payload`
- `is_ad_hoc`
- `initial_context`
- `execution_mode`
- `resource_tags`
- `timeout`
- `planning_depth`

## 3. queue 事件

主队列流转时通常会产生：

- `queue.enqueued`
- `queue.dequeued`
- `queue.completed`

## 4. Run 状态

调度器会同时维护：

- `run_statuses`
- `running_tasks`
- `_running_task_meta`
- observability 侧的 active / completed runs

## 5. API 已公开的部分

当前 FastAPI 已公开：

- `POST /api/v1/tasks/dispatch`
- `POST /api/v1/tasks/dispatch/batch`
- `POST /api/v1/tasks/dispatch/schedule/{item_id}`
- `POST /api/v1/tasks/status/batch`

## 6. 当前未通过 REST 暴露的部分

调度器内部已有，但当前 REST 未公开：

- queue overview
- queue list
- queue insert / remove / reorder
- active runs
- persisted runs history
- run timeline

## 7. scheduler 未运行时的排队

当前行为：

- `ExecutionService.run_ad_hoc_task()` 会把任务写入 `_pre_start_task_buffer`
- 返回通常仍是 success / queued
- 待 scheduler 启动时，buffer 会被 flush 到主队列

## 8. 常见排障

- 任务卡在 queued：先确认 scheduler 是否启动
- task 已 dispatch 但没有 active run：先检查是否仍在 pre-start buffer
- queue 里看不到某个 task：它可能已 dequeue 并在 `running_tasks` 中

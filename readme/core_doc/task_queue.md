---
# 核心模块: `task_queue.py`

## 概览
自定义异步任务队列，支持高优先级插入、批量删除与顺序调整。

## Tasklet 字段
- `task_name`: `<plan>/<task>`
- `cid` / `trace_id` / `trace_label` / `source`
- `payload` / `initial_context`
- `execution_mode`: `sync` / `async`
- `resource_tags`: 用于并发限制
- `timeout` / `cpu_bound`

## 队列能力
- `put` / `get` / `join`
- `insert_at` / `remove_by_cid` / `remove_by_filter`
- `move_to_front` / `move_to_position` / `clear`

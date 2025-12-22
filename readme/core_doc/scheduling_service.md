---
# 核心模块: `scheduling_service.py`

## 概览
基于 cron 的时间调度服务，定期检查 `schedule.yaml` 并提交到主队列。

## schedule.yaml 格式
```yaml
- id: daily_job
  task: "subdir/my_task"
  enabled: true
  trigger:
    type: time_based
    schedule: "0 2 * * *"
  run_options:
    cooldown: 0
  inputs:
    foo: "bar"
```

## 说明
- `id` 用于运行状态追踪
- `run_options.cooldown` 控制最小间隔
- `plan_name` 在加载时由 Scheduler 自动补充
- 兼容性：手动触发接口当前读取 `task_name` 字段，建议同时保留 `task` 与 `task_name`

# Aura REST API 参考

## 基础信息

- 前缀：`/api/v1`
- OpenAPI：`/docs`
- ReDoc：`/redoc`

## 任务调度

### 单任务调度

`POST /api/v1/tasks/dispatch`

```json
{
  "plan_name": "MyTestPlan",
  "task_ref": "tasks:test:draw_one_star",
  "inputs": {}
}
```

### 批量调度

`POST /api/v1/tasks/dispatch/batch`

```json
{
  "tasks": [
    {
      "plan_name": "MyTestPlan",
      "task_ref": "tasks:test:draw_one_star",
      "inputs": {}
    }
  ]
}
```

### 手动触发 schedule 项

`POST /api/v1/tasks/dispatch/schedule/{item_id}`

### 批量状态查询

`POST /api/v1/tasks/status/batch`

```json
{
  "cids": ["123", "456"]
}
```

## 资源分组

### System

- `GET /api/v1/system/status`
- `GET /api/v1/system/metrics`
- `GET /api/v1/system/health`
- `GET /api/v1/system/ready`
- `POST /api/v1/system/start`
- `POST /api/v1/system/stop`

### Plans

- `GET /api/v1/plans`
- `GET /api/v1/plans/{plan_name}/tasks`
- `GET /api/v1/plans/{plan_name}/files/tree`
- `GET /api/v1/plans/{plan_name}/files/content?path=...`
- `PUT /api/v1/plans/{plan_name}/files/content?path=...`
- `POST /api/v1/plans/{plan_name}/files/reload?path=...`

### Queue / Runs

- `GET /api/v1/queue/overview`
- `GET /api/v1/queue/list?state=ready&limit=200`
- `POST /api/v1/queue/insert`
- `GET /api/v1/runs/active`
- `GET /api/v1/runs/history`

### Actions / Services / Packages

- `GET /api/v1/actions`
- `GET /api/v1/services`
- `GET /api/v1/packages`

## WebSocket

- 事件流：`ws://127.0.0.1:18098/ws/v1/events`
- 日志流：`ws://127.0.0.1:18098/ws/logs`

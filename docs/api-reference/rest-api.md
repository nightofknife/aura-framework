# Aura REST API Reference

## Base

- Prefix: `/api/v1`
- OpenAPI: `/docs`
- ReDoc: `/redoc`

The current backend is centered on a minimal platform surface for task selection, dispatch, queue arrangement, and run inspection.

## Minimal Platform API

### System

- `GET /api/v1/system/status`
- `GET /api/v1/system/health`
- `GET /api/v1/system/metrics`

`status` and `health` return a stable shape:

```json
{
  "status": "ok",
  "is_running": true,
  "scheduler_initialized": true,
  "scheduler_running": true,
  "ready": true
}
```

### Plans / Tasks

- `GET /api/v1/plans`
- `GET /api/v1/plans/{plan_name}/tasks`
- `GET /api/v1/plans/{plan_name}/task-load-errors`

`GET /plans/{plan_name}/tasks` returns task metadata keyed by canonical `task_ref`, with `meta.inputs` included so GUI clients do not need to read task YAML files. Legacy task id formats are not part of the API contract.

### Dispatch

- `POST /api/v1/tasks/dispatch`
- `POST /api/v1/tasks/dispatch/batch`
- `POST /api/v1/tasks/status/batch`

Single dispatch request:

```json
{
  "plan_name": "resonance",
  "task_ref": "tasks:auto_cycle_trade.yaml",
  "inputs": {}
}
```

Single dispatch response:

```json
{
  "status": "queued",
  "message": "Task queued",
  "cid": "xxx",
  "trace_id": "xxx",
  "trace_label": "xxx"
}
```

### Queue

- `GET /api/v1/queue/overview`
- `GET /api/v1/queue/list?state=ready&limit=200`
- `DELETE /api/v1/queue/{cid}`
- `POST /api/v1/queue/{cid}/move-to-front`
- `POST /api/v1/queue/reorder`
- `DELETE /api/v1/queue/clear`

Queue overview response:

```json
{
  "ready_count": 3,
  "running_count": 1,
  "delayed_count": 0,
  "ready_length": 3,
  "delayed_length": 0,
  "avg_wait_sec": 0.2
}
```

Queue list response:

```json
{
  "items": [
    {
      "cid": "xxx",
      "plan_name": "resonance",
      "task_ref": "tasks:auto_cycle_trade.yaml",
      "task_name": "tasks:auto_cycle_trade.yaml",
      "trace_label": "resonance/auto_cycle_trade",
      "status": "queued",
      "queued_at": 1710000000000,
      "enqueued_at": 1710000000000,
      "source": "gui"
    }
  ]
}
```

### Runs

- `GET /api/v1/runs/active`
- `GET /api/v1/runs/history`
- `GET /api/v1/runs/{cid}`

History response:

```json
{
  "runs": [
    {
      "cid": "xxx",
      "plan_name": "resonance",
      "task_ref": "tasks:auto_cycle_trade.yaml",
      "task_name": "tasks:auto_cycle_trade.yaml",
      "status": "success",
      "started_at": 1710000000000,
      "finished_at": 1710000009000,
      "duration_ms": 9000,
      "error": null
    }
  ]
}
```

Run detail returns one object with:

- `cid`
- `plan_name`
- `task_ref`
- `trace_id`
- `trace_label`
- `status`
- `started_at`
- `finished_at`
- `duration_ms`
- `error`
- `user_data`
- `framework_data`
- `nodes`

## Compatibility API

These routes are still exposed for the current GUI during migration, but they are not part of the preferred minimal contract:

- `POST /api/v1/system/start`
- `POST /api/v1/system/stop`
- `GET /api/v1/system/ready`
- `GET /api/v1/system/logs`
- `GET /api/v1/system/hot_reload/status`
- `POST /api/v1/system/hot_reload/enable`
- `POST /api/v1/system/hot_reload/disable`
- `GET /api/v1/plans/{plan_name}/files/tree`
- `GET /api/v1/plans/{plan_name}/files/content`
- `PUT /api/v1/plans/{plan_name}/files/content`
- `POST /api/v1/plans/{plan_name}/files/reload`
- `DELETE /api/v1/plans/{plan_name}`
- `GET /api/v1/run/{cid}/detail`
- `GET /api/v1/actions`
- `GET /api/v1/services`
- `GET /api/v1/packages`

## Not Yet Required for GUI V1

The new minimal GUI is expected to work via HTTP polling only. WebSocket event and log streams are not required for the V1 platform contract.

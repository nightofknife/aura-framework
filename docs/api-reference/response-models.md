# 响应模型

本页汇总当前 `backend/api/schemas.py` 中已公开的 Pydantic 模型。

## `TaskRunResponse`

字段：

- `status: str`
- `message: str`
- `cid: str | null`
- `trace_id: str | null`
- `trace_label: str | null`

用于：

- `POST /tasks/dispatch`
- `POST /tasks/dispatch/schedule/{item_id}`

## `SystemStatusResponse`

字段：

- `is_running: bool`

用于：

- `GET /system/status`

## `HealthResponse`

字段：

- `status: str`
- `scheduler_initialized: bool`
- `scheduler_running: bool`

用于：

- `GET /system/health`
- `GET /system/ready`

## `PlanSummary`

字段：

- `name: str`
- `task_count: int`
- `task_error_count: int`

用于：

- `GET /plans`

## `TaskLoadErrorResponse`

字段：

- `plan_name: str`
- `source_file: str`
- `task_refs: list[str]`
- `error_code: str`
- `message: str`

用于：

- `GET /plans/{plan_name}/task-load-errors`

## `PackageSummary`

字段：

- `canonical_id: str`
- `name: str`
- `version: str`
- `path: str`

用于：

- `GET /packages`

## `ActionSummary`

字段：

- `fqid: str`
- `name: str`
- `public: bool`
- `read_only: bool`
- `description: str`

用于：

- `GET /actions`

## `GenericMessageResponse`

字段：

- `status: str`
- `message: str`
- `data: dict | null`

用于：

- `POST /system/start`
- `POST /system/stop`
- `PUT /plans/{plan_name}/files/content`
- `POST /plans/{plan_name}/files/reload`
- `DELETE /plans/{plan_name}`

## 说明

- 部分路由未显式声明 response model，返回结构应视为实现细节
- `services`、`plans/{plan_name}/tasks`、`system/metrics` 属于这种情况

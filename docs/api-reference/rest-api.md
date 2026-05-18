# Aura REST API Reference

## Base

- Prefix: `/api/v1`
- OpenAPI: `/docs`
- ReDoc: `/redoc`
- Default local base URL: `http://127.0.0.1:18098/api/v1`

API 保持 `/api/v1`。stable 字段只增不删；compat API 保留迁移说明；experimental API 不进入默认 GUI。

## Security Boundary

默认模式是 `local_only`。

- 公共路由：
  - `GET /api/v1/system/health`
  - `GET /api/v1/system/status`
- 其他路由受保护。
- loopback GUI 访问不需要 API key。

绑定非 loopback host 时，必须显式开启远程模式：

- `AURA_API_REMOTE_ENABLED=1`
- `AURA_API_AUTH_KEY`
- `AURA_API_TRUSTED_HOSTS`

远程受保护请求必须发送 `X-Aura-Api-Key`。

## Stability Classes

- `stable`: 默认 GUI 使用，必须保持文档和测试同步。
- `compat`: 兼容迁移接口，可能受 feature flag 限制。
- `experimental`: 当前不承诺稳定，默认 GUI 不暴露。

## Stable API

### System

- `GET /api/v1/system/status`
- `GET /api/v1/system/health`
- `GET /api/v1/system/metrics`
- `POST /api/v1/system/start`
- `POST /api/v1/system/stop`

### Plans / Tasks

- `GET /api/v1/plans`
- `GET /api/v1/plans/{plan_name}/tasks`
- `GET /api/v1/plans/{plan_name}/task-load-errors`

`/plans/{plan_name}/tasks` 返回 canonical `task_ref`、`meta.inputs` 和 task definition 摘要。GUI 不直接读取 task YAML。

### Dispatch

- `POST /api/v1/tasks/dispatch`
- `POST /api/v1/tasks/dispatch/batch`
- `POST /api/v1/tasks/status/batch`
- `POST /api/v1/tasks/validate`
- `POST /api/v1/tasks/dry-run`

`/tasks/validate` and `/tasks/dry-run` are no-side-effect authoring endpoints. They validate DSL, manifest, action resolution, input defaults, and backend selection without executing real actions.

### Queue

- `GET /api/v1/queue/overview`
- `GET /api/v1/queue/list?state=ready&limit=200`
- `DELETE /api/v1/queue/{cid}`
- `POST /api/v1/queue/{cid}/move-to-front`
- `DELETE /api/v1/queue/clear`
- `GET /api/v1/queue/recovery/status`
- `POST /api/v1/queue/recovery/recover`
- `POST /api/v1/queue/recovery/abandon-stale`

V6 persists the main task queue in SQLite. Event queues and interrupt queues remain in memory.

### Runs

- `GET /api/v1/runs/active`
- `GET /api/v1/runs/history`
- `GET /api/v1/runs/{cid}`
- `GET /api/v1/runs/{cid}/evidence`
- `GET /api/v1/runs/{cid}/evidence/manifest`
- `GET /api/v1/runs/{cid}/locators`
- `GET /api/v1/runs/{cid}/debug-report`

`GET /runs/{cid}` 保留原有字段，并新增：

- `action_results`: action result envelope 列表。
- `policy_decisions`: policy allow/deny 审计记录。
- `evidence`: 结构化 evidence 引用。

`GET /runs/{cid}/evidence` 只返回 evidence manifest 和引用，不直接返回二进制截图或 OCR 文件。

### Catalog

- `GET /api/v1/actions`
- `GET /api/v1/services`
- `GET /api/v1/packages`

stable desktop action 必须暴露：

- 参数 schema
- 返回 schema
- capability metadata
- supported backend domains
- side effect level
- stability: `stable|compat|experimental`

### Capabilities

- `GET /api/v1/capabilities`
- `GET /api/v1/capabilities/{domain}`
- `POST /api/v1/capabilities/self-check`

backend metadata 包含 `backend_id`、`domain`、`available`、`health_status`、前后台限制、权限要求、side effect、capabilities、limitations、last error 和 stability。

### Workspace

- `GET /api/v1/workspace`
- `GET /api/v1/workspace/packages`
- `POST /api/v1/workspace/packages/{package_id}/enable`
- `POST /api/v1/workspace/packages/{package_id}/disable`
- `POST /api/v1/workspace/packages/{package_id}/reload`
- `POST /api/v1/workspace/packages/lock`
- `POST /api/v1/workspace/packages/validate`
- `GET /api/v1/workspace/packages/{package_id}/permissions`
- `GET /api/v1/workspace/packages/{package_id}/migrations`
- `POST /api/v1/workspace/packages/{package_id}/upgrade-plan`
- `POST /api/v1/workspace/packages/{package_id}/upgrade`
- `POST /api/v1/workspace/packages/{package_id}/rollback`

package enable/disable 修改 workspace profile。V3/V4 不保证所有 package 生命周期变更热加载，用户需要 reload 或重启 API 才能刷新已加载 service/action。

### Runtime Reload

- `GET /api/v1/runtime/reload/status`
- `POST /api/v1/runtime/reload/plan`
- `POST /api/v1/runtime/reload/apply`

Runtime reload is a local administration operation. Apply is protected by the hot reload admin feature flag.

### Migrations

- `GET /api/v1/migrations/status`
- `POST /api/v1/migrations/plan`
- `POST /api/v1/migrations/apply`

Migration apply is additive and idempotent. POST migration operations are protected by the hot reload admin feature flag.

### Diagnostics

- `GET /api/v1/diagnostics/recent`
- `GET /api/v1/diagnostics/{id}`
- `POST /api/v1/diagnostics/collect`

diagnostics 默认脱敏，默认只导出 evidence manifest，不复制截图/OCR 原始文件。

### Policy

- `GET /api/v1/policy`
- `GET /api/v1/policy/effective`

`/policy` 返回 capability taxonomy、内置 profiles 和当前 profile。`/policy/effective` 返回当前 profile 下的 allow/deny 集合，以及已加载 action/service 的 capability metadata。

### Observability

- `GET /api/v1/observability/traces`
- `GET /api/v1/observability/traces/{trace_id}`
- `GET /api/v1/observability/errors/summary`
- `GET /api/v1/observability/metrics/actions`
- `GET /api/v1/observability/metrics/backends`
- `GET /api/v1/observability/metrics/services`
- `GET /api/v1/observability/metrics/desktop`
- `GET /api/v1/observability/resources`
- `GET /api/v1/observability/errors/{category}`
- `GET /api/v1/observability/queue/analysis`

Observability API 只读聚合 run store、action results、policy audit 和 evidence refs，用于错误分类、trace 查询、action/backend 指标和队列分析。

## Compatibility API

以下路由仍保留，但不是推荐最小契约：

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
- `POST /api/v1/queue/reorder`
- `GET /api/v1/run/{cid}/detail`

## Experimental API

GUI 默认不暴露 action/service/package 在线编辑和完整 IDE 能力。此类接口必须先明确契约、测试和稳定性分类，再进入主导航。

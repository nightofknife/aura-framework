# Observability Query Guide

V5 的 observability 查询层复用 V4 的 run store、action result envelope、policy audit 和 evidence refs，不引入第二套事件模型。

## CLI

```powershell
python cli.py observability errors
python cli.py observability trace TRACE_ID
python cli.py observability backend-metrics
python cli.py observability service-metrics
python cli.py observability desktop-metrics
python cli.py observability resources
python cli.py observability error-category locator_not_found
python cli.py run explain CID
```

`run explain` 会返回失败分类、policy decision、backend/fallback、evidence reference 和定位建议。

## API

- `GET /api/v1/observability/traces`
- `GET /api/v1/observability/traces/{trace_id}`
- `GET /api/v1/observability/errors/summary`
- `GET /api/v1/observability/errors/{category}`
- `GET /api/v1/observability/metrics/actions`
- `GET /api/v1/observability/metrics/backends`
- `GET /api/v1/observability/metrics/services`
- `GET /api/v1/observability/metrics/desktop`
- `GET /api/v1/observability/resources`
- `GET /api/v1/observability/queue/analysis`

## 错误分类

- `policy_denied`
- `backend_unavailable`
- `action_validation_failed`
- `template_render_failed`
- `dsl_schema_invalid`
- `capture_failed`
- `locator_not_found`
- `ocr_failed`
- `yolo_failed`
- `timeout`
- `dependency_unavailable`
- `unknown_error`

## 数据来源

- `runs`
- `run_nodes`
- `action_results`
- `policy_audit`
- `evidence_refs`

SQLite V5 migration 只增不删，已有 runs 可以通过 backfill 聚合到 trace、error、action、backend 指标表。

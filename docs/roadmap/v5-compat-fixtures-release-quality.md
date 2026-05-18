# Aura V5 兼容治理、测试夹具与发布质量升级方案

V5 的目标是把 V1-V4 已形成的框架能力变成可验证、可升级、可发布的本地基线。本阶段不做远程 marketplace，不把 GUI 扩成 IDE，不恢复或引用已清理业务资产，也不引入 Docker、Poetry 或 `pyproject.toml`。

## 目标

- 建立兼容矩阵，统一 API、manifest、Task DSL、workspace、lock、capability、diagnostics、policy、evidence、run store 的 schema version。
- 建立 fake/fixture golden tests，让核心桌面自动化链路可以在无真实桌面副作用的环境中验收。
- 把 V4 的 action result、policy audit、evidence refs 和 run nodes 聚合成可查询的 observability 视图。
- 提供 debug report 和默认安全的 fake step replay。
- 建立本地 package pack、diff、compat、upgrade-plan 和 release check 质量门禁。

## 关键交付

### Compatibility Governance

- 新增 `compat/aura-compat.yaml`。
- 新增 `python cli.py compat matrix`、`compat check`、`compat diff`。
- 新增 `python cli.py package upgrade-plan PACKAGE_ID`。
- stable API snapshot 存放在 `tests/snapshots/api-v1-stable.json`，删除 stable path 或 method 会被兼容检查捕获。

### Golden Fixtures

- 新增 `tests/fixtures/desktop/`。
- 新增 `python cli.py fixture list|run|verify`。
- fixture 只允许 `fake` 或 `fixture` backend，默认不更新 snapshot。
- `--update-snapshot` 只更新 fixture snapshot，不修改业务代码。

### Observability Query

- 新增错误分类：`policy_denied`、`backend_unavailable`、`action_validation_failed`、`template_render_failed`、`dsl_schema_invalid`、`capture_failed`、`locator_not_found`、`ocr_failed`、`timeout`、`dependency_unavailable`、`unknown_error`。
- 新增 API：`/observability/traces`、`/observability/errors/summary`、`/observability/metrics/actions`、`/observability/metrics/backends`、`/observability/queue/analysis`。
- 新增 CLI：`observability errors`、`observability trace`、`observability backend-metrics`、`run explain`。

### Debug Report

- 新增 `python cli.py debug report --cid CID`。
- 新增 `python cli.py debug replay-step --cid CID --node NODE --backend fake`。
- 默认只允许 `fake` 或 `fixture` replay；真实副作用 replay 必须显式 `--allow-side-effects`，并仍受 policy 限制。

### Package Release Gate

- 新增 `package pack`、`package diff`、`package compat`。
- `.aura` 作为本地包格式，不上传、不发布到远程 registry。
- 新增 `python cli.py release check`，组合 strict validate、package doctor、policy doctor、compat check、fixture verify、pytest 和 GUI build。

## 验收标准

- `compat check` 能发现 unsupported schema version 和 stable API snapshot 破坏。
- fake fixture E2E 可以在无真实桌面副作用下验证最小 package 流程。
- 失败 run 可以按错误类型、trace、action、backend 聚合查询。
- debug report 能导出失败上下文，并支持默认 fake step replay。
- package 可以本地 pack、diff、compat、upgrade-plan。
- `release check` 成为本地发布 readiness 的统一入口。

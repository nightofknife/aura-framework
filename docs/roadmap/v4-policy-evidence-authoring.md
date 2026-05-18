# Aura V4 权限治理、证据链与开发者工具链升级方案

## Summary

V4 补齐 roadmap 剩余关键缺口：Action/Service 权限模型、统一 evidence/run detail 诊断链路、desktop facade 完成度、DSL 作者工具链。

V4 不扩展 GUI 成完整 IDE，不做远程 marketplace，不引入 Docker/Poetry/pyproject。

## 目标

- 每个 stable action/service 都有 capability metadata。
- policy profile 在 action 参数调用前完成 allow/deny 判定。
- run detail 能定位 action、backend、fallback、policy decision 和 evidence reference。
- stable desktop action 逐步统一走 facade。
- fake backend 支撑无真实桌面副作用的 dry-run 和 CI。
- plan 作者能通过 scaffold、validate、graph、template render、dry-run 完成最小开发闭环。

## Policy

默认 profile 是 `default`，采用 fail-closed：

- 未知 capability 拒绝执行。
- profile 明确禁止的能力拒绝执行。
- `hid_mouse`、`process.control`、`network.remote` 默认拒绝。

内置 profiles：

- `safe`: 只允许 read/OCR/window read 等低风险能力。
- `default`: 允许常规桌面输入、截图、OCR，拒绝 HID、进程控制和远程网络。
- `trusted`: 允许 package 显式声明的 capability。
- `dev`: 开发诊断模式，允许实验能力并保留 audit。

## Evidence

每个 action 执行后生成 action result envelope。desktop action 保留 backend、fallback、duration、evidence；非 desktop action 也生成统一 envelope，只是 `backend=null`。

持久化位置：

```text
logs/evidence/{cid}/
  manifest.json
  action-results.jsonl
  captures/
  ocr/
  backend/
```

diagnostics 默认只导出 manifest 和引用。截图/OCR 文件必须显式 `--include-evidence`。

## CLI

新增：

```powershell
python cli.py policy inspect
python cli.py policy doctor
python cli.py package permissions PACKAGE_ID
python cli.py task graph --plan PLAN --task-ref TASK_REF --format mermaid|json
python cli.py task explain --plan PLAN --task-ref TASK_REF --format text|json
python cli.py template render --plan PLAN --task-ref TASK_REF --context context.json --format text|json
python cli.py scaffold package PACKAGE_ID
python cli.py scaffold task --plan PLAN --name NAME
```

这些命令不执行 action。`template render` 只渲染 `params`、`when`、`returns`。

## API / GUI

新增 stable API：

- `GET /api/v1/policy`
- `GET /api/v1/policy/effective`
- `GET /api/v1/workspace/packages/{package_id}/permissions`
- `GET /api/v1/runs/{cid}/evidence`

GUI 只增加只读观测：

- Runs 显示 action result、backend fallback、policy decision、evidence reference。
- Plans 显示只读 task graph。
- Settings 显示 active policy profile。

## 验收标准

- policy deny 会进入 run detail 和 policy audit。
- `/runs/{cid}` 返回 `action_results`、`policy_decisions`、`evidence`。
- diagnostics 默认不复制截图 evidence。
- fake capture/window/OCR/mouse/keyboard 能支撑无副作用 E2E。
- 新 plan 作者可以通过 CLI 工具完成最小任务开发闭环。

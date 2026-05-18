# Aura V1 提升实施方案

V1 目标是把 Aura 从当前本机工作区收敛为通用 Windows 桌面自动化框架的稳定基线。本阶段只做三件事：core / desktop 边界基线、API / GUI 契约收敛、Task DSL 校验与 dry-run 初版。

V1 不拆仓，不引入 Docker、Poetry、`pyproject.toml`，不恢复或迁移已清理业务资产，不做完整 GUI IDE，也不做 package marketplace。

## 1. Core / Desktop 边界

V1 保留当前默认 `workspace-default` 运行方式，确保现有 API 和 GUI 启动不破坏。

边界定义：

- `aura_core` 是框架核心，负责 scheduler、DSL、package、API、observability 和安全边界。
- `plans/aura_base` 是官方 desktop capability package，提供截图、键鼠、OCR、视觉、YOLO、进程管理等能力。
- `framework-core` 是最小 smoke 依赖档，用于验证 core 不隐式依赖 desktop capability。
- `workspace-default` 是当前仓库默认工作区 profile，不是 core 的定义。

V1 不迁移目录结构。core / desktop 解耦先通过依赖档、测试和文档固化。

## 2. API / GUI 契约

V1 API 分为三类：

- `stable`：GUI V1 默认使用，必须有文档和测试。
- `compat`：保留但属于兼容迁移接口，可能受 feature flag 限制。
- `experimental`：当前不承诺，GUI 主导航不暴露。

V1 stable API：

- system：`GET /system/status`、`GET /system/health`、`GET /system/metrics`、`POST /system/start`、`POST /system/stop`
- plans/tasks：`GET /plans`、`GET /plans/{plan}/tasks`、`GET /plans/{plan}/task-load-errors`
- execution：`POST /tasks/dispatch`、`POST /tasks/dispatch/batch`、`POST /tasks/status/batch`
- queue：`GET /queue/overview`、`GET /queue/list`、`DELETE /queue/{cid}`、`POST /queue/{cid}/move-to-front`、`DELETE /queue/clear`
- runs：`GET /runs/active`、`GET /runs/history`、`GET /runs/{cid}`
- catalog：`GET /actions`、`GET /services`、`GET /packages`

GUI V1 默认导航只保留执行台、运行记录、方案/任务和设置。

`DashboardView`、`ActionsView` detail、`ServicesView` detail/status、`PackagesView` manifest 编辑和 `AutomationView` 作为 experimental 源码保留，但不作为 V1 公开产品能力。

## 3. Task DSL 校验与 Dry-run

V1 新增：

```powershell
.venv-test\Scripts\python.exe cli.py validate
```

参数：

- `--base-path PATH`：工作区根目录，默认当前目录。
- `--plan PLAN`：只校验指定 plan。
- `--format text|json`：输出格式，默认 `text`。
- `--strict`：启用更严格静态检查。
- `--dry-run --plan PLAN --task-ref TASK_REF`：只校验指定任务，不执行 action。

返回码：

- `0`：无错误。
- `1`：发现校验错误。
- `2`：CLI 参数或运行环境错误。

JSON 输出：

```json
{
  "status": "error",
  "errors": [
    {
      "plan_name": "demo",
      "file_path": "plans/demo/tasks/task.yaml",
      "task_ref": "tasks:task.yaml",
      "task_key": "task",
      "step_id": "start",
      "field_path": "steps.start.action",
      "error_code": "action_missing",
      "message": "Step action must be a non-empty string."
    }
  ]
}
```

默认校验是宽松模式：会检查 manifest、task YAML、schema、移除字段、`depends_on`、`task_ref`、输入 schema 和外部 action FQID/依赖格式。`--strict` 会额外要求 bare action 出现在当前 plan manifest exports 中。

`--dry-run` 只做解析、输入默认值归一化和 action 参数静态检查，不执行截图、键鼠、OCR、进程、文件写入等副作用 action。

## 4. 验收标准

V1 完成后应满足：

- `framework-core` 可独立 smoke，不隐式要求加载 `aura_base`。
- 当前 `workspace-default` 启动和 GUI V1 使用不被破坏。
- REST 文档、后端 routes、GUI 默认调用表面一致。
- `cli.py validate` 能在运行任务前发现主要 DSL 错误。
- `--dry-run` 不产生桌面自动化副作用。
- 新 plan 作者能根据文档创建、校验、派发一个最小任务。
- 已清理业务资产不作为路线、测试或示例资产出现。

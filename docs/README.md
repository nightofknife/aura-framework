# Aura 文档总览

Aura 当前文档按四个入口层组织：

- [快速开始](./getting-started/01-python-runtime.md)
  从环境、CLI、API、任务 YAML 和运行时语义开始。
- [包开发](./package-development/manifest-reference.md)
  面向 package、action、service、hook 开发者。
- [运行维护](./runtime-operations/scheduler-and-profiles.md)
  面向调度、状态规划、观测、热重载和排障。
- [API 参考](./api-reference/rest-api.md)
  面向集成方，覆盖当前已公开的 REST 接口和响应模型。

## 推荐阅读路径

### 初次接触项目

1. [Python 运行环境与入口](./getting-started/01-python-runtime.md)
2. [架构总览](./getting-started/02-architecture-overview.md)
3. [任务 YAML 指南](./getting-started/03-task-yaml-guide.md)
4. [运行时行为](./getting-started/04-runtime-behavior.md)

### 编写 package / 扩展

1. [Manifest 参考](./package-development/manifest-reference.md)
2. [Action 与 Service 开发](./package-development/actions-and-services.md)
3. [Hook 与生命周期](./package-development/hooks-and-lifecycle.md)
4. [任务引用与依赖](./package-development/task-references-and-dependencies.md)

### 运维与排障

1. [Scheduler 与 Runtime Profile](./runtime-operations/scheduler-and-profiles.md)
2. [状态规划](./runtime-operations/state-planning.md)
3. [Observability](./runtime-operations/observability.md)
4. [Hot Reload](./runtime-operations/hot-reload.md)
5. [Queue 与 Runs](./runtime-operations/queue-and-runs.md)

### API 集成

1. [REST API 参考](./api-reference/rest-api.md)
2. [响应模型](./api-reference/response-models.md)
3. [错误语义](./api-reference/error-semantics.md)

## 术语

- `Plan`
  方案。通常对应 `plans/<PlanName>/` 目录。
- `Task`
  任务。来自 plan 下的 task YAML 定义。
- `Step` / `Node`
  任务里的步骤节点。
- `Action`
  可执行动作函数。
- `Service`
  可注入的运行时服务。
- `Package`
  可被 `PackageManager` 发现和加载的扩展包或方案包。

## 关于 schema

- [docs/schemas/task-schema.json](./schemas/task-schema.json) 是任务 DSL 的静态校验契约。
- 运行时仍兼容少量额外写法，例如单任务文件的根级 `meta/steps/returns` 结构。
- 当 schema 与运行时兼容层同时存在时，以本目录中的文档说明和当前运行时代码为准。

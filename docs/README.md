# Aura 文档总览

## V5 新增入口

- [V5 兼容治理、测试夹具与发布质量升级方案](./roadmap/v5-compat-fixtures-release-quality.md)
- [Observability Query](./runtime-operations/observability-queries.md)
- [Package Compatibility and Upgrade](./package-development/compat-and-upgrade.md)
- [Fixtures and Golden Tests](./package-development/fixtures-and-golden-tests.md)
- [Release Check](./runtime-operations/release-check.md)
- [Packaging](./runtime-operations/packaging.md)

## V6 Runtime Operations

- [V6 Runtime Reload, Recoverable Queue, and SDK](./roadmap/v6-runtime-reload-recoverable-queue-sdk.md)
- [Runtime Reload](./runtime-operations/runtime-reload.md)
- [Queue Recovery](./runtime-operations/queue-recovery.md)
- [Extension SDK Reference](./package-development/sdk-reference.md)

## Roadmap Closure

- [Roadmap Closure 全量补齐方案](./roadmap/roadmap-closure-plan.md)
- [Non-GUI Roadmap Closure Implementation](./roadmap/non-gui-roadmap-closure-implementation.md)
- [Roadmap Closure 状态收口](./roadmap/roadmap-closure-status.md)

Aura 当前文档按四类入口组织：

- [快速开始](./getting-started/01-python-runtime.md)
- [包开发](./package-development/manifest-reference.md)
- [运行维护](./runtime-operations/scheduler-and-profiles.md)
- [API 参考](./api-reference/rest-api.md)
- [升级路线](./roadmap/aura-framework-upgrade-roadmap.md)

## 先看什么

首次接触当前仓库，建议按这个顺序阅读：

1. [Python 运行环境与入口](./getting-started/01-python-runtime.md)
2. [架构总览](./getting-started/02-architecture-overview.md)
3. [REST API 参考](./api-reference/rest-api.md)
4. [通用 Windows 桌面自动化框架提升路线](./roadmap/aura-framework-upgrade-roadmap.md)
5. [V1 提升实施方案](./roadmap/v1-upgrade-plan.md)
6. [V2 桌面能力多 Backend 提升方案](./roadmap/v2-desktop-capability-runtime.md)
7. [V3 Package Lifecycle 与长期运行升级方案](./roadmap/v3-package-lifecycle-runtime-operations.md)
8. [V4 权限治理、证据链与开发者工具链升级方案](./roadmap/v4-policy-evidence-authoring.md)

## 当前定位

Aura 的目标是通用 Windows 桌面自动化框架。当前仓库仍保留默认本机工作区形态：

- `aura_core` 是框架核心。
- `plans/aura_base` 是官方 desktop capability package。
- `workspace-default` 是默认工作区 profile，不等同于 core。
- GUI 是本地运行控制台和观测入口，不是完整 IDE。

## 推荐入口

### 运行维护

- [本机 API 部署约定](./runtime-operations/local-api-deployment.md)
- [Scheduler 与 Runtime Profile](./runtime-operations/scheduler-and-profiles.md)
- [Queue 与 Runs](./runtime-operations/queue-and-runs.md)
- [Desktop Capability Backend Matrix](./runtime-operations/desktop-capabilities.md)
- [Workspace Profile](./runtime-operations/workspace-profile.md)
- [Persistence](./runtime-operations/persistence.md)
- [Diagnostics](./runtime-operations/diagnostics.md)
- [Packaging](./runtime-operations/packaging.md)
- [Policy Capabilities](./runtime-operations/policy-capabilities.md)
- [Evidence 与 Run Detail](./runtime-operations/evidence-and-run-detail.md)

### 扩展开发

- [Manifest 参考](./package-development/manifest-reference.md)
- [Action 与 Service 开发](./package-development/actions-and-services.md)
- [任务引用与依赖](./package-development/task-references-and-dependencies.md)
- [Package Lifecycle](./package-development/package-lifecycle.md)
- [Task Authoring Toolchain](./package-development/task-authoring-toolchain.md)

## 工程约定

- Python 3.13
- PowerShell 脚本驱动
- `.venv` 负责 runtime
- `.venv-test` 负责 pytest
- 默认 API 入口是 `http://127.0.0.1:18098/api/v1`
- 默认安全模型是 `localhost-only`

## 术语

- `Plan`: `plans/<PlanName>/`
- `Task`: plan 下的 task YAML
- `Action`: 可执行动作函数
- `Service`: 可注入运行时服务
- `Package`: 可被 `PackageManager` 发现和加载的扩展包或方案包

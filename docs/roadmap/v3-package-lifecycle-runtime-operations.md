# Aura V3 Package Lifecycle 与长期运行升级方案

V3 把 Aura 从仓库内置 plan 的本地工作区，推进到可安装、可启停、可锁定、可诊断、可长期运行的 Windows 桌面自动化框架基线。

## 目标

- `workspace.yaml` 成为当前工作区 profile。
- `packages.lock.yaml` 记录 enabled package 的版本、source、hash 和依赖。
- 本地 package lifecycle 支持 list、validate、install、enable、disable、remove、lock、doctor。
- SQLite 默认持久化到 `logs/aura.sqlite3`。
- diagnostics bundle 可以导出结构化排障资料。
- GUI 默认提供 capabilities 和 packages 运维视图。

## 非目标

- 不做远程 marketplace。
- 不做完整 GUI IDE。
- 不恢复、不迁移、不引用已清理业务资产。
- 不引入 Docker、Poetry 或 pyproject 迁移。

## 验收标准

- 没有 `workspace.yaml` 时仍兼容原扫描行为。
- 有 `workspace.yaml` 时只加载 enabled package。
- package lock 可复现当前 enabled package 状态。
- API 重启后 run history 默认从 SQLite 可查。
- diagnostics bundle 默认脱敏且不导出截图 evidence。
- V1 stable API 与 V2 capability API 保持兼容。

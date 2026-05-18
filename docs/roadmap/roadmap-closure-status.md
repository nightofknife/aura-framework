# Aura Roadmap Closure 状态收口

更新日期：2026-05-14

本文用于记录 V1 到 P2 的实现边界、当前未提交变更分类、质量门禁结果和剩余工作。它是状态收口文档，不替代 `aura-framework-upgrade-roadmap.md`、各阶段实施方案或运行指南。

## 当前结论

Aura 的非 GUI 框架基线已经按 roadmap 目标完成主要收口：core 边界、desktop capability runtime、package lifecycle、长期运行、权限治理、evidence/run detail、SDK、recoverable queue、compat/release gate、安全加固和 observability 写入优化都已有实现与默认测试覆盖。

剩余重点不在框架底座，而在两个方向：

- GUI 轻量 authoring/debugging/observability 体验继续独立推进。
- 真实桌面、raw input、HID、YOLO 等 opt-in 环境验证继续作为显式人工/本机测试，不进入默认 release gate。

`lsns/` 删除只作为本地方案空间清理和资产删除分类记录，不纳入 Aura 框架路线、示例、测试、package 或未来方向说明。

## 已完成能力

### V1 稳定基线

- 固化 `aura_core`、`plans/aura_base`、`workspace-default` 三者边界。
- 增加 framework-core smoke，验证 core 可在 minimal workspace 下启动并通过 API health。
- 收敛 stable API 和 GUI 默认调用面。
- 增加 Task DSL validate/dry-run 初版，支持结构化错误输出。

### V2 Desktop Capability Runtime

- 建立 desktop capability registry/facade/backends/profile/fallback/result 基线。
- 覆盖 capture、mouse、keyboard、window、OCR、fake backend。
- 明确 raw input 只做监听诊断，HID mouse 作为可选驱动 backend，不可用时 fail-closed。
- 引入统一 backend metadata、selection policy 和 capability API。

### V3 Package Lifecycle 与长期运行

- 引入 `workspace.yaml`、`packages.lock.yaml` 和 package lifecycle CLI。
- SQLite 从 run store 扩展为长期运行数据层。
- 增加 diagnostics bundle、workspace/package API、compat version schema 基线。
- package lock 能复现当前 enabled package 状态。

### V4 权限治理、证据链与开发者工具链

- 增加 action/service capability policy 和 fail-closed profile。
- action result envelope、policy audit、evidence refs、run detail 统一落库。
- 补齐 desktop facade 的 capture/window/OCR/input 稳定调用路径。
- 增加 task graph、explain、template render、scaffold、SDK context/evidence writer。

### V5 兼容治理、测试夹具与发布质量

- 增加 `compat/aura-compat.yaml`、compat check/diff/snapshot/deprecation 机制。
- 增加 fake/golden fixtures 和无副作用 E2E 验证。
- 增加 observability query、error taxonomy、debug report、fake replay-step。
- 增加 `.aura` 本地 pack/diff/compat/upgrade-plan 和 release check。

### V6 Runtime Reload、可恢复队列与 SDK 稳定化

- 增加 runtime/package reload plan/apply/status、reload barrier 和 rollback 约束。
- main queue 持久化到 SQLite，支持 claim/ack/recover/abandon stale。
- 增加 SQLite migration runner。
- 稳定 extension SDK：`ActionContext`、`EvidenceWriter`、`PolicyContext`、`ActionResultBuilder`。

### Roadmap Closure 与非 GUI 补齐

- core import boundary 增强，禁止 core smoke 加载 desktop-only module。
- stable desktop action/service 通过 conformance scan 禁止直接绑定 Win32/ctypes/OCR/YOLO SDK。
- LocatorResult、DesktopActionResult、evidence manifest、debug report、run explain 补深。
- package upgrade/rollback/migration hook 执行闭环落地。
- persistence cleanup/archive/export、observability resource/desktop metrics、真实 opt-in fixture marker 落地。

### P0/P1/P2 安全与性能加固

- API local mutating 操作增加 token 与 package admin feature flag。
- package id/path、file action、policy/backend/admin gate、durable queue claim/ack 做安全加固。
- diagnostics、persistence、debug report、run explain 统一使用 Redactor。
- package pack/hash/checksum/validate/doctor 默认拒绝 symlink。
- YOLO model trust 默认拒绝绝对路径、禁用自动下载，并限制 trusted roots。
- observability 写入改为后台批量 writer，事件发布热路径不再同步写 SQLite。

## 当前未提交变更分类

基于 `git status --short` 的分类结果：

| 分类 | 数量 | 说明 |
| --- | ---: | --- |
| 框架核心 `packages/aura_core/` | 43 | policy、diagnostics、fixtures、compat、observability、SDK、queue、workspace lifecycle、安全工具等 |
| API/CLI | 18 | stable API、security dependency、workspace/diagnostics/runtime/migration/observability routes、CLI command groups |
| 官方 package/plans | 16 | `plans/aura_base` desktop runtime/facade/actions/services 与 `plans/aura_benchmark` metadata |
| 文档 | 22 | roadmap、runtime operations、package development、API reference、README |
| 测试/夹具 | 21 | V1-V6、closure、安全、fixtures、snapshots |
| 工程配置/脚本 | 17 | requirements、setup/test/release scripts、GitHub config、example config、pytest config |
| workspace/compat/lock | 3 | `workspace.yaml`、`packages.lock.yaml`、compat matrix |
| GUI | 24 | GUI 页面、组件、主题、API client；后续可独立拆分审查 |
| 删除资产 `lsns/` | 168 | 本地业务资产清理；不作为框架能力、路线或示例 |

## Lock Drift 处理

`release check` 曾报告 `plans/aura_base` lock drift。原因是 `plans/aura_base` 已有预期变更，包括 manifest、requirements、actions、services 和 desktop runtime 相关文件，而 `packages.lock.yaml` 尚未刷新。

已执行：

```powershell
.venv-test\Scripts\python.exe cli.py package lock
.venv-test\Scripts\python.exe cli.py package doctor --format json
```

当前结果：

- `package doctor`: `status=success`
- `errors=[]`
- `warnings=[]`
- `plans/aura_base` content hash 已更新为 `sha256:556b0ec461c02ef42209a24cff84ebca5af23fdd8a0667339d377c6186e05fc2`

## Release Gate

当前已通过：

```powershell
git diff --check
.venv-test\Scripts\python.exe -m pytest -m "not slow and not yolo"
.venv-test\Scripts\python.exe cli.py release check
```

最近结果：

- `pytest -m "not slow and not yolo"`: `86 passed, 1 deselected`
- `release check`: `status=success`
- `npm run build`: release check 内通过
- `package doctor`: warning 已清零

## 剩余工作

### 先不做

- 不恢复、不迁移、不引用 `lsns/`。
- 不做远程 marketplace。
- 不引入 Docker、Poetry、pyproject。
- 不承诺跨平台。
- 不把 GUI 扩展成完整 IDE。

### 后续可独立推进

- GUI 轻量 authoring/debugging：validate、dry-run、task graph、debug report、fake replay、upgrade-plan 的控制台入口。
- 真实桌面环境 opt-in 验证：desktop capture、real OCR、real YOLO、raw input monitor、HID mouse driver。
- 提交拆分：建议按 core/API、desktop runtime、package/runtime ops、security/observability、docs/tests、GUI、lsns deletion 分组提交或分 PR。

# Aura V6 Runtime Reload、可恢复队列与 SDK 稳定化升级方案

## Summary

V6 将 Aura 从“可发布的本地框架基线”继续推进为“长期运行时可维护框架”。本阶段补齐安全 runtime/package reload、可恢复 main task queue、SQLite migration runner、稳定扩展 SDK，以及 GUI 运维入口。

V6 不做远程 marketplace，不做 GUI IDE，不恢复或引用已清理业务资产，不引入 Docker、Poetry 或 pyproject。事件队列与 interrupt 队列继续保持内存态；V6 只持久化 main task queue。

## Key Changes

- Runtime reload 提供 plan/apply/status，默认 fail-fast；drain 模式等待 active runs 完成后刷新 runtime。
- Main queue 使用 SQLite `queue_items` 和 `worker_leases` 保存 ready、delayed、leased、completed、dropped、abandoned 状态。
- SQLite 增加 migration status/plan/apply 入口，迁移保持 additive 和幂等。
- Extension SDK 暴露 `ActionContext`、`EvidenceWriter`、`PolicyContext`、`ActionResultBuilder`。
- GUI 不新增主导航：Settings 展示 reload/migration，Observability 展示 queue recovery。

## Acceptance

- API 重启后 ready/delayed main queue 可以恢复。
- stale leased queue item 可 recover 或 abandon，并进入结构化状态。
- Package enable/disable 后可通过 reload plan/apply 刷新 runtime。
- Action 作者可使用稳定 SDK，而不依赖内部 `ExecutionContext`。
- V1-V5 默认 API、GUI、release check 不回退。

# Persistence

Aura 默认使用本地 SQLite 作为长期运行数据层：

```text
logs/aura.sqlite3
```

主要数据包括 runs、run nodes、workspace package snapshot、capability snapshot、diagnostic bundle metadata、queue recovery state、action result、policy audit、evidence refs 和 observability 聚合数据。

## Migration

- 如果旧库 `logs/runs/run_store.sqlite3` 存在，启动和 migration 命令会尝试无损复制到新库。
- 旧库不会被删除。
- `/runs/history` 和 `/runs/{cid}` 优先读取新库。

## Queue Policy

- V6 只持久化 main task queue。
- event queue 和 interrupt queue 仍保持内存态。
- API 重启后 ready/delayed queue item 可以恢复；过期 leased item 根据 attempts 和 task 解析结果恢复或标记为 `abandoned`。

## Lifecycle Commands

```powershell
python cli.py persistence status
python cli.py persistence cleanup --older-than 30 --dry-run
python cli.py persistence cleanup --older-than 30 --apply
python cli.py persistence archive --older-than 90 --output diagnostics/archive.zip
python cli.py persistence export --format jsonl --output diagnostics/runs.jsonl
python cli.py persistence export --format sqlite --output diagnostics/aura.sqlite3
```

`cleanup` 默认只处理可重建或过期运维数据：

- `resource_samples`
- `queue_snapshots`
- `diagnostic_bundles`

以下数据默认受保护，不会被 cleanup 删除：

- `runs`
- `node_terminal_events`
- `action_results`
- `policy_audit`
- `evidence_refs`
- `logs/evidence/*`

`archive` 导出历史 run、diagnostic metadata 和 evidence manifest。二进制 evidence 默认不导出，除非对应命令显式提供 include evidence 语义。

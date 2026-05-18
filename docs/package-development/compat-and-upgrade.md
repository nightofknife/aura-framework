# Package Compatibility and Upgrade

Aura 使用本地兼容矩阵和本地 package lifecycle 管理升级风险。本页只描述本地流程，不包含远程 marketplace、远程 registry 或 Git 安装。

## Compatibility Matrix

默认文件：

```text
compat/aura-compat.yaml
```

矩阵覆盖：

- stable API snapshot
- stable action/service contract snapshot
- manifest schema version
- task DSL schema version
- workspace/lock schema version
- capability/diagnostics/policy/evidence/run store schema version
- desktop result schema reference
- deprecation records and breaking change notes

常用命令：

```powershell
python cli.py compat matrix
python cli.py compat check
python cli.py compat snapshot --update
python cli.py compat deprecations
python cli.py compat diff --from-lock old.lock.yaml --to-lock packages.lock.yaml
python cli.py package upgrade-plan plans/aura_base
```

`compat check` 默认只比较当前契约和快照，不更新快照。只有显式执行 `compat snapshot --update` 才会写入 stable contract snapshot。

过期 deprecation 必须包含 migration note，否则 `compat deprecations` 和 `compat check` 会失败。

## Local Package Commands

```powershell
python cli.py package pack plans/aura_base
python cli.py package diff old_package new_package
python cli.py package compat plans/aura_base
python cli.py package upgrade plans/aura_base --from .\local-package --dry-run
python cli.py package upgrade plans/aura_base --from .\local-package --apply
python cli.py package rollback plans/aura_base --to-lock packages.lock.yaml
python cli.py package migrations plans/aura_base
python cli.py package migrations plans/aura_base --execute --trusted
```

`.aura` 是本地 zip 格式，包含 `manifest.yaml`、`package/`、`checksums.sha256`、`package-lock.snapshot.yaml`，并可选包含 `compat-report.json`、`fixtures/`、`migrations/`。

## Upgrade Loop

- `--dry-run` 只生成升级计划，不修改 `workspace.yaml`、`packages.lock.yaml` 或 package 文件。
- `--apply` 先执行 validate、diff、fake fixture gate，然后备份当前 package、workspace、lock，替换文件并写入 lock。
- 写入 lock 后必须通过 runtime reload plan/apply gate。reload 失败时 upgrade 失败并自动恢复 package files、workspace profile 和 lock。
- apply 失败会记录 upgrade operation，rollback 会再次记录 rollback operation。
- migration hook 默认只做 dry-run；真实执行必须显式传入 `--execute --trusted`，且仍受 active policy profile 约束。
- 只支持本地目录、zip、`.aura`；远程 registry/Git 安装不进入 stable contract。

# Package Lifecycle

## Dependency Workflow

```powershell
python cli.py package deps doctor plans/aura_base
python cli.py package deps plan plans/aura_base
python cli.py package deps install plans/aura_base --dry-run
python cli.py package deps install plans/aura_base --apply --trusted --allow-network
```

`package install` only installs package files into the workspace. It does not run
`pip`. Dependency installation is a separate, auditable step:

- `doctor` reports missing or incompatible Python requirements.
- `plan` shows the exact pip command without changing the environment.
- `install --apply` requires `--trusted`, explicit `--allow-network`, and a
  policy profile that allows `filesystem.write` and `network.remote`.
- direct URL/path requirements are rejected by the automatic installer.

V3 的 package lifecycle 面向本地工作区，不包含远程 marketplace。

常用命令：

```powershell
python cli.py package list
python cli.py package validate plans/aura_base
python cli.py package install C:\path\to\package --link
python cli.py package enable plans/aura_base
python cli.py package disable plans/aura_benchmark
python cli.py package remove vendor/example --keep-files
python cli.py package lock
python cli.py package doctor
```

行为：

- `install` 会写入 `workspace.yaml` 并刷新 `packages.lock.yaml`。
- `enable` / `disable` 只修改 workspace profile，不删除文件。
- package 状态变更后需要 reload 或重启 API 才会影响已加载 runtime。
- `doctor` 会检查 manifest、task YAML、依赖、重复 package id 和 lock drift。

Package id 规范：

- 输入兼容 `@plans/aura_base` 和 `plans/aura_base`。
- 输出统一使用 `plans/aura_base`。

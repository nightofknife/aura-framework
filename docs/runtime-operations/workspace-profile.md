# Workspace Profile

Aura V3 使用仓库根目录的 `workspace.yaml` 描述当前工作区：

```yaml
workspace_schema_version: 1
workspace:
  name: default
  profile: workspace-default
runtime:
  api_profile: local_only
  desktop_profile: default
  persistence: sqlite
packages:
  - id: plans/aura_base
    enabled: true
    source: plans/aura_base
```

规则：

- `id` 使用 manifest canonical id 去掉前导 `@` 后的形式。
- `enabled: false` 的 package 不进入 runtime load。
- 没有 `workspace.yaml` 时，Aura 继续扫描 `plans/` 和 `packages/`。
- `workspace-default` 是 runtime 依赖档，不是 core。

生成 lock：

```powershell
python cli.py package lock
```

检查当前状态：

```powershell
python cli.py package list
python cli.py package doctor
```

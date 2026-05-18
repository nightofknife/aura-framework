# Task Authoring Toolchain

V4 提供一组 CLI 工具，帮助 plan 作者在不执行真实 action 的情况下检查、解释和搭建任务。

所有命令支持 `--base-path`。

## Validate

```powershell
python cli.py validate
python cli.py validate --plan aura_base --format json --strict
python cli.py validate --dry-run --plan aura_base --task-ref tasks:example.yaml
```

`validate` 解析 manifest 和 task YAML，检查 inputs、depends_on、task_ref、action reference 和 desktop backend 选择。`dry-run` 不执行截图、键鼠、OCR、进程或文件写入。

## Task Graph

```powershell
python cli.py task graph --plan PLAN --task-ref TASK_REF --format mermaid
python cli.py task graph --plan PLAN --task-ref TASK_REF --format json
```

`task graph` 基于 `depends_on` 生成 DAG，不执行 action。

## Task Explain

```powershell
python cli.py task explain --plan PLAN --task-ref TASK_REF
python cli.py task explain --plan PLAN --task-ref TASK_REF --format json
```

输出内容：

- task_ref
- task file
- inputs
- steps
- action resolve 预判
- capability/policy 预判
- DAG 摘要

## Template Render

```powershell
python cli.py template render --plan PLAN --task-ref TASK_REF --context context.json
python cli.py template render --plan PLAN --task-ref TASK_REF --context context.json --format json
```

只渲染：

- `params`
- `when`
- `returns`

缺失变量返回结构化 error，不执行 action。

## Scaffold

```powershell
python cli.py scaffold package plans/demo
python cli.py scaffold task --plan demo --name hello
```

`scaffold package` 生成最小 package 目录、manifest、task、action 和 README。`scaffold task` 在已有 plan 下生成最小 task YAML，不覆盖同名文件。

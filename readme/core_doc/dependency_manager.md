---
# 核心模块: `dependency_manager.py`

## 概览
`DependencyManager` 用于检查 Plan 插件的 Python 依赖（`requirements.txt`），并根据配置决定是否自动安装。

## 关键流程
- `ensure_plan_dependencies(plan_path)`
  - 返回 `DependencyCheckResult(ok, missing)`
  - 若缺失依赖且允许自动安装，会调用 `pip install -r requirements.txt`

## 解析规则
- 支持 `-r`/`--requirement` 引用子 requirements 文件
- 跳过无法解析的行（会记录警告）

## 相关配置项（`config.yaml`）
- `dependencies.requirements_file`（默认 `requirements.txt`）
- `dependencies.auto_install`（默认 `true`）
- `dependencies.pip.args`（附加 pip 参数）
- `dependencies.pip.timeout_sec`（安装超时）
- `dependencies.on_missing`（`skip_plan` / `continue`）

## 与插件加载的关系
`PluginManager` 会在加载 Plan 插件时调用该模块，缺失依赖时可跳过该 Plan。

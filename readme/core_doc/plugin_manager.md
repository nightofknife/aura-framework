---
# 核心模块: `plugin_manager.py`

## 概览
负责发现、解析、排序并加载所有插件（Plans / Packages）。

## 加载流程
1. 扫描 `plans/**/plugin.yaml` 与 `packages/**/plugin.yaml`
2. 解析 `identity`/`dependencies`/`extends`/`overrides`
3. 使用 `PluginProvider` + `resolvelib` 进行依赖排序
4. 若无 `api.yaml`，调用 `builder.build_package_from_source`
5. 从 `api.yaml` 注册 Action/Service；加载 `hooks.py`

## 依赖处理
- 对 plan 插件会检查 `requirements.txt`
- `DependencyManager` 可自动安装缺失依赖（受 `config.yaml` 控制）

## 关键数据
- `plugin_registry`: 所有已发现插件
- `loaded_plugin_ids`: 成功加载的插件列表

---
# 核心模块: `plugin_provider.py`

## 概览
`PluginProvider` 是 `resolvelib` 的适配层，让依赖解析器理解 Aura 的插件模型。

## 作用
- 将 `plugin_registry` 转为可解析的候选集合
- 返回插件依赖（来自 `plugin.yaml.dependencies`）
- 与 `TopologicalSorter` 共同决定加载顺序

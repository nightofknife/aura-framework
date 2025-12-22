---
# 核心模块: `plan_manager.py`

## 概览
`PlanManager` 负责加载所有 Plan，并为每个 Plan 创建对应的 `Orchestrator`。

## 初始化流程
1. 调用 `PluginManager.load_all_plugins()`
2. 遍历所有 `plugin_type == plan` 的插件
3. 为每个 Plan 创建 `Orchestrator`
4. 若存在 `states_map.yaml`，创建 `StatePlanner` 并注入

## 对外接口
- `initialize()` 完成完整加载
- `get_plan(name)` / `list_plans()` 查询已加载 Plan

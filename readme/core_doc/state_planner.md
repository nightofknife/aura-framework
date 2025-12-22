---
# 核心模块: `state_planner.py`

## 概览
基于 `states_map.yaml` 的状态规划器，用于在任务执行前保证系统处于目标初始状态。

## states_map.yaml 结构
- `states`: 状态定义
  - `check_task`: 用于判断当前状态的任务
  - `priority` / `can_async`
- `transitions`: 状态转移
  - `from`, `to`, `cost`, `transition_task`

## 工作流程
1. `determine_current_state` 并行/串行执行 `check_task`
2. 使用 Dijkstra 计算最小成本路径
3. 依次执行 `transition_task`，必要时重试

## 触发方式
任务的 `meta.requires_initial_state` 指定目标状态，由 `ExecutionManager` 调用。

---
# 核心模块: `state_store_service.py`

## 概览
`StateStoreService` 提供跨任务的持久化状态存储（JSON 文件）。

## 配置
`config.yaml`:
```yaml
state_store:
  type: file
  path: ./project_state.json
```

## API
- `get(key, default=None)`
- `set(key, value)` (立即持久化)
- `delete(key)`
- `get_all_data()`

## 相关 Action
`packages/aura_core/state_actions.py` 定义了 `state.set` / `state.get` / `state.delete`。
如需在任务中使用，请确保该模块被加载并注册为 Action。

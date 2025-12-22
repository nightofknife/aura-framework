---
# 核心模块: `task_loader.py`

## 概览
从 Plan 的 `tasks/` 目录加载任务定义，带 TTL 缓存并支持热重载。

## 规则
- `tasks/<name>.yaml` 支持单文件多任务
- 任务 ID 由路径 + key 组成
- 自动填充 `execution_mode` 默认值

## 关键方法
- `get_task_data(task_name_in_plan)`
- `get_all_task_definitions()`
- `reload_task_file(path)`：清除缓存并重新加载

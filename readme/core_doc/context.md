---
# 核心模块: `context.py`

## 概览
`ExecutionContext` 是任务执行期间的数据容器，支持分支 fork/merge，用于 DAG 并行场景。

## 数据结构
- `initial`: 触发器或调度传入的初始数据
- `inputs`: API 或 `aura.run_task` 传入的输入参数
- `nodes`: 已执行节点结果
- `loop`: 循环节点的 `item` / `index`
- `cid`: 当前任务追踪 ID

## 关键方法
- `fork()` / `merge()`：分支隔离与合并
- `add_node_result(node_id, result)`：写入节点结果
- `set_loop_variables(...)`：设置循环变量

## 节点结果结构
`nodes.<id>` 里包含 `run_state`，并可能包含 `output` 或命名输出字段。

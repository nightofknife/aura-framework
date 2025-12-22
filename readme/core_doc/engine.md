---
# 核心模块: `engine.py`

## 概览
`ExecutionEngine` 执行单个 Task：解析 `steps` 为 DAG，按依赖与条件并发调度节点。

## 依赖表达式 `depends_on`
支持以下结构：
- 字符串：依赖该节点成功
- 列表：所有成员为真才执行
- 字典：
  - `and` / `or` / `not`
  - `{node_id: "success|failed|running|skipped"}` 按状态判断
  - `"when: <expression>"` 运行时条件（Jinja 渲染，结果取布尔值）

## 节点执行
- 节点定义包含 `action` 与可选 `params`
- 具体执行交由 `ActionInjector` 完成

## 循环 `loop`
- `for_each`: list/dict
- `times`: 整数次数
- `while`: 表达式，使用模板渲染

## 重试
支持简写与完整写法：
- `retry: 3`
- `retry_delay: 2`
- `retry_on: ["TimeoutError", "requests.exceptions.ConnectionError"]`
- `retry_condition: "{{ result.status_code >= 500 }}"`
或：
```yaml
retry:
  count: 3
  delay: 1
  on_exception: [...]
  condition: "..."
```
`retry_condition` 可使用 `result` 与上下文变量。

## 输出
- 定义 `outputs` 时，按模板生成命名输出
- 未定义 `outputs` 时，默认写入 `output`
- 节点结果写入 `ExecutionContext.nodes`

## 事件回调
`event_callback` 会发布 `node.started` / `node.succeeded` / `node.failed` / `node.finished`。

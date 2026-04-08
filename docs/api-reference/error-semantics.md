# 错误语义

本页说明当前 REST API 的主要状态码和错误来源。

## 1. `202 Accepted`

典型用于：

- `POST /tasks/dispatch`
- `POST /tasks/dispatch/batch`
- `POST /tasks/dispatch/schedule/{item_id}`

语义：

- 请求已被接受
- 不代表 task 已经执行完成
- 在 scheduler 未启动时，任务可能只是在 pre-start buffer 中排队

## 2. `400 Bad Request`

典型来源：

- `task_ref` 非法
- plan/task 输入校验失败
- schedule item 不存在或无法排队
- file reload 过程中出现业务错误
- 删除 plan 失败

## 3. `404 Not Found`

典型来源：

- plan 不存在
- 文件不存在
- task-load-errors 查询时 plan 不存在

## 4. 任务定义损坏

task 文件损坏通常不会在 plan 装载阶段把整个 plan 阻断，而是进入 `task-load-errors`。

损坏来源包括：

- YAML 解析失败
- schema 校验失败
- 已移除语法仍在使用
- `aura.run_task` 参数不合法
- `depends_on` 语法非法

调度这类 task 时，常见外部表现是：

- 任务找不到
- 或输入校验/调度报 `400`

## 5. 空对象返回

`GET /system/metrics` 在 scheduler 尚未创建时返回 `{}`，这不是错误，而是当前实现约定。

## 6. 调试建议

- 先看 HTTP 状态码
- 再看 `detail` 或 `message`
- 再看 [REST API 参考](./rest-api.md) 和 [响应模型](./response-models.md)
- 若涉及 task 文件问题，再看 `GET /plans/{plan_name}/task-load-errors`

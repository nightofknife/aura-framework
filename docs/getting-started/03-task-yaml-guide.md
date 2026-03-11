# 任务 YAML 结构详解（当前语法）

本文档是 Aura 当前版本的任务编写规范，按运行时真实实现整理。

---

## 1. 任务文件组织

任务文件默认放在方案包的 `tasks/` 目录（或 `manifest.yaml` 的 `task_paths` 指定目录）：

```text
plans/MyPlan/
├── manifest.yaml
└── tasks/
    ├── login.yaml
    └── combat/
        └── farm.yaml
```

支持两种 YAML 结构：

### A. 单任务文件（推荐）

```yaml
# tasks/login.yaml
meta:
  title: 登录
steps:
  open_page:
    action: log
    params:
      message: "open"
```

该文件的任务键默认是文件名 `login`。

### B. 多任务文件

```yaml
# tasks/auth.yaml
login:
  meta:
    title: 登录
  steps:
    s1:
      action: log
      params: { message: "login" }

logout:
  meta:
    title: 登出
  steps:
    s1:
      action: log
      params: { message: "logout" }
```

---

## 2. `task_ref` 规范（仅此一种）

`aura.run_task` 只接受标准格式：

- `tasks:<path>.yaml`
- `tasks:<path>.yaml:<task_key>`

示例：

- `tasks:login.yaml`
- `tasks:combat:farm.yaml`
- `tasks:auth.yaml:logout`

不支持：

- 斜杠写法（如 `tasks/auth/login`）
- `task_name` 参数
- 跨包调用（当前 canonical `task_ref` 模式下禁用）

---

## 3. 顶层结构

一个任务定义包含 3 个核心区块：

```yaml
my_task:
  meta: {}
  steps: {}
  returns: {}
```

> 单任务文件可省略外层 `my_task:`，直接写 `meta/steps/returns`。

---

## 4. `meta` 字段

常用字段：

```yaml
meta:
  title: "任务标题"
  description: "任务描述"
  entry_point: true
  concurrency: exclusive
  inputs:
    - name: username
      type: string
      required: true
```

- `title`：任务显示名
- `description`：任务说明
- `entry_point`：是否作为入口任务（TUI 会读取）
- `concurrency`：并发策略（`None | str | dict`，由 TaskLoader 规范化）
- `inputs`：输入参数 schema（详见下一节）

---

## 5. `meta.inputs` 输入定义

`inputs` 必须是列表；每项至少包含 `name`，推荐写 `type`。

支持类型：

- `string`
- `number`
- `boolean`
- `list`
- `dict`
- `list<type>`（语法糖，如 `list<string>`）

示例：

```yaml
meta:
  inputs:
    - name: mode
      type: string
      enum: ["easy", "hard"]
      default: "easy"

    - name: retry_count
      type: number
      min: 0
      max: 10
      default: 3

    - name: tags
      type: list<string>
      count: "1-5"

    - name: profile
      type: dict
      properties:
        uid:
          type: string
          required: true
        debug:
          type: boolean
          default: false
```

校验规则要点：

- 仅允许声明过的输入名；多余输入会报错
- `dict` 默认不允许额外字段（只允许 `properties` 中声明的键）
- `count` 语法糖支持 `3`、`<=5`、`>=2`、`1-3`、`[1,3]`
- `options` 会被归一化为 `enum`
- 不支持 `integer/array/object`（请改用 `number/list/dict`）

---

## 6. `steps` 字段

`steps` 是字典，键是步骤 ID（节点 ID）：

```yaml
steps:
  step_id:
    action: log
    params:
      message: "hello"
```

常用步骤字段：

- `action`：动作名（必填）
- `params`：动作参数
- `outputs`：输出映射
- `depends_on`：依赖表达式
- `when`：步骤条件（字符串模板）
- `loop`：循环执行配置
- `retry` / `on_exception` / `on_result`：重试配置
- `timeout` / `timeout_sec`：步骤超时
- `step_note`：步骤说明（字符串）

禁止字段：

- `label`（已移除）
- `goto`（已移除）

---

## 7. `depends_on` 语法

### 基本依赖

```yaml
depends_on: fetch_data
```

### 列表（等价于 all）

```yaml
depends_on: [a, b, c]
```

### 逻辑组合

```yaml
depends_on:
  all: [a, b]
```

```yaml
depends_on:
  any: [a, b]
```

```yaml
depends_on:
  none: [a, b]
```

### 按状态依赖

```yaml
depends_on:
  fetch_data: "success|failed"
```

支持状态：`success`、`failed`、`running`、`skipped`。

不支持：

- `and/or/not`
- `depends_on` 内联 `when:...`

---

## 8. `when` 条件执行

`when` 必须是字符串模板，渲染后转布尔值。

```yaml
steps:
  check:
    action: log
    params: { message: "check" }

  run_if_needed:
    action: log
    depends_on: check
    when: "{{ inputs.enabled }}"
    params:
      message: "enabled"
```

---

## 9. `loop` 循环

### for_each

```yaml
loop:
  for_each: "{{ inputs.items }}"
  parallelism: 4
```

- 支持列表或字典
- 循环变量：`loop.item`、`loop.index`

### times

```yaml
loop:
  times: 3
  parallelism: 2
```

### while

```yaml
loop:
  while: "{{ nodes.check.output }}"
  max_iterations: 100
```

> `while` 未配置 `max_iterations` 时默认 1000。

---

## 10. 重试与超时

### 推荐重试写法

```yaml
on_exception:
  retry: 3
  retry_on: ["TimeoutError"]
  delay: 1

on_result:
  retry_when: "{{ result.status != 200 }}"
  max_retries: 2
  delay: 1
```

### 兼容写法（仍可用）

```yaml
retry: 3
retry_delay: 1
retry_on: ["TimeoutError"]
retry_condition: "{{ result.status != 200 }}"
```

### 超时

```yaml
timeout: 30
```

或：

```yaml
timeout_sec: 30
```

---

## 11. 输出与返回值

### `outputs`（步骤输出映射）

```yaml
steps:
  query:
    action: http.get
    params: { url: "https://example.com" }
    outputs:
      code: "{{ result.status }}"
```

- 配置了 `outputs`：按模板写入节点结果
- 未配置 `outputs`：动作返回值写入 `nodes.<step>.output`

### `returns`（任务返回）

```yaml
returns:
  ok: "{{ nodes.query.run_state.status == 'SUCCESS' }}"
  status_code: "{{ nodes.query.code }}"
```

- 存在 `returns`：渲染后作为 `user_data`
- 不写 `returns`：`user_data` 默认为 `true`

---

## 12. 子任务调用（`aura.run_task`）

```yaml
steps:
  call_sub_task:
    action: aura.run_task
    params:
      task_ref: "tasks:combat:farm.yaml"
      inputs:
        times: 3
```

要求：

- 必须使用 `task_ref`
- `inputs` 必须是对象
- 只允许当前方案包内任务

---

## 13. 完整示例

```yaml
meta:
  title: 刷图任务
  entry_point: true
  inputs:
    - name: runs
      type: number
      default: 3
      min: 1

steps:
  prepare:
    action: log
    params:
      message: "prepare"
    step_note: "准备阶段"

  run_loop:
    action: aura.run_task
    depends_on: prepare
    loop:
      times: "{{ inputs.runs }}"
      parallelism: 1
    params:
      task_ref: "tasks:combat:single_run.yaml"
      inputs:
        idx: "{{ loop.index }}"
    outputs:
      sub_result: "{{ result }}"

  finish:
    action: log
    depends_on:
      run_loop: "success|failed"
    params:
      message: "done"

returns:
  run_status: "{{ nodes.finish.run_state.status }}"
```

---

## 14. 常见错误速查

- `task_ref` 使用斜杠路径：改为 `tasks:...yaml[:task_key]`
- `aura.run_task` 传 `task_name`：改为 `task_ref`
- `depends_on` 使用 `and/or/not`：改为 `all/any/none`
- `depends_on` 内写 `when:`：改为步骤级 `when`
- 使用 `goto/label`：改为 `step_note` + 依赖/条件建模

---

**上一章**: [核心概念详解](./02-core-concepts.md)  
**下一章**: [任务流程控制](./04-task-control-flow.md)

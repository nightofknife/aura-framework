# 4. 理解任务语法

Aura 的任务是使用 YAML 文件定义的，这种格式既易于人类阅读，也易于机器解析。每个任务文件都由三个核心部分组成：`meta`、`inputs` 和 `steps`。

## 1. 任务文件基本结构

一个典型的 Aura 任务文件 (`.yaml`) 结构如下：

```yaml
meta:
  # 关于任务的元数据
  ...

inputs:
  # 任务执行前需要的输入参数
  ...

steps:
  # 任务要执行的具体步骤
  ...
```

---

## 2. `meta` 块：任务的元数据

`meta` 块用于定义任务的描述性信息，这些信息会显示在 Web UI 中，帮助用户理解任务的用途。

*   `title` (必需): 任务的标题，应简洁明了。
*   `description` (可选): 对任务功能的详细描述。

**示例：**

```yaml
meta:
  title: "发送欢迎邮件"
  description: "此任务向新注册的用户发送一封欢迎邮件。"
```

---

## 3. `inputs` 块：定义输入参数

`inputs` 块定义了任务在执行前可以接收的参数。它是一个列表，每个列表项代表一个输入参数。

每个输入参数可以包含以下字段：

*   `name` (必需): 参数的名称，在 `steps` 中通过 `{{ inputs.name }}` 来引用。
*   `type` (必需): 参数的数据类型，目前支持 `string`, `integer`, `boolean`, `float`, `list`, `dict`。
*   `required` (可选): 一个布尔值，指定此参数是否为必需。默认为 `false`。
*   `default` (可选): 参数的默认值。如果 `required` 为 `false` 且用户未提供值，将使用此默认值。
*   `description` (可选): 参数的描述，会显示在 UI 上，用于提示用户。

**示例：**

```yaml
inputs:
  - name: "user_email"
    type: "string"
    required: true
    description: "接收邮件的用户的电子邮箱地址。"

  - name: "send_delay_seconds"
    type: "integer"
    required: false
    default: 0
    description: "发送邮件前等待的秒数。"
```

---

## 4. `steps` 块：定义执行步骤

`steps` 块是任务的核心，它定义了要按顺序执行的一系列操作。它是一个列表，每个列表项代表一个执行步骤。

每个步骤包含以下字段：

*   `name` (必需): 步骤的唯一名称，用于在日志中标识该步骤。
*   `action` (必需): 要调用的 Action 的唯一标识符。格式通常为 `<plan_name>.<action_name>`。例如，`core.log` 调用 `core` Plan 中的 `log` Action。
*   `params` (可选): 一个字典，包含了要传递给 Action 的参数。

**示例：**

```yaml
steps:
  - name: "wait_before_sending"
    action: "core.sleep"
    params:
      seconds: "{{ inputs.send_delay_seconds }}"

  - name: "send_the_email"
    action: "email.send"
    params:
      recipient: "{{ inputs.user_email }}"
      subject: "欢迎来到 Aura！"
      body: "感谢您的注册。"
```

---

## 5. 变量引用语法 `{{ ... }}`

在 Aura 的任务文件中，你可以使用双花括号 `{{ ... }}` 语法来动态地插入变量。这是一种强大的模板功能，主要用于 `steps` 的 `params` 部分。

**引用输入变量**:

你可以通过 `inputs` 关键字来访问在 `inputs` 块中定义的任何参数。

```yaml
# 假设 inputs 中定义了 user_name
steps:
  - name: "log_greeting"
    action: "core.log"
    params:
      message: "Hello, {{ inputs.user_name }}!"
```

在任务执行时，`{{ inputs.user_name }}` 会被替换为用户为 `user_name` 参数提供的实际值。在后续的章节中，你还会学习如何引用更复杂的变量，例如上一步的输出或全局的上下文变量。

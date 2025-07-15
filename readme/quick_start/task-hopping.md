

#### **8. 任务间的跳转与调用 (Task Hopping)**


# **高级流程控制：任务间的跳转与调用**

随着自动化方案变得复杂，将所有逻辑都放在一个巨大的任务文件中会变得难以维护。Aura 鼓励您将功能拆分成独立的、可复用的任务，并通过强大的跳转和调用指令将它们串联起来。

Aura 提供了三种主要的任务流转机制：`run_task`，`go_step` 和 `go_task`。

### **`run_task`: 调用并返回 (像函数调用)**

`run_task` 是最常用的任务间交互方式。它会暂停当前任务的执行，去运行一个指定的“子任务”。当子任务执行完毕后，程序流程会**返回**到父任务，并从 `run_task` 的下一步继续执行。这完全就像在编程中调用一个函数。

**使用场景**:
*   封装可复用的功能模块，如“登录”、“登出”、“数据抓取”等。
*   保持主任务的逻辑清晰，将实现细节隐藏在子任务中。

**参数**:
*   `task_name`: `str` - 要调用的子任务的完整ID (例如 `MyPlan/tasks/login/main`)。
*   `pass_params` (可选): `dict` - 一个字典，用于向子任务的上下文中传递参数。
*   `output_to` (可选): `str` - 子任务可以定义 `outputs` 来返回值。`output_to` 用于接收这些返回值。

**示例**:

**父任务 (`main.yaml`)**:
```yaml
- name: "调用登录子任务"
  action: run_task
  params:
    task_name: "MyPlan/tasks/login_module/login"
    pass_params:
      username: "aura_user"
      password: "secure_password"
  output_to: "login_result"

- name: "检查登录结果"
  action: assert_condition
  params:
    condition: "{{ login_result.success }}"
```

**子任务 (`login_module.yaml`)**:
```yaml
login:
  # 注意，子任务通常不需要是 entry_point
  steps:
    - name: "输入用户名"
      action: type_text
      params:
        text: "{{ username }}" # 从 pass_params 接收
    - name: "输入密码"
      # ...
  outputs: # 定义子任务的返回值
    success: "{{ True }}" # 这里应为真实的是否成功逻辑
    login_time: "{{ some_time_variable }}"
```

### **`go_task`: 跳转不返回 (像状态转移)**

`go_task` 会**立即中止**当前任务的执行，并将控制权**永久地**转移给一个新的任务。程序流程**不会**返回到原任务。

**使用场景**:
*   构建状态机。例如：`初始化状态` -> `处理中状态` -> `完成状态`，每个状态都是一个任务。
*   在任务发生严重错误后，跳转到一个统一的“错误处理”任务。

**示例**:
```yaml
steps:
  - name: "执行一些操作"
    # ...
  - name: "如果发生严重错误"
    when: "{{ something_went_wrong }}"
    go_task: "MyPlan/tasks/error_handling/report_error" # 直接跳转，不返回

  - name: "操作成功，跳转到下一步"
    go_task: "MyPlan/tasks/processing/step_two"
```

### **`go_step`: 任务内跳转 (像 goto)**

`go_step` 是一个任务内部的跳转指令，它允许你直接跳到当前任务中另一个带有 `id` 的步骤。

**使用场景**:
*   跳过某些初始化步骤。
*   在循环逻辑中实现 `continue` 或 `break` 的效果。
*   **注意**: 过度使用 `go_step` 会让任务逻辑变得混乱，难以追踪。请优先考虑使用 `if/then/else` 和 `while` 循环。

**示例**:
```yaml
steps:
  - id: "initialization"
    name: "执行一些初始化操作"
    # ...

  - name: "检查是否需要跳过初始化"
    when: "{{ context_already_initialized }}"
    go_step: "main_logic" # 跳转到 id 为 main_logic 的步骤

  - name: "执行一些只有第一次才运行的步骤"
    # ...

  - id: "main_logic"
    name: "这里是主要逻辑的开始"
    # ...
```


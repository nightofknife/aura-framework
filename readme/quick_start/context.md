
---

### **第二部分：核心概念 (Core Concepts) **

#### **5. 上下文 (Context)**


---

# **核心概念：上下文 (Context)**

如果您已经编写过任何简单的程序，您一定知道“变量”——它们是用来临时存储和传递数据的地方。在 Aura 中，这个“变量存储区”就是**上下文 (Context)**。

您可以将上下文想象成一个任务专属的、临时的**智能记事本**。当任务开始时，Aura 会发给它一本空白的记事本；在任务执行的每一步，都可以往上面**写入**信息，或者**读取**之前记下的信息；当任务结束时，这本记事本通常会被销毁。

上下文是让您的自动化任务变得“智能”和“动态”的关键。没有它，每个步骤都将是孤立的，无法相互协作。

### **写入数据到上下文: `output_to`**

将数据写入上下文最常见的方式，是通过在步骤中使用 `output_to` 关键字。

当一个 Action 执行完毕后，它通常会有一个**返回值**（例如 `find_image` 的返回值是它找到的图像信息）。`output_to` 告诉 Aura：“请把这个返回值存到我的记事本里，并给它起个名字”。

让我们看一个实际的例子：

```yaml
steps:
  - name: "查找用户名输入框"
    action: find_image
    params:
      template: "images/username_field.png"
    # 核心在这里:
    output_to: "username_input_info"

  # 在这一步之后，上下文中就有了一个名为 "username_input_info" 的变量。
  # 它存储了 find_image Action 的所有返回信息。
```

### **从上下文中读取数据: Jinja2 模板 `{{ ... }}`**

一旦数据被记在了“记事本”上，我们就可以在后续的步骤中随时读取它。Aura 使用了强大而简洁的 **Jinja2 模板语法**来实现这一点。

您只需将变量名放在双大括号 `{{ }}` 中，Aura 就会在执行时自动将其替换为真实的值。

继续上面的例子，我们找到了输入框，现在需要点击它并输入文字：

```yaml
steps:
  - name: "查找用户名输入框"
    action: find_image
    params:
      template: "images/username_field.png"
    output_to: "username_input_info"

  - name: "断言是否找到了输入框"
    action: assert_condition
    params:
      # 读取 username_input_info 变量的 found 属性
      condition: "{{ username_input_info.found }}"
      message: "错误：在屏幕上找不到用户名输入框！"

  - name: "点击输入框的中心点"
    # 只有在上一部断言成功后才会执行
    action: click
    params:
      # 读取 username_input_info 变量的 center_point 属性
      # .center_point 是一个坐标元组 (x, y)
      # [0] 表示取元组的第一个元素 (x坐标)
      x: "{{ username_input_info.center_point[0] }}"
      y: "{{ username_input_info.center_point[1] }}"

  - name: "输入用户名"
    action: type_text
    params:
      # 直接使用一个在任务开始前就定义好的变量
      text: "{{ login_username }}"
```

在这个例子中，我们：
1.  将 `find_image` 的复杂结果存入 `username_input_info`。
2.  通过 `{{ username_input_info.found }}` 读取其布尔值属性来进行判断。
3.  通过 `{{ username_input_info.center_point[0] }}` 读取其元组属性来获取精确的点击坐标。
4.  通过 `{{ login_username }}` 读取一个可能在任务启动时传入的简单变量。

### **上下文的生命周期与隔离**

理解上下文的生命周期非常重要：

*   **创建**: 当一个任务开始执行时，Aura 会为其创建一个全新的上下文。
*   **隔离 (子任务)**: 如果任务A调用了子任务B (`run_task`)，子任务B会得到一个**全新的、空白的**上下文。父任务A的数据**不会**自动传递给子任务B。这种设计保证了子任务的纯粹性和独立性，避免了意外的数据污染。您需要通过 `run_task` 的 `pass_params` 机制来**显式地**将所需数据传递给子任务。
*   **销毁**: 当任务执行完毕（或失败、或中止）后，它所对应的上下文就会被销毁，其中的所有临时数据都会丢失。

### **超越临时：持久化上下文**

“任务结束后上下文就被销毁”，这个规则在99%的情况下都很好。但有时，我们确实需要在**多次任务运行之间**共享数据，例如：
*   保存上一次成功处理的订单号，以便下次从这个订单号继续。
*   存储一个需要长期有效的 API 认证 Token。

为此，Aura 提供了**持久化上下文 (Persistent Context)** 的功能。

在您的方案文件夹（例如 `MyFirstPlan/`）中，您可以创建一个名为 `persistent_context.json` 的文件。在**每次任务开始时**，Aura 会自动读取这个文件，并将其中的所有键值对**加载到当前任务的上下文中**。

这意味着，您可以像访问普通上下文变量一样，无缝地访问这些持久化数据。

**工作流程**:
1.  **手动创建文件**: 在 `plans/MyFirstPlan/` 目录下创建一个 `persistent_context.json` 文件，内容如下：
    ```json
    {
      "auth_token": "some_initial_or_expired_token",
      "last_processed_id": 1000
    }
    ```
2.  **在任务中直接使用**:
    ```yaml
    - name: "使用已加载的Token"
      action: http.request # 假设的Action
      params:
        url: "https://api.example.com/data"
        headers:
          Authorization: "Bearer {{ auth_token }}" # 直接使用，无需特殊前缀
    ```
3.  **更新并保存**: 要更新这些值，您可以使用特定的 Action。
    ```yaml
    - name: "获取新的认证Token"
      action: http.request
      params:
        url: "https://api.example.com/token"
      output_to: "api_response"

    - name: "更新长期上下文中的Token"
      action: set_persistent_value
      params:
        key: "auth_token"
        value: "{{ api_response.json.token }}"

    - name: "将所有更改写入文件"
      action: save_persistent_context
    ```

这个流程使得处理需要跨任务、跨次运行的数据变得简单而直观。

---



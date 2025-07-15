
---

### **第三部分：高级流程控制 (Advanced Flow Control)**

这一部分将全面介绍 Aura 框架中用于构建复杂、非线性任务逻辑的所有工具。

---

#### **6. 条件执行 (Conditional Execution)**


# **高级流程控制：条件执行**

现实世界的自动化任务充满了“如果...那么...”的逻辑。例如，“如果找到了登录按钮，就点击它；否则，就刷新页面”。Aura 提供了强大的条件执行能力，让您的任务能够根据实时情况做出决策。

### **简单条件: `when`**

`when` 是在单个步骤上添加执行条件的最简单方式。它接受一个返回布尔值 (`True` 或 `False`) 的表达式。只有当表达式的值为 `True` 时，该步骤才会被执行。

```yaml
steps:
  - name: "查找登录按钮"
    action: find_image
    params:
      template: "images/login_button.png"
    output_to: "login_button_result"

  - name: "如果找到了，就点击它"
    # 只有当 login_button_result.found 为 True 时，这一步才会执行
    when: "{{ login_button_result.found }}"
    action: click
    params:
      x: "{{ login_button_result.center_point[0] }}"
      y: "{{ login_button_result.center_point[1] }}"
```

`when` 非常适合用于控制单个可选步骤的执行。

### **完整分支逻辑: `if / then / else`**

当您需要处理更复杂的“如果...那么...否则...”逻辑时，可以使用 `if` 块。这是一个结构化的步骤，它包含一个条件和两个可执行的步骤列表 (`then` 和 `else`)。

*   **`if`**: 定义一个条件表达式。
*   **`then`**: 如果条件为 `True`，则执行这个块里的所有步骤。
*   **`else` (可选)**: 如果条件为 `False`，则执行这个块里的所有步骤。

**示例：**

假设我们需要检查用户是否已登录。如果屏幕上有“退出”按钮，说明已登录，我们就在日志中记录一条信息；否则，我们就执行登录操作。

```yaml
- name: "检查是否已登录"
  action: find_text
  params:
    text_to_find: "退出"
  output_to: "logout_button_result"

- name: "根据登录状态执行不同操作"
  if: "{{ logout_button_result.found }}"  # 条件
  then:
    - name: "记录已登录状态"
      action: log
      params:
        message: "用户当前已登录。"
  else:
    - name: "执行登录操作"
      action: run_task # 调用另一个任务
      params:
        task_name: "MyPlan/tasks/login_flow/main" # 假设登录流程被封装在一个子任务里
    - name: "登录后再次验证"
      action: assert_condition
      params:
        condition: "{{ True }}" # 示例
```

**关键点**:
*   `then` 和 `else` 后面跟的都是一个标准的**步骤列表**，您可以在里面定义任意多个、任意复杂的步骤，甚至可以嵌套另一个 `if` 块。
*   `else` 块是完全可选的。如果您只想在条件满足时执行某些操作，可以省略 `else`。不过如果不用 `else`为什么不用`when`呢。

---




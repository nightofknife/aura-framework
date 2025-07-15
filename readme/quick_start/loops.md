
#### **7. 循环 (Loops)**



# **高级流程控制：循环**

循环是自动化的核心，它让您能够重复执行一系列操作，直到满足特定条件为止。Aura 支持两种功能强大的循环结构：`for` 循环和 `while` 循环。

### **遍历列表: `for` 循环**

当您需要对一个列表（或任何可迭代对象）中的每一个元素执行相同的操作时，`for` 循环是最佳选择。例如，处理一个文件列表、遍历从API获取的数据行等。

`for` 循环的结构包含三个部分：
*   **`for.in`**: 指定要遍历的列表。这通常是一个来自上下文的变量。
*   **`for.as`**: 指定一个变量名。在每次循环中，当前遍历到的元素会被赋值给这个变量。
*   **`do`**: 一个步骤列表，定义了在每次循环中要执行的操作。

**示例：**

假设我们从一个 Action 中获取了一个文件名列表，现在需要逐个打印它们。

```yaml
- name: "假设我们获取了一个文件列表"
  action: set_variable
  params:
    name: "file_list"
    value:
      - "report_2023_01.csv"
      - "report_2023_02.csv"
      - "report_2023_03.csv"

- name: "遍历并处理每个文件"
  for:
    in: "{{ file_list }}"
    as: "current_file"
  do:
    - name: "打印当前文件名"
      action: log
      params:
        message: "正在处理文件: {{ current_file }}"
    - name: "模拟处理文件"
      action: sleep
      params:
        seconds: 1
```

**关键点**:
*   在 `do` 块内，您可以通过 `for.as` 定义的变量名（本例中是 `current_file`）来访问当前循环的元素。
*   当 `for` 循环结束后，`for.as` 定义的变量会自动从上下文中移除，以保持环境干净。

### **条件循环: `while` 循环**

当您需要在一个条件为 `True` 的情况下持续执行某些操作时，应使用 `while` 循环。这在需要“等待”某个状态达成时非常有用，例如等待一个文件被创建、等待一个元素在网页上出现等。

`while` 循环的结构包含两个主要部分：
*   **`while`**: 一个条件表达式。只要此表达式的值为 `True`，循环就会继续。
*   **`do`**: 一个步骤列表，定义了在每次循环中要执行的操作。
*   **`max_loops` (可选, 默认 1000)**: 为了防止无限循环导致程序卡死，您可以设置一个最大循环次数。

**示例：**

让我们实现一个经典的“等待某个图像出现”的逻辑，最长等待30秒。

```yaml
- name: "初始化等待计时器"
  action: set_variable
  params:
    name: "timeout_expired"
    value: false

- name: "启动一个30秒后会改变计时器状态的异步任务" # 这是一个高级用法，这里用 set_variable 模拟
  action: run_task
  params:
    task_name: "MyPlan/utils/set_flag_after_30s"
    pass_params:
      flag_name: "timeout_expired"

- name: "等待“加载完成”的标志出现，或直到超时"
  while: "{{ not load_result.found and not timeout_expired }}" # 循环条件
  max_loops: 60 # 设置一个合理的上限
  do:
    - name: "查找“加载完成”的图像"
      action: find_image
      params:
        template: "images/loading_complete.png"
      output_to: "load_result"
      continue_on_failure: true # 很重要，确保查找失败时循环能继续
    - name: "如果没找到，等待0.5秒再试"
      when: "{{ not load_result.found }}"
      action: sleep
      params:
        seconds: 0.5
```



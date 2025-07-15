
---

### **第二部分：核心概念 (Core Concepts) - 最终版**

#### **4. 行为 (Actions)**

---

# **核心概念：行为 (Actions)**

如果说任务是“菜谱”，那么“行为(Action)”就是菜谱中每一个具体的**动作指令**，例如“切菜”、“倒油”、“翻炒”。它是 Aura 框架中可以执行的、不可再分的最小原子操作。

每个 `step` 的核心都是一个 Action。它告诉 Aura 在这一步具体要做什么。

### **Action 的剖析**

让我们看一个典型的 Action 步骤：

```yaml
- name: "点击登录按钮"
  action: find_text_and_click
  params:
    text_to_find: "登录"
  output_to: "login_click_success"
```

*   **`name` (可选, 推荐)**: 步骤的可读名称。它会显示在日志中，让您清楚地知道任务执行到了哪一步。一个好的命名习惯能极大地提升任务的可维护性。

*   **`action` (必需)**: Action 的唯一注册名称。这是一个简单的字符串，例如 `find_text_and_click`, `type_text`, `run_python`。它直接对应到一个后台的 Python 函数。

*   **`params` (可选)**: 一个字典，包含了执行这个 Action 所需的所有参数。

*   **`output_to` (可选)**: 一个字符串，指定一个上下文变量名。此 Action 的**返回值**将会被存入这个变量中，供后续步骤使用。

---

### **核心 Action 库**

Aura 内置了一系列核心 Action，以满足常见的自动化需求。下面是它们的详细分类和用法说明。

---

### **类别一：流程控制与数据处理**

这类 Action 负责控制任务的执行流程和处理数据，是构建逻辑的基础。

#### **`log`**
在框架的日志系统中记录一条消息。这是调试任务最常用的工具。

*   **参数**:
    *   `message` (必需): `str` - 要打印的信息内容。支持 Jinja2 模板。
    *   `level` (可选, 默认 `'info'`): `str` - 日志的级别。可选值为 `'info'`, `'debug'`, `'warning'`, `'error'`。
*   **示例**:
    ```yaml
    - name: "记录不同级别的日志"
      action: log
      params:
        message: "警告：API 密钥即将过期，剩余 {{ api_days_left }} 天。"
        level: "warning"
    ```

#### **`run_python`**
在受控环境中执行一小段 Python 代码字符串，并可以返回结果。

*   **参数**:
    *   `code` (必需): `str` - 要执行的 Python 代码字符串。
*   **上下文交互**:
    *   在代码中，你可以通过一个名为 `ctx` 的字典来访问和修改当前任务的上下文。例如：`ctx['my_var'] = 123` 或 `print(ctx['some_var'])`。
*   **返回值**:
    *   代码的最后一条表达式的值或 `return` 语句的值。
*   **示例**:
    ```yaml
    - name: "处理字符串并存回上下文"
      action: run_python
      params:
        code: |
          # 从上下文中读取 full_name
          name = ctx['full_name']
          # 处理后，创建一个新变量
          ctx['first_name'] = name.split(' ')[0]
          # 返回处理结果
          return len(name)
      output_to: "name_length"
    ```

#### **`sleep`**
暂停任务执行指定的秒数。

*   **参数**:
    *   `seconds` (必需): `float` - 要暂停的秒数。
*   **示例**:
    ```yaml
    - name: "等待3.5秒让页面加载"
      action: sleep
      params:
        seconds: 3.5
    ```

#### **`set_variable`**
在当前任务的上下文中显式地设置或覆盖一个变量。

*   **参数**:
    *   `name` (必需): `str` - 要设置的变量名。
    *   `value` (必需): `any` - 要设置的值。
*   **示例**:
    ```yaml
    - action: set_variable
      params:
        name: "retry_count"
        value: 0
    ```

#### **`stop_task`**
立即停止当前任务的执行。

*   **参数**:
    *   `message` (可选, 默认 `'任务已停止'`): `str` - 在日志中显示的停止原因。
    *   `success` (可选, 默认 `True`): `bool` - 任务停止时是标记为成功还是失败。
*   **示例**:
    ```yaml
    - name: "如果用户不存在则停止"
      when: "{{ not user_found }}"
      action: stop_task
      params:
        message: "错误：未在数据库中找到指定用户。"
        success: false
    ```

#### **`assert_condition`**
断言一个条件必须为真。如果为假，则立即停止任务并标记为失败。

*   **参数**:
    *   `condition` (必需): `bool` - 要断言的条件，通常是一个 Jinja2 表达式。
    *   `message` (可选, 默认 `'断言失败'`): `str` - 断言失败时显示的错误信息。
*   **示例**:
    ```yaml
    - name: "断言登录后用户名正确"
      action: assert_condition
      params:
        condition: "{{ welcome_text == '你好, Aura' }}"
        message: "页面显示的用户名不匹配！"
    ```

---

### **类别二：视觉与 OCR**

这类 Action 负责“看”屏幕，识别图像和文本。

#### **`find_image`** / **`find_all_images`**
在屏幕上查找一个或所有匹配的图像。

*   **参数**:
    *   `template` (必需): `str` - 模板图像的文件路径，相对于当前方案的根目录。例如 `'assets/button.png'`。
    *   `region` (可选): `tuple[int, int, int, int]` - 一个 `(左, 上, 宽, 高)` 的元组，用于限定查找区域。
    *   `threshold` (可选, 默认 `0.8`): `float` - 图像匹配的置信度阈值 (0.0 到 1.0)。
*   **返回值**:
    *   一个包含匹配结果的对象。关键属性是 `result.found` (布尔值) 和 `result.center_point` (坐标)。`find_all_images` 返回一个包含多个结果的列表。
*   **示例**:
    ```yaml
    - name: "查找确认按钮"
      action: find_image
      params:
        template: "images/confirm_button.png"
      output_to: "confirm_button"
    ```

#### **`find_text`** / **`recognize_all_text`**
在屏幕上查找指定的文本，或识别区域内的所有文本。

*   **参数**:
    *   `text_to_find` (必需, 仅 `find_text`): `str` - 要查找的文本。
    *   `region` (可选): `tuple[int, int, int, int]` - 限定查找区域。
    *   `match_mode` (可选, 默认 `'exact'`): `str` - 匹配模式，如 `'exact'` (完全匹配) 或 `'contains'` (包含)。
*   **返回值**:
    *   一个 OCR 结果对象。关键属性是 `result.found` (布尔值)、`result.text` (识别出的文本) 和 `result.center_point` (坐标)。
*   **示例**:
    ```yaml
    - name: "查找欢迎语"
      action: find_text
      params:
        text_to_find: "欢迎"
        match_mode: "contains"
      output_to: "welcome_message"
    ```

---

### **类别三：键鼠控制**

这类 Action 负责模拟用户的鼠标和键盘操作。

#### **`click`**
模拟鼠标点击。

*   **参数**:
    *   `x`, `y` (可选): `int` - 窗口内的点击坐标。如果未提供，则在当前鼠标位置点击。
    *   `button` (可选, 默认 `'left'`): `str` - `'left'`, `'right'`, `'middle'`。
    *   `clicks` (可选, 默认 `1`): `int` - 点击次数（例如 `2` 表示双击）。
*   **示例**:
    ```yaml
    # 点击上下文变量中存储的坐标
    - action: click
      params:
        x: "{{ confirm_button.center_point[0] }}"
        y: "{{ confirm_button.center_point[1] }}"
    ```

#### **`type_text`**
模拟键盘输入。

*   **参数**:
    *   `text` (必需): `str` - 要输入的文本。
    *   `interval` (可选, 默认 `0.01`): `float` - 每个按键之间的间隔（秒）。
*   **示例**:
    ```yaml
    - action: type_text
      params:
        text: "这是由 Aura 自动输入的密码。"
    ```

#### **`press_key`**
模拟单个按键（例如 'enter', 'ctrl', 'f5'）。

*   **参数**:
    *   `key` (必需): `str` - 要按下的键的名称。
*   **示例**:
    ```yaml
    - action: press_key
      params:
        key: "enter"
    ```

#### **`scroll`**
模拟鼠标滚轮滚动。

*   **参数**:
    *   `direction` (必需): `str` - `'up'` 或 `'down'`。
    *   `amount` (必需): `int` - 滚动的“咔哒”数。
*   **示例**:
    ```yaml
    - action: scroll
      params:
        direction: "down"
        amount: 10
    ```


---

### **类别四：复合与高级行为**

这类 Action 将多个原子操作组合起来，或者提供了更高级的封装。

#### **`find_image_and_click`** / **`find_text_and_click`**
查找一个图像或文本，如果找到，就点击它。这是两个最常用的复合 Action。

*   **参数**:
    *   与 `find_image` / `find_text` 的参数基本相同。
    *   增加了 `button` 和 `move_duration` 等点击相关参数。
*   **返回值**: `bool` - `True` 表示成功找到并点击，`False` 表示未找到。
*   **示例**:
    ```yaml
    - name: "查找并点击设置按钮"
      action: find_image_and_click
      params:
        template: "images/settings_icon.png"
        threshold: 0.9
      output_to: "settings_clicked"
    ```

#### **`wait_for_image`**
在指定时间内，周期性地查找某个图像，直到找到或超时。

*   **参数**:
    *   `template`, `region`, `threshold`: 与 `find_image` 相同。
    *   `timeout` (可选, 默认 `10.0`): `float` - 最长等待时间（秒）。
    *   `interval` (可选, 默认 `1.0`): `float` - 每次查找之间的间隔时间（秒）。
*   **返回值**: 与 `find_image` 相同。如果超时，返回一个 `found=False` 的结果。
*   **示例**:
    ```yaml
    - name: "等待“加载完成”的标志出现"
      action: wait_for_image
      params:
        template: "images/loading_complete.png"
        timeout: 30
      output_to: "load_result"
    ```

---





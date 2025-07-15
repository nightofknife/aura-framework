
---

### **第四部分：健壮性与调试 (Robustness & Debugging)**

这一部分将聚焦于如何处理预料之外的错误，以及在任务行为不符合预期时如何快速定位问题。

---

#### **9. 错误处理 (Error Handling)**


# **健壮性与调试：错误处理**

在自动化领域，我们必须接受一个事实：**错误是常态**。网络可能会抖动，应用程序可能会卡顿，UI元素可能会延迟加载。一个健壮的自动化方案不应该因为这些偶发的小问题而崩溃。Aura 提供了多种机制来优雅地处理错误，增强您任务的韧性。

### **自动重试: `retry`**

`retry` 是处理暂时性错误（如网络超时、元素未及时出现）最有效的武器。您可以在任何一个步骤上添加 `retry` 块，当该步骤执行失败时，Aura 会自动为你重新尝试。

`retry` 块包含两个参数：
*   **`count`**: `int` - 总共尝试的次数（包括第一次）。例如，`count: 3` 表示第一次执行失败后，还会再重试2次。
*   **`interval`**: `float` - 每次重试之间的等待时间（秒）。

**示例：**

假设我们点击一个按钮后，需要等待一个“操作成功”的提示图片出现。这个图片可能会有几秒的延迟。

```yaml
- name: "点击提交按钮"
  action: find_image_and_click
  params:
    template: "images/submit_button.png"

- name: "等待成功提示，最多尝试5次，每次间隔2秒"
  action: find_image
  params:
    template: "images/success_toast.png"
  retry:
    count: 5
    interval: 2.0
  output_to: "success_toast_result"

- name: "断言操作最终是否成功"
  action: assert_condition
  params:
    condition: "{{ success_toast_result.found }}"
    message: "在等待10秒后，仍未看到操作成功的提示！"
```

在这个例子中，`find_image` 步骤总共有 `5 * 2 = 10` 秒的时间来等待图片出现。只有当5次尝试全部失败后，整个步骤才会被最终标记为失败。

### **忽略失败: `continue_on_failure`**

有时候，一个步骤的失败并不影响整个任务的主流程。例如，您可能想尝试点击一个“关闭弹窗广告”的按钮，但这个广告可能并不会每次都出现。如果因为找不到这个广告按钮而让整个任务失败，那就太可惜了。

在这种情况下，您可以使用 `continue_on_failure: true`。

它告诉 Aura：“请尝试执行这个步骤。如果它成功了，很好；如果它失败了，没关系，记录一下警告就行，然后继续执行下一个步骤，不要中断整个任务。”

**示例：**

```yaml
- name: "处理主要业务逻辑"
  # ...

- name: "【可选】尝试关闭可能出现的广告弹窗"
  action: find_image_and_click
  params:
    template: "images/close_ad_button.png"
  continue_on_failure: true
  output_to: "ad_closed_result" # 即使失败，ad_closed_result 也会被设置为 False

- name: "继续执行后续的关键步骤"
  # ...
```

**`output_to` 与 `continue_on_failure` 的联动**:
根据 `engine.py` 的代码，当一个设置了 `continue_on_failure: true` 的步骤最终失败时，如果它也设置了 `output_to`，Aura 会自动将 `False` 存入指定的上下文变量中。这非常有用，因为它允许您在后续步骤中判断这个可选操作是否真的执行成功了。

```yaml
- name: "检查广告是否被成功关闭"
  when: "{{ ad_closed_result }}" # 如果成功关闭则为True，否则为False
  action: log
  params:
    message: "广告弹窗已被成功关闭。"
```

### **失败时自动截图**

当一个步骤（在所有重试之后）最终失败时，Aura 会自动截取当前屏幕的快照，并将其保存在方案目录下的 `debug_screenshots` 文件夹中。

文件名会包含时间戳和失败步骤的名称，例如 `failure_20230716-153000_点击提交按钮.png`。

这个功能对于事后分析问题至关重要。当您回来检查失败的日志时，可以立刻看到任务失败时屏幕上到底发生了什么，是程序崩溃了？还是弹出了一个预料之外的窗口？一目了然。

---



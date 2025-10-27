# 3. 你的第一个任务：Hello, World

在本教程中，你将学习如何创建、执行并验证一个最简单的 "Hello, World" 任务。这是熟悉 Aura 工作流程的最佳方式。

## 1. 理解 Plan 的目录结构

在 Aura 中，一个 Plan 就是一个功能的集合，它有自己独立的目录。首先，我们需要为我们的 "hello" Plan 创建一个目录。

在项目根目录下的 `plans/` 文件夹中，创建一个名为 `hello/` 的新文件夹。然后，在 `hello/` 文件夹内部，再创建一个名为 `tasks/` 的文件夹。

最终的目录结构应该如下所示：

```
aura/
├── plans/
│   ├── hello/
│   │   └── tasks/
│   └── ... (其他 Plan)
└── ... (项目其他文件)
```

`plans/` 目录是 Aura 默认加载所有任务的地方。

## 2. 编写你的第一个任务文件

现在，在 `plans/hello/tasks/` 目录下，创建一个名为 `say_hello.yaml` 的 YAML 文件，并填入以下内容：

```yaml
meta:
  title: "Say Hello"
  description: "一个简单的任务，用于在日志中打印 Hello, World。"

inputs:
  - name: "person_name"
    type: "string"
    required: true
    default: "World"
    description: "要问候的人的名字。"

steps:
  - name: "print_greeting"
    action: "core.log"
    params:
      message: "Hello, {{ inputs.person_name }}!"
      level: "INFO"
```

让我们来分解一下这个文件的内容：

*   **`meta`**: 描述了任务的标题和功能，这些信息会显示在 Web UI 中。
*   **`inputs`**: 定义了任务可以接受的输入参数。这里我们定义了一个名为 `person_name` 的字符串参数，并提供了一个默认值 `"World"`。
*   **`steps`**: 定义了任务要执行的具体步骤。
    *   `name`: 步骤的唯一标识符。
    *   `action`: 指定要执行的动作。`core.log` 是 Aura 内置的一个 Action，用于在控制台打印日志。
    *   `params`: 传递给 Action 的参数。在这里，我们使用 `{{ inputs.person_name }}` 语法来引用前面定义的输入变量，动态地构造日志消息。

## 3. 重启服务并执行任务

为了让 Aura 加载我们新创建的任务，你需要**重启主服务**。在终端里，停止之前运行的 `python main.py` (通常使用 `Ctrl+C`)，然后再次运行它：

```bash
python main.py
```

服务启动后，刷新你的浏览器中的 Web UI。

1.  在左侧的导航栏中，你应该能看到我们新创建的 "hello" Plan。
2.  点击 "hello"，然后在任务列表中选择 "Say Hello"。
3.  在右侧的执行面板中，你可以看到 `person_name` 这个输入参数。你可以保留默认值 "World"，或者输入你自己的名字。
4.  点击 "执行" (Execute) 按钮。

## 4. 查看结果

任务执行后，页面下方会显示实时的执行日志。你应该能看到类似下面的一行输出：

```
[INFO] Hello, World!
```

如果你在输入框中填入了其他名字，比如 "Alice"，那么日志就会显示 `[INFO] Hello, Alice!`。

## 总结

恭喜你！你已经成功地创建并执行了你的第一个 Aura 任务。你学会了：

*   如何创建 Plan 的目录结构。
*   如何编写一个简单的 YAML 任务文件。
*   如何通过 Web UI 触发任务并查看结果。

现在你已经掌握了 Aura 的基本操作，可以尝试探索更复杂的任务了。


---

### **第二部分：快速上手 (Quick Start) - 修正版**

**(这是文档的下一页 `quick-start.md` 的更新版本)**

---

# **快速上手**

本章节将引导您完成 Aura 的安装，并运行您的第一个自动化任务。整个过程预计需要 15 分钟。

### **1. 环境要求**

在开始之前，请确保您的系统满足以下要求：

*   **操作系统**: Windows 10/11 (当前主要支持 Windows)
*   **Python**: 3.10 或更高版本

您可以打开终端或命令提示符，输入以下命令来检查 Python 版本：
```bash
python --version
```

### **2. 安装 Aura**

Aura 框架以一个压缩包的形式提供。安装过程非常简单。

1.  **解压文件**: 将您收到的 `Aura-Framework.zip` (或类似名称的压缩包) 解压到一个您喜欢的位置。例如，`D:\Aura`。
2.  **运行安装脚本**:
    *   进入解压后的文件夹（例如 `D:\Aura`）。
    *   找到并双击运行 `install.bat` 文件。
    *   这个脚本会自动为您创建一个 Python 虚拟环境，并安装所有必需的依赖库。请耐心等待其执行完毕。

    > **提示**: 安装脚本执行完毕后，您会在当前目录下看到一个名为 `.venv` 的新文件夹。这是 Aura 专用的 Python 环境，可以确保框架的稳定运行，不与您系统上其他的 Python 项目冲突。

### **3. Aura 项目结构**

与其他框架不同，Aura 不会自动生成目录。您需要手动创建您的工作区。一个典型的 Aura 工作区结构如下所示，我们强烈建议您遵循这个结构：

```
D:/MyAuraWorkspace/      <-- 这是您的项目根目录
├── Aura/                 <-- 您解压的 Aura 框架文件夹
│   ├── .venv/
│   ├── main.py           <-- 框架的启动入口
│   ├── install.bat
│   └── ... (其他框架文件)
│
└── plans/                <-- 【重要】您的所有自动化方案都存放在这里
    ├── MyFirstPlan/
    └── AnotherPlan/
```

**创建您的工作区**:
1.  在您喜欢的位置（例如 `D:\`）创建一个新的文件夹，作为您的工作区，例如 `MyAuraWorkspace`。
2.  将解压后的 `Aura` 框架文件夹整个移动到 `MyAuraWorkspace` 中。
3.  在 `MyAuraWorkspace` 中，与 `Aura` 文件夹**并列**，创建一个新的文件夹，命名为 `plans`。

**为什么这样组织？**
*   **框架与方案分离**: 这样做可以将框架的核心代码 (`Aura/`) 与您自己编写的自动化方案 (`plans/`) 完全分开。未来当 Aura 框架有新版本时，您只需替换 `Aura/` 文件夹，而您所有的 `plans` 都可以无缝地继续使用。
*   **路径约定**: Aura 框架默认会从与自身**上一级目录**的 `plans` 文件夹中加载方案。遵循这个结构可以确保您的方案能被正确发现。

### **4. 创建您的第一个方案 (Plan)**

一个“方案”是您一系列相关自动化任务的集合。让我们在刚刚创建的 `plans` 目录中创建第一个方案。

1.  进入 `plans/` 目录。
2.  在 `plans/` 目录下，创建一个新的文件夹，命名为 `MyFirstPlan`。
3.  在 `MyFirstPlan/` 目录下，再创建一个名为 `tasks` 的文件夹。

现在您的目录结构应该是这样：
```
MyAuraWorkspace/
├── Aura/
└── plans/
    └── MyFirstPlan/
        └── tasks/
            └── (空)
```

### **5. 编写您的第一个任务**

现在，让我们编写一个经典的 "Hello, World" 任务。

1.  在 `plans/MyFirstPlan/tasks/` 目录下，创建一个新的文本文件，并命名为 `main.yaml`。
2.  将以下内容复制并粘贴到 `main.yaml` 文件中：

```yaml
# plans/MyFirstPlan/tasks/main.yaml
main:
  meta:
    title: "我的第一个任务"
    entry_point: true
  steps:
    - name: "向世界问好"
      action: log
      params:
        message: "Hello, Aura! 我成功运行了第一个任务。"

    - name: "做一个简单的数学计算"
      action: run_python
      params:
        code: "return 10 * 10"
      output_to: "calculation_result"

    - name: "打印计算结果"
      action: log
      params:
        message: "计算结果是: {{ calculation_result }}"
```

**代码解读**:
*   `main:`: 这是任务的名称（ID）。
*   `meta:`: 任务的元数据。
    *   `title:`: 在 UI 中显示的友好名称。
    *   `entry_point: true`: 标记这个任务是一个可以独立启动的“入口”，它会出现在 Aura 的可运行任务列表中。
*   `steps:`: 一个列表，包含了这个任务需要执行的所有步骤。
*   `action: log.info`: 调用名为 `log.info` 的“行为”，它会在日志中打印一条信息。
*   `output_to: "calculation_result"`: 将上一步 Action 的返回值（`100`）存储到一个名为 `calculation_result` 的变量中。
*   `message: "计算结果是: {{ calculation_result }}"`: 使用 `{{ ... }}` 语法从上下文中读取变量的值并将其插入字符串中。

### **6. 运行任务**

现在，最激动人心的时刻到了！

1.  回到 `Aura/` 文件夹。
2.  双击运行 `main.py` (或对应的启动程序) 来启动 Aura 的用户界面。
3.  在 Aura 的 UI 中，您应该能看到一个名为“我的第一个任务”的条目。如果看不到，请检查您的目录结构是否正确。
4.  点击“运行”按钮。

### **7. 查看结果**

任务执行得非常快。要确认它是否成功运行，请查看日志文件。

1.  在您的工作区根目录 (`MyAuraWorkspace/`)下，应该会自动生成一个 `logs/` 文件夹。
2.  打开 `logs/` 目录，找到最新的日志文件（例如 `aura_2025-07-15.log`）。
3.  打开它，您应该能在文件末尾看到类似下面的内容：

```
[INFO] [YAML Log] Hello, Aura! 我成功运行了第一个任务。
...
[INFO] [YAML Log] 计算结果是: 100
...
[INFO] ======= 任务 '我的第一个任务' 执行结束 =======
```

**恭喜您！** 您已经成功地创建并运行了您的第一个 Aura 自动化任务。您已经掌握了最核心的流程。在接下来的章节中，我们将深入探索 Aura 更强大的功能。

---


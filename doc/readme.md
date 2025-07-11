

# **Aura框架官方入门手册 (v1.0)**

欢迎来到Aura的世界！

Aura是一个为游戏自动化、桌面应用操作等场景设计的、强大且高度可扩展的自动化框架。无论你是一个希望通过简单配置就能实现自动化任务的入门用户，还是一个希望构建复杂、专用功能的开发者，Aura都能满足你的需求。

本手册将带你从零开始，逐步掌握Aura的全部能力，从“零代码”的低代码开发，到编写自定义插件，最终成为Aura框架的专家。

---

## **第一章：初识Aura - 你的第一个自动化任务**

在这一章，我们将以最简单的方式，让你体验到Aura的魅力。你不需要编写任何Python代码，只需要理解简单的YAML配置。

### **1.1 核心概念**

*   **方案包 (Plan)**: 一个独立的文件夹，包含了实现某个特定目标（如“自动挖矿”）所需的所有配置、任务和资源。它是Aura组织工作的基本单位。
*   **任务 (Task)**: 一个YAML文件，定义了一系列要执行的步骤。例如，一个“挖矿”任务可能包含“寻找矿石”、“点击矿石”、“等待采集”等步骤。
*   **行为 (Action)**: 框架预先定义好的、可执行的最小操作单元，如 `log` (打印日志)、`click` (点击屏幕)、`find_image` (寻找图片)等。
*   **上下文 (Context)**: 一个临时的“记忆板”，用于在任务的不同步骤之间传递数据。例如，`find_image`的结果可以存入上下文，供后续的`click`行为使用。

### **1.2 创建你的第一个方案包**

1.  在Aura根目录下的 `plans/` 文件夹中，创建一个新文件夹，命名为 `MyFirstPlan`。
2.  在 `MyFirstPlan/` 中，创建一个名为 `tasks/` 的子文件夹。

### **1.3 编写你的第一个任务**

在 `MyFirstPlan/tasks/` 文件夹中，创建一个名为 `hello_aura.yaml` 的文件，并粘贴以下内容：

```yaml
# tasks/hello_aura.yaml

name: "我的第一个任务"
description: "一个简单的任务，用于向世界问好。"

steps:
  - name: "向控制台打印日志"
    action: log
    params:
      message: "你好，Aura！我来了！"

  - name: "等待3秒"
    action: wait
    params:
      seconds: 3

  - name: "再次打印日志，使用上下文变量"
    action: log
    params:
      message: "等待结束，任务完成。"
```

### **1.4 运行任务**

1.  启动Aura IDE。
2.  切换到“**任务浏览器**”标签页。
3.  在“选择方案包”下拉菜单中，选择 `MyFirstPlan`。
4.  在下方的任务列表中，你应该能看到 `hello_aura`。
5.  点击该任务右侧的“**运行**”按钮。

观察IDE下方的日志输出，你会看到任务按步骤执行，并打印出我们定义的日志。恭喜你，你已经成功运行了第一个Aura任务！

---

## **第二章：低代码开发 - 驾驭核心行为**

现在，让我们学习如何使用Aura最核心的视觉与控制行为，来与游戏或应用进行交互。

### **2.1 准备资源**

1.  在你的方案包 `MyFirstPlan/` 下，创建一个 `resources/images/` 文件夹。
2.  截取一张你想要在屏幕上寻找的图片（例如，游戏中的一个按钮），将其保存为 `target_button.png` 并放入上述文件夹。

### **2.2 核心视觉行为：`find_image`**

`find_image` 用于在屏幕上寻找指定的图片。

```yaml
# tasks/find_and_click.yaml

name: "寻找并点击按钮"
steps:
  - name: "在屏幕上寻找目标按钮"
    action: find_image
    params:
      # 使用相对于方案包根目录的路径
      template: "resources/images/target_button.png"
      threshold: 0.8 # 相似度阈值，0.8代表80%
    # 将寻找结果保存到上下文中，变量名为 button_location
    output_to: button_location
```

### **2.3 条件判断与流程控制**

我们可以根据 `find_image` 的结果来决定后续操作。`find_image` 的结果是一个包含 `found` (布尔值) 和坐标信息的对象。

```yaml
# tasks/find_and_click.yaml (续)

  - name: "如果找到了按钮，就点击它"
    # 'when' 字段：只有当其值为True时，才执行此步骤
    # 我们引用上一步保存到上下文的变量 button_location
    when: "{{ button_location.found }}"
    action: click
    params:
      # 直接使用 button_location 对象，click行为会自动提取其坐标
      target: "{{ button_location }}"
      
  - name: "如果没找到，就打印日志"
    when: "{{ not button_location.found }}"
    action: log
    params:
      message: "没有在屏幕上找到目标按钮。"
```

### **2.4 运行与调试**

在“任务浏览器”中运行 `find_and_click` 任务。观察它的行为：
*   如果屏幕上有目标按钮，它会被点击。
*   如果屏幕上没有，控制台会打印“未找到”的日志。

你可以使用“**方案编辑器**”来实时修改YAML文件，并使用“**资源管理器**”来预览你的图片资源，复制它们的相对路径。

---

## **第三章：进阶开发 - 状态机与中断**

对于需要长期运行、处理复杂逻辑的脚本（如自动打怪），简单的线性任务已不足够。Aura提供了更高级的工具：**状态机**和**中断系统**。

### **3.1 状态机 (State Machine)**

状态机将复杂的任务分解为一系列独立的状态（如“寻怪”、“战斗”、“回城补给”），并定义状态之间转换的条件。

*   **定义**: 在 `world_map.yaml` 文件中定义所有状态和转换规则。
*   **运行**: 状态机任务会自动运行，根据`world_map.yaml`的定义，在不同状态间切换，并执行每个状态对应的任务。

这是一个简化的 `world_map.yaml` 示例：

```yaml
# world_map.yaml

states:
  searching:
    description: "寻找怪物的状态"
    on_run: # 在此状态下循环执行的任务
      action: run_task
      params:
        task_name: "tasks/search_for_monster"
    transitions:
      - to: fighting
        # 当 find_monster 任务在上下文中设置了 monster_found=True 时，切换到战斗状态
        when: "{{ monster_found }}"
  
  fighting:
    description: "与怪物战斗的状态"
    on_enter: # 进入此状态时执行一次
      action: run_task
      params:
        task_name: "tasks/attack_monster"
    transitions:
      - to: searching
        # 当战斗结束时，切换回寻怪状态
        when: "{{ not monster_found }}"
```

### **3.2 中断系统 (Interrupt System)**

中断用于处理突发事件，例如“被玩家攻击”或“背包满了”。当中断条件满足时，它会**暂停**当前主任务，执行一个预设的“处理器任务”，处理完后再恢复主任务。

*   **定义**: 在 `interrupts.yaml` 文件中定义中断规则。
*   **激活**: 中断可以在任务中被动态激活 (`activates_interrupts`)，也可以被设置为全局启用。

```yaml
# interrupts.yaml

interrupts:
  - name: "低血量保护"
    scope: global # 全局中断
    enabled_by_default: true
    condition: # 触发条件
      action: find_image
      params:
        template: "resources/images/low_health_warning.png"
    handler_task: "tasks/use_potion" # 处理器任务
    on_complete: resume # 处理完毕后恢复主任务
```

---

## **第四章：成为开发者 - 编写你自己的插件**

当你发现内置行为无法满足你的特定需求时（例如，你需要操作Excel或调用一个特定的API），就是时候展现你的真正实力了。Aura的**命名空间服务架构 (ANSA)** 允许你轻松地为框架添加新功能。

### **4.1 插件的核心：服务 (Service)**

服务是一个封装了特定领域能力的Python类。例如，一个`ExcelService`封装了读写Excel文件的所有逻辑。

**约定**:
*   **路径**: 服务文件放在 `services/{你的名字}/{你的服务}.py` 或方案包私有的 `plans/{方案名}/services/{你的服务}.py`。
*   **命名**: 文件名用蛇形命名法 (`my_service.py`)，类名用对应的驼峰命名法 (`MyService`)。

**示例：创建一个Discord通知服务**

1.  安装所需库: `pip install requests`
2.  创建文件 `services/my_plugins/discord_service.py`:

```python
# notifier_services/my_plugins/discord_service.py
import requests

class DiscordService:
    def send_message(self, webhook_url: str, message: str):
        """向指定的Discord Webhook发送一条消息。"""
        try:
            data = {"content": message}
            response = requests.post(webhook_url, json=data)
            return response.status_code == 204
        except Exception:
            return False
```

### **4.2 将服务暴露为行为 (Action)**

服务本身不能在YAML中直接调用，你需要创建一个Action作为“接口”。

**约定**:
*   **路径**: Action文件可以放在方案包的 `plugins/` 目录下。
*   **装饰器**: 使用 `@register_action` 和 `@requires_services`。

**示例：创建 `send_discord` 行为**

创建文件 `plans/MyFirstPlan/plugins/discord_actions.py`:

```python
from src.actions.decorators import register_action, requires_services
from typing import TYPE_CHECKING

# 这是一种高级技巧，用于在运行时避免循环导入，同时让代码编辑器获得类型提示
if TYPE_CHECKING:
    from services.my_plugins.discord_service import DiscordService

@register_action(name="send_discord")
# 声明此Action需要一个名为'discord'的服务，它来自'my_plugins'命名空间
@requires_services(discord='my_plugins/discord')
def send_discord_message(discord: 'DiscordService', url: str, msg: str):
    """
    发送一条Discord消息。
    参数 'discord' 会被Aura自动注入DiscordService的实例。
    """
    return discord.send_message(webhook_url=url, message=msg)
```

### **4.3 在YAML中使用你的新插件**

现在，你可以在任何任务中像使用内置行为一样使用你的新行为了！

```yaml
# tasks/test_plugin.yaml
steps:
  - name: "发送Discord通知"
    action: send_discord
    params:
      url: "你的Discord Webhook URL"
      msg: "我的Aura插件工作啦！"
```

### **4.4 服务管理器**

你可以随时在Aura IDE的“**服务管理器**”标签页中，查看你所有自定义服务的加载状态。如果加载失败，这里会提供详细的错误信息，帮助你快速定位问题。

---

## **第五章：框架的未来**

你已经掌握了Aura的核心。现在，整个世界都是你的画布。你可以：
*   **构建复杂的领域服务**: 封装任何你需要的能力，无论是操作数据库、控制智能家居，还是与特定的硬件交互。
*   **设计精妙的AI**: 结合状态机和行为树（未来可能支持），构建出能适应复杂动态环境的自动化AI。
*   **分享你的插件**: 将你的 `services/{你的名字}/` 文件夹分享给其他人，他们只需要把它放到自己的`services`目录下，就能使用你开发的强大功能。

Aura的设计哲学是**开放与赋能**。我们提供了坚实的地基和标准的接口，而你，才是这座自动化大厦真正的建造者。

**旅程才刚刚开始。去创造吧！**


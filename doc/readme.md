# **Aura 框架官方手册 (v2.0)**

欢迎来到Aura的世界！

Aura是一个为游戏自动化、桌面应用操作等场景设计的、强大且高度可扩展的自动化框架。无论你是一个希望通过简单配置就能实现自动化任务的入门用户，还是一个希望构建复杂、专用功能的开发者，Aura都能满足你的需求。

本手册将带你从零开始，逐步掌握Aura的全部能力。

---

## **第一部分：用户指南 - 零代码自动化**

### **1. 核心概念**

*   **方案 (Plan)**: 一个独立的文件夹，包含了实现某个特定目标（如“自动挖矿”）所需的所有配置、任务和资源。它是Aura组织工作的基本单位。
*   **任务 (Task)**: 一个YAML文件，定义了一系列要执行的步骤。
*   **行为 (Action)**: 框架或插件预先定义好的、可执行的最小操作单元，如 `log` (打印日志)、`click` (点击屏幕)。
*   **上下文 (Context)**: 一个临时的“记忆板”，用于在任务的不同步骤之间传递数据。

### **2. 你的第一个任务**

1.  在Aura根目录下的 `plans/` 文件夹中，创建一个新文件夹 `MyFirstPlan`。
2.  在 `MyFirstPlan/` 中，创建一个 `tasks/` 子文件夹。
3.  在 `MyFirstPlan/tasks/` 中，创建 `hello.yaml` 文件：

```yaml
# plans/MyFirstPlan/tasks/hello.yaml
name: "我的第一个任务"
description: "一个简单的任务，用于向世界问好。"

steps:
  - name: "向控制台打印日志"
    action: log
    params:
      message: "你好，Aura！我来了！"
```

4.  运行Aura，在任务浏览器中找到并运行 `MyFirstPlan/hello` 任务。

### **3. 与屏幕交互**

Aura的核心能力是视觉识别和模拟操作。

```yaml
# plans/MyFirstPlan/tasks/find_and_click.yaml
name: "寻找并点击"
steps:
  - name: "在屏幕上寻找目标"
    action: find_image
    params:
      # 将你要找的图片放在 MyFirstPlan/resources/images/target.png
      template: "resources/images/target.png"
      threshold: 0.8 # 相似度
    output_to: result # 将结果存入上下文

  - name: "如果找到了，就点击它"
    when: "{{ result.found }}" # 'when' 用于条件判断
    action: click
    params:
      target: "{{ result }}"
```

---

## **第二部分：高级用户指南 - 流程控制**

### **1. 调度任务 (`schedule.yaml`)**

在你的方案根目录（例如 `MyFirstPlan/`）下创建 `schedule.yaml`，可以让任务定时或周期性运行。

```yaml
# plans/MyFirstPlan/schedule.yaml
- id: daily_login_task
  name: "每日登录奖励"
  task: "tasks/login" # 要运行的任务
  trigger:
    type: "cron" # 使用cron表达式
    value: "0 9 * * *" # 每天上午9点执行
  enabled: true
```

### **2. 状态机 (`states_map.yaml`)**

对于复杂逻辑，可以使用状态机。在方案根目录下创建 `states_map.yaml`。

```yaml
# plans/MyFirstPlan/states_map.yaml
states:
  searching:
    description: "寻找怪物的状态"
    task: "tasks/find_monster" # 此状态下循环运行的任务
  fighting:
    description: "与怪物战斗的状态"
    task: "tasks/fight_monster"

transitions:
  - from: searching
    to: fighting
    when: "{{ context.monster_found }}" # 当上下文中 monster_found 为 true 时切换
  - from: fighting
    to: searching
    when: "{{ not context.monster_alive }}"
```
*要启动状态机，需要一个特殊的任务来调用 `ensure_state` 行为。*

### **3. 中断处理 (`interrupts.yaml`)**

中断用于处理突发事件（如被攻击、低血量）。在方案根目录下创建 `interrupts.yaml`。

```yaml
# plans/MyFirstPlan/interrupts.yaml
interrupts:
  - name: "低血量保护"
    scope: global # 全局生效
    enabled_by_default: true
    condition: # 触发条件
      action: find_image
      params:
        template: "resources/images/low_health.png"
    handler_task: "tasks/use_potion" # 处理任务
```

---

## **第三部分：开发者指南 - 创建你自己的插件**

当你发现内置行为无法满足需求时，可以创建自己的插件。

### **1. 插件的结构**

一个插件就是一个文件夹，通常放在 `packages/` 目录下。

```
packages/
└── my_notifier/            <-- 插件根目录
    ├── plugin.yaml         <-- 插件清单 (必需)
    ├── notifier_service.py <-- 你的服务逻辑
    ├── notifier_actions.py <-- 你的行为定义
    └── hooks.py            <-- (可选) 框架钩子
```

### **2. 插件清单 (`plugin.yaml`)**

这是插件的“身份证”，是**必需**的。

```yaml
# packages/my_notifier/plugin.yaml
identity:
  author: "YourName"
  name: "notifier"
  version: "1.0.0"

description: "一个可以通过Discord发送通知的插件。"

# 如果你的插件依赖其他插件，在这里声明
dependencies:
  "Aura-Project/base": "1.0.0" # 依赖基础包
```

### **3. 创建服务 (Service)**

服务是封装了特定领域能力的Python类。

```python
# packages/my_notifier/notifier_service.py
import requests
from packages.aura_core.api import register_service

@register_service(alias="discord", public=True)
class NotifierService:
    def send(self, webhook_url: str, message: str) -> bool:
        """向指定的Discord Webhook发送一条消息。"""
        try:
            data = {"content": message}
            response = requests.post(webhook_url, json=data)
            return response.status_code == 204
        except Exception:
            return False
```
*   `@register_service(alias, public)`:
    *   `alias`: 服务在本插件内的简称。
    *   `public=True`: 使服务能被其他插件使用。

### **4. 创建行为 (Action)**

行为是暴露给YAML任务的接口，它是一个Python函数。

```python
# packages/my_notifier/notifier_actions.py
from packages.aura_core.api import register_action, requires_services
from typing import TYPE_CHECKING

# TYPE_CHECKING块用于代码编辑器的类型提示，避免循环导入
if TYPE_CHECKING:
    from .notifier_service import NotifierService

@register_action(name="send_discord", public=True)
@requires_services(notify='YourName/notifier/discord')
def send_discord_message(notify: 'NotifierService', url: str, msg: str):
    """
    发送一条Discord消息。
    参数 'notify' 会被Aura自动注入NotifierService的实例。
    """
    return notify.send(webhook_url=url, message=msg)
```
*   `@register_action(name, public)`:
    *   `name`: 行为在YAML中使用的名字。
    *   `public=True`: 使行为能被用户在YAML中使用。
*   `@requires_services(local_name='author/plugin/service_alias')`:
    *   声明此行为依赖的服务。Aura会自动实例化并注入它。
    *   `local_name` 是函数参数名。
    *   值是服务的完整ID (FQID): `author/name/alias`。

### **5. 构建与使用**

**你不需要手动构建任何东西！**

当你启动Aura时，框架会自动检测到你的新插件，解析`@register_service`和`@register_action`，并在内部为你处理一切。

现在，你可以在任务中直接使用你的新行为了：
```yaml
# tasks/test_my_plugin.yaml
steps:
  - name: "发送开工通知"
    action: send_discord
    params:
      url: "你的Discord Webhook URL"
      msg: "我的Aura插件工作啦！"
```

---

## **第四部分：框架架构概览**

Aura采用模块化、事件驱动的架构。

*   **Scheduler (调度器)**: 框架的心脏，一个在后台运行的异步引擎，负责管理所有任务的生命周期。
*   **PluginManager (插件管理器)**: 负责发现、解析、构建和加载所有插件 (`plugin.yaml`)。
*   **PlanManager (方案管理器)**: 管理所有类型为 "plan" 的插件，并为它们加载 `schedule.yaml`, `interrupts.yaml` 等配置文件。
*   **ExecutionManager (执行管理器)**: 负责实际执行单个任务的步骤，处理上下文和条件判断。
*   **EventBus (事件总线)**: 一个全局的发布/订阅系统，允许框架各部分之间，以及插件之间进行解耦通信。任务可以被事件触发。
*   **ServiceRegistry / ActionRegistry (注册中心)**: 全局单例，存放了所有已加载的服务和行为的定义。

这种设计使得框架功能高度内聚，且易于扩展。开发者可以通过创建自己的插件来无缝地为Aura添加新功能。

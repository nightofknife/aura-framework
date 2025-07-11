

# Aura 自动化框架 - 任务文件 (`tasks/*.yaml`) 参考手册 (v5.1)

欢迎来到 Aura 框架 v5.1！本手册将专注于如何编写强大、灵活且易于维护的任务文件。在新版本中，我们统一并简化了任务格式，以提供更佳的开发体验。

## 核心理念：结构化的任务定义

Aura v5.1 采用“一个文件，多个任务”的结构化方法。你可以在单个 YAML 文件中定义一组逻辑相关的任务，这有助于更好地组织你的自动化方案。

一个典型的任务文件目录结构如下：
```
plans/
└── MyAwesomePlan/
    └── tasks/
        ├── common.yaml         # 存放通用子任务，如 'check_login', 'take_screenshot'
        ├── quests/
        │   ├── daily_quest.yaml
        │   └── main_quest.yaml
        └── navigation.yaml     # 存放所有导航相关的任务
```

## 任务ID (Task ID) 的构成

任务ID是任务在整个框架中的唯一标识符，格式为：**`{plan_name}/{file_path_in_tasks}/{task_key}`**。

**示例：**
假设你的方案包名为 `MyAwesomePlan`，有一个任务文件路径为 `plans/MyAwesomePlan/tasks/quests/daily_quest.yaml`，其内容如下：

```yaml
# tasks/quests/daily_quest.yaml

collect_rewards:
  # ... steps ...
  
complete_missions:
  # ... steps ...
```

那么这两个任务的完整ID将是：
*   `MyAwesomePlan/quests/daily_quest/collect_rewards`
*   `MyAwesomePlan/quests/daily_quest/complete_missions`

这个ID将用于 `schedule.yaml` 的调度、`interrupts.yaml` 的处理，以及在任务中通过 `run_task` 或 `go_task` 进行调用。

## 任务文件格式

每个任务文件都是一个 YAML 字典，其顶层键是该文件内定义的**任务键 (Task Key)**。

```yaml
# 任务键 (Task Key)，例如: login_to_game
login_to_game:
  # 任务元数据 (meta)
  meta:
    title: "一个易于在UI中辨识的标题"
    description: "（可选）关于此任务用途的更详细说明。"
    entry_point: true # (可选) 设为 true，此任务将出现在UI的任务浏览器中，可手动执行。
    
  # 任务输出 (outputs) - 可选
  outputs:
    player_id: "{{ user_data.id }}"
    session_token: "{{ login_result.token }}"

  # 任务步骤 (steps) - 核心
  steps:
    - # ... 第一个步骤 ...
    - # ... 第二个步骤 ...
```

### 1. `meta` - 任务元数据

`meta` 块用于定义任务的描述性信息，主要供UI和开发者使用。

*   `title` (字符串, **必需**): 任务的显示名称。
*   `description` (字符串, 可选): 任务的详细描述。
*   `entry_point` (布尔值, 可选, 默认为 `false`): 如果为 `true`，这个任务将被视为一个高级别的、可独立运行的入口任务，会显示在UI的任务列表中。通常用于主线任务或可手动触发的功能。子任务或纯粹被调用的任务应省略此项或设为 `false`。

### 2. `outputs` - 任务返回值

`outputs` 块允许你定义当此任务作为子任务被 `run_task` 调用时，应该返回什么值。它是一个字典，键是返回对象的属性名，值是Jinja2表达式。

**示例：**
一个登录子任务可以这样返回值：
```yaml
# tasks/common/do_login.yaml
login:
  meta:
    title: "执行登录"
  outputs:
    user_id: "{{ login_response.user.id }}"
    username: "{{ login_response.user.name }}"
    is_success: true
  steps:
    - action: api.login
      params: { user: "test", pass: "123" }
      output_to: "login_response"
```
当其他任务调用 `run_task: common/do_login/login` 时，可以将返回的字典存入变量，并访问 `user_id` 等属性。

### 3. `steps` - 任务步骤

`steps` 是一个列表，定义了任务要执行的具体操作。每个步骤都是一个字典，包含以下关键字：

#### 核心关键字

*   `name` (字符串, 可选): 步骤的描述性名称，强烈推荐填写，用于日志输出。
*   `action` (字符串, 可选): 要执行的行为名称，例如 `log.info`, `app.find_text_and_click`。如果一个步骤只用于流程控制（如 `if`），则可以省略 `action`。
*   `params` (字典, 可选): 传递给 `action` 的参数。所有值都支持 Jinja2 渲染。
*   `id` (字符串, 可选): 步骤的唯一标识符，用于被 `go_step` 指令跳转。

#### 流程控制关键字

*   `when` (Jinja2表达式, 可选): 只有当表达式的计算结果为真值时，该步骤才会执行。
    ```yaml
    - name: "仅当生命值低于50%时吃药"
      action: use_item
      params: { item_id: "health_potion" }
      when: "{{ player.hp < player.max_hp * 0.5 }}"
    ```

*   `if` / `then` / `else` (可选): 实现条件分支。`if` 的值是一个Jinja2表达式，`then` 和 `else` 的值是步骤列表。
    ```yaml
    - name: "检查是否需要修理装备"
      if: "{{ needs_repair }}"
      then:
        - name: "跳转到修理任务"
          go_task: "common/repair_gear"
      else:
        - name: "记录日志：无需修理"
          action: log.info
          params: { message: "装备状态良好。" }
    ```

*   `for` / `do` (可选): 实现迭代循环。`for` 的值是一个字典，`do` 的值是要在循环中执行的步骤列表。
    *   `in`: (Jinja2表达式) 其结果必须是一个可迭代对象（如列表、字典）。
    *   `as`: (字符串) 定义了循环中每个元素的变量名。
    ```yaml
    - name: "出售所有垃圾物品"
      for:
        in: "{{ items_to_sell }}"
        as: "current_item"
      do:
        - name: "点击出售按钮"
          action: app.click
          params: { target: "{{ current_item.sell_button_coords }}" }
    ```

*   `while` / `do` (可选): **(全新增强)** 实现条件循环。`while` 的值是Jinja2表达式，只要为真就一直执行 `do` 块中的步骤。
    *   `max_loops`: (整数, 可选, 默认1000) 防止无限循环的最大执行次数。
    ```yaml
    - name: "持续攻击直到Boss倒下"
      while: "{{ boss.is_alive and player.is_in_combat }}"
      max_loops: 300 # 最多攻击300次
      do:
        - action: combat.attack
          params: { target: "boss" }
        - action: app.wait
          params: { seconds: 1.5 }
    ```

*   `go_step` (字符串, 可选): **(全新增强)** **立即**跳转到当前任务中具有指定 `id` 的步骤。现在可以跳转到任意嵌套深度（如 `if/then` 或 `for/do` 内部）的步骤。
    ```yaml
    steps:
      - go_step: "final_step"
      - if: "{{ some_condition }}"
        then:
          - id: "final_step" # 即使ID在嵌套块中，也能被跳转到
            action: log.info
            params: { message: "任务结束！" }
    ```

*   `go_task` (字符串, 可选): **立即**中止当前任务，并跳转到指定的另一个任务（使用完整的任务ID）。
    ```yaml
    - name: "如果掉线，则跳转到重连任务"
      action: common.check_connection
      output_to: "is_connected"
    - if: "{{ not is_connected }}"
      go_task: "common/reconnect"
    ```

*   `run_task` (内置action): **(全新增强)** 作为一个普通的步骤执行一个子任务，执行完毕后会返回到当前任务继续执行。
    *   **参数**:
        *   `task_name`: (字符串) 要执行的子任务的完整ID。
        *   `pass_params`: (字典, 可选) 将一个字典中的键值对传递到子任务的上下文中。
    *   **行为**: 如果子任务中执行了 `go_task`，`run_task` 会正确地将此信号向上传递，导致父任务也立即中止并跳转。
    ```yaml
    - name: "调用登录子任务并传递凭证"
      action: run_task
      params:
        task_name: "common/login"
        pass_params:
          username: "my_user"
          password: "{{ env.secret_password }}"
      output_to: "login_result"
    ```

#### 错误处理与执行选项

*   `retry` (字典, 可选): 当步骤的 `action` 执行失败时自动重试。
    *   `count` (整数): 最大重试次数。
    *   `interval` (数字): 每次重试的间隔秒数。
    ```yaml
    - name: "尝试点击一个可能加载慢的按钮"
      action: app.click
      params: { text: "确定" }
      retry: { count: 5, interval: 2 }
    ```

*   `output_to` (字符串, 可选): 将 `action` 或 `run_task` 的返回值存储到以此字符串为名的上下文变量中，供后续步骤使用。
    ```yaml
    - name: "获取玩家坐标"
      action: player.get_coords
      output_to: "player_coords"
    - name: "根据坐标记录日志"
      action: log.info
      params: { message: "玩家当前在 ({{ player_coords.x }}, {{ player_coords.y }})" }
    ```

*   `continue_on_failure` (布尔值, 可选, 默认为 `false`): 如果一个步骤（包括其所有重试）最终失败，设置此项为 `true` 将允许任务继续执行下一个步骤，而不是中止。

---

## 完整示例

假设有一个文件 `plans/MyGame/tasks/daily.yaml`：

```yaml
# 任务键: main
main:
  meta:
    title: "完成所有日常任务"
    entry_point: true
  steps:
    - name: "执行登录子任务"
      action: run_task
      params: { task_name: "common/login" }
      output_to: "login_info"

    - name: "检查登录是否成功，若失败则跳转"
      if: "{{ not login_info.is_success }}"
      go_task: "common/report_error" # 如果失败，立即中止并跳转

    - name: "持续领取邮件奖励直到邮箱为空"
      id: "mail_loop_start"
      action: mail.get_next
      output_to: "next_mail"
    - if: "{{ next_mail }}" # 如果找到了邮件
      then:
        - action: mail.claim
          params: { mail_id: "{{ next_mail.id }}" }
        - go_step: "mail_loop_start" # 返回循环开头继续检查下一封
      else:
        - action: log.info
          params: { message: "所有邮件已领取完毕。" }
    
    - name: "完成所有日常任务"
      action: run_task
      params: { task_name: "quests/daily_quest/complete_all" }

    - name: "任务完成"
      action: log.info
      params: { message: "所有日常任务已完成！" }
```



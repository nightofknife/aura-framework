
---

# **Aura 自动化框架 - 任务文件 (`tasks/*.yaml`) 参考手册 (v6)**

欢迎来到 Aura 框架 v6！本手册将专注于如何编写新一代的任务文件。新架构引入了一个强大的、基于**有向无环图 (DAG)** 的执行引擎，允许你构建复杂的、具有声明式依赖和高级流程控制的并发工作流。

## 核心理念：万物皆图 (Everything is a Graph)

在 Aura v6 中，**所有任务的核心逻辑都以图（Graph）的形式定义**。即使是看似线性的 `steps` 列表，在底层也会被自动转换为一个单节点的图来执行。这种统一的模型提供了前所未有的灵活性和一致性。

一个任务文件依然可以包含多个任务定义：
```
plans/
└── MyAwesomePlan/
    └── tasks/
        ├── common.yaml
        └── daily_quest.yaml
```

## 任务ID (Task ID)

任务ID的构成保持不变：**`{plan_name}/{file_path_in_tasks}/{task_key}`**。

## 任务定义结构 (Task Definition Structure)

每个任务文件都是一个 YAML 字典，其顶层键是该文件内定义的**任务键 (Task Key)**。

```yaml
my_task_key:
  # --- 1. 执行与调度选项 (Execution & Scheduling Options) ---
  execution_mode: sync
  resource_tags: ['gpu', 'login_session']
  timeout: 3600

  # --- 2. 状态管理 (State Management) ---
  required_initial_state: "logged_in"
  ensured_final_state: "at_home_screen"

  # --- 3. 任务 I/O 与错误处理 (Task I/O & Error Handling) ---
  returns:
    player_id: "{{ steps.get_user_info.result.id }}"
  on_failure:
    do:
      - action: log.error
        params: { message: "任务 {{ task.name }} 失败，错误: {{ error }}" }

  # --- 4. 核心逻辑 (Core Logic) ---
  steps:
    # 任务的所有节点都在这里定义
    node_A:
      # ...
    node_B:
      # ...
```

---

### 1. 执行与调度选项 (Execution & Scheduling Options)

这些顶层关键字告诉 `ExecutionManager` **如何**以及**在什么条件下**运行此任务。

*   `execution_mode` (字符串, 可选, 默认为 `'sync'`):
    *   `'sync'`: **同步模式**。任务中的每个 `action` 都会在**线程池**中执行。适用于大多数传统的、可能包含阻塞 I/O 或 CPU 密集型操作的 Action。这是最安全、最兼容的默认选项。
    *   `'async'`: **异步模式**。任务中的每个 `action` 都必须是 `async def` 定义的异步函数，它们将直接在 `asyncio` 事件循环中执行。适用于纯粹的、非阻塞的 I/O 密集型任务（如大量并发的 API 请求），性能极高。

*   `resource_tags` (列表[字符串], 可选):
    *   为任务打上资源标签。`ExecutionManager` 会确保在同一时间，只有一个拥有相同标签的任务在运行。这是一种轻量级的、具名的互斥锁。

*   `timeout` (数字, 可选, 默认为 `3600`):
    *   任务的最大执行时间（秒）。如果任务执行超过此时长，它将被强制取消。

### 2. 状态管理 (State Management)

这些关键字与 `StatePlanner` 模块集成，实现了强大的声明式状态转换。

*   `required_initial_state` (字符串, 可选):
    *   声明此任务期望系统在执行前处于的**前置状态**。

*   `ensured_final_state` (字符串, 可选):
    *   声明此任务成功执行后，系统**应该**处于的状态。

### 3. 任务 I/O 与错误处理 (Task I/O & Error Handling)

*   `returns` (字典, 可选):
    *   定义当此任务作为子任务被 `run_task` 调用时，应该返回什么值。
    *   **重要**: 在 `returns` 块中，你可以通过 `{{ steps.node_id.result }}` 来访问图中任意节点的执行结果。

*   `on_failure` (字典, 可选):
    *   定义一个“catch 块”。如果任务的 `steps` 图中的任何节点失败，整个任务会立即中止，并转而执行 `on_failure` 块中定义的步骤。
    *   它必须包含一个 `do` 键，其值为一个**线性的步骤列表**。
    *   在 `on_failure` 块中，你可以访问一个特殊的 `error` 变量。

### 4. 核心逻辑: `steps` - 图定义

在 v6 中，`steps` 关键字现在是一个**字典**，用于定义任务的**执行图 (Execution Graph)**。这个字典的键是**节点ID (Node ID)**，值是**节点定义 (Node Definition)**。

```yaml
steps:
  # 节点ID: get_user_data
  get_user_data:
    # 节点定义
    name: "获取用户数据"
    action: api.get_user
    
  # 节点ID: process_data
  process_data:
    # 节点定义
    name: "处理数据"
    depends_on: "get_user_data" # 依赖关系
    action: data.analyze
    params:
      user: "{{ steps.get_user_data.result }}"
```

#### **节点定义 (Node Definition)**

每个节点都是图中的一个执行单元，支持以下关键字：

##### **A. 核心执行关键字**

一个节点**必须**包含以下执行块之一：
*   `action`: (字符串) 执行单个 Action。
*   `do`: (步骤列表) 按顺序执行一个线性的子步骤列表。
*   `for_each`: (字典) 并发地对一个列表的每一项执行一个子图。
*   `while`: (字典) 根据条件重复执行一个子图。
*   `switch`: (字典) 根据条件从多个路径中选择一个执行。
*   `try`: (字典) 定义一个包含 `try/catch/finally` 逻辑的复杂块。

##### **B. 通用节点关键字**

*   `name` (字符串, 可选): 节点的描述性名称，用于日志输出。
*   `depends_on` (依赖结构, 可选): **核心关键字**。声明此节点的前置依赖。详见下一节。
*   `when` (Jinja2表达式, 可选): 只有当表达式为真时，节点才会执行。如果为假，节点状态为 `SKIPPED`。
*   `on_failure` (字典, 可选): **节点级别**的 `on_failure` 处理器。如果此节点失败，会先执行这里的逻辑，然后再将失败状态传递给整个任务。

#### **定义依赖关系 (`depends_on`)**

`depends_on` 关键字用于定义节点之间的执行顺序和逻辑关系。引擎会确保只有在依赖条件满足时，节点才会被调度执行。

*   **简单依赖 (字符串)**: 依赖单个节点。
    ```yaml
    depends_on: "node_A"
    ```

*   **与 (AND) 依赖 (列表)**: 依赖多个节点，它们**都必须成功**。
    ```yaml
    depends_on: ["node_A", "node_B"] # 隐式的 AND
    # 或显式的 AND
    depends_on:
      and: ["node_A", "node_B"]
    ```

*   **或 (OR) 依赖 (字典)**: 依赖多个节点，**至少一个成功**即可。
    ```yaml
    depends_on:
      or: ["node_A", "node_B"]
    ```
*   **非 (NOT) 依赖 (字典)**: 依赖的节点**必须没有成功**（即处于 PENDING, RUNNING, 或 FAILED 状态）。这对于定义故障转移路径非常有用。
    ```yaml
    depends_on:
      not: "node_A" # 如果 node_A 失败或未运行，则满足
    ```

*   **复合依赖**: 你可以任意嵌套 `and`, `or`, `not` 来创建复杂的逻辑。
    ```yaml
    depends_on:
      and:
        - "node_A"
        - or:
            - "node_B"
            - "node_C"
        - not: "error_flag_node"
    ```

#### **高级流程控制节点**

除了执行 `action` 的简单节点，你还可以使用专门的流程控制节点：

*   **`do` (线性脚本)**
    ```yaml
    linear_node:
      do:
        - name: "第一步"
          action: log.info
          params: { message: "Hello" }
        - name: "第二步"
          action: log.info
          params: { message: "World" }
    ```

*   **`for_each` (并行循环)**
    ```yaml
    fan_out_node:
      for_each:
        in: "{{ some_list_variable }}"
        as: "item" # 变量名
        do: # 为每个 item 执行的子图
          sub_node_1:
            action: api.process_item
            params: { data: "{{ item }}" }
    ```

*   **`while` (条件循环)**
    ```yaml
    polling_node:
      while:
        condition: "{{ steps.check_status.result.status != 'completed' }}"
        limit: 10 # 最大循环次数
        do: # 循环体子图
          check_status:
            action: api.get_job_status
          wait:
            depends_on: "check_status"
            action: app.wait
            params: { seconds: 5 }
    ```

*   **`switch` (条件分支)**
    ```yaml
    branching_node:
      switch:
        cases:
          - when: "{{ user.level > 10 }}"
            then: "high_level_path_node" # 要跳转到的节点ID
          - when: "{{ user.level > 5 }}"
            then: "mid_level_path_node"
        default: "low_level_path_node" # 如果所有 when 都为 false
    ```

*   **`try` (错误处理)**
    ```yaml
    robust_node:
      try:
        do:
          risky_op:
            action: api.might_fail
      catch:
        do:
          handle_error:
            action: log.warning
            params: { message: "操作失败: {{ error }}" }
      finally:
        do:
          cleanup:
            action: resource.release
    ```

#### **内置 Action: `run_task`**

`run_task` 现在是一个标准的 Action，可以在任何 `action` 字段中使用。

```yaml
run_sub_task_node:
  action: run_task
  params:
    task_name: "MyPlan/common/login"
    with: # 新的标准参数传递键
      username: "my_user"
      password: "{{ env.secret_password }}"
```

---

## Jinja2 上下文 - 访问数据

*   **`steps`**: **核心对象**。用于访问图中任何已完成节点的状态和结果。
    *   `steps.node_id.status`: 节点的状态 (e.g., 'SUCCESS', 'FAILED')。
    *   `steps.node_id.result`: 节点的返回值。
    *   **示例**: `{{ steps.get_user_data.result.name }}`

*   **`task`**: 当前任务的信息 (`task.name`, `task.run_id`)。
*   **`params`**: 在子任务中，访问由 `run_task` 的 `with` 块传递进来的参数。
*   **`env`**: 访问环境变量 (`{{ env.MY_API_KEY }}`)。
*   **`config(key)`**: 访问当前方案的配置 (`{{ config('user.name') }}`)。
*   **`error`**: 在 `on_failure` 或 `catch` 块中，访问错误详情。

---

## 完整示例

一个并发获取数据并处理的 `graph` 任务：

```yaml
# tasks/data_processing.yaml

process_user_and_products:
  returns:
    final_report: "{{ steps.generate_report.result }}"
  steps:
    # --- 起始节点 (并发执行) ---
    fetch_user:
      name: "获取用户信息"
      action: api.get_user_info
      retry: { count: 3, interval: 1 }

    fetch_products:
      name: "获取产品列表"
      action: api.get_products
      retry: { count: 3, interval: 1 }

    # --- 核心成功路径 ---
    process_data:
      name: "分析并整合数据"
      depends_on:
        and: [fetch_user, fetch_products] # 必须两者都成功
      action: data.process
      params:
        user: "{{ steps.fetch_user.result }}"
        items: "{{ steps.fetch_products.result }}"

    generate_report:
      name: "生成报告"
      depends_on: "process_data"
      action: reporting.create
      params:
        processed_data: "{{ steps.process_data.result }}"

    # --- 故障处理路径 ---
    report_failure:
      name: "报告数据获取失败"
      depends_on:
        or: # 如果任一获取失败 (即没有成功)
          - not: "fetch_user"
          - not: "fetch_products"
      action: alert.send_warning
      params:
        message: >
          数据获取不完整。
          用户获取状态: {{ steps.fetch_user.status | default('PENDING') }}.
          产品获取状态: {{ steps.fetch_products.status | default('PENDING') }}.
```

## 5. Jinja2 模板 - 过滤器和函数

Aura 使用标准的 [Jinja2 模板引擎](https://jinja.palletsprojects.com/en/3.1.x/templates/)，这意味着你可以使用所有内置的过滤器和函数来转换和操作数据。

**常用过滤器示例**:
*   **提供默认值**: 当一个变量可能不存在时，这非常有用。
    ```yaml
    params:
      username: "{{ user.name | default('guest') }}"
    ```
*   **获取长度**: 检查列表中的项目数或字符串的长度。
    ```yaml
    when: "{{ steps.get_items.result | length > 0 }}"
    ```
*   **转换为JSON字符串**: 在日志记录或将复杂对象作为单个字符串传递给API时非常有用。
    ```yaml
    params:
      message: "User data: {{ steps.fetch_user.result | tojson }}"
    ```
*   **数学运算**:
    ```yaml
    params:
      next_level_xp: "{{ (player.level * 100) | int }}"
    ```

请参考 [Jinja2 官方文档](https://jinja.palletsprojects.com/en/3.1.x/templates/#list-of-built-in-filters) 获取完整的内置过滤器列表。

## 6. 迁移指南：从 v5 (线性 Steps) 到 v6 (图 Steps)

Aura v6 的引擎内置了对旧版线性 `steps` 列表格式的**向后兼容支持**。如果引擎检测到一个任务的 `steps` 是一个列表（`[...]`）而不是字典（`{...}`），它会自动将其包装在一个特殊的单节点图中执行。

**虽然这可以确保旧任务继续运行，但我们强烈建议您将任务迁移到新的图格式，以便：**
*   利用并发执行来提升性能。
*   使用更清晰、更强大的 `depends_on` 依赖系统。
*   获得更精细的错误处理和流程控制能力。

#### **迁移示例**

**v5 线性 `steps` (旧)**
```yaml
steps:
  - name: "获取用户数据"
    action: api.get_user
    output_to: "user_data"

  - name: "处理数据"
    action: data.analyze
    params:
      user: "{{ user_data }}"
    output_to: "analysis_result"

  - name: "发送报告"
    action: reporting.send
    params:
      report: "{{ analysis_result }}"
```

**v6 图 `steps` (新)**
```yaml
steps:
  get_user_data:
    name: "获取用户数据"
    action: api.get_user

  process_data:
    name: "处理数据"
    depends_on: "get_user_data" # 显式依赖
    action: data.analyze
    params:
      user: "{{ steps.get_user_data.result }}" # 通过 `steps` 对象引用结果

  send_report:
    name: "发送报告"
    depends_on: "process_data"
    action: reporting.send
    params:
      report: "{{ steps.process_data.result }}"
```
如您所见，迁移过程非常直观：
1.  将 `steps` 从列表改为字典。
2.  为每个步骤（现在是节点）分配一个唯一的**节点ID**作为键。
3.  使用 `depends_on` 明确声明节点之间的执行顺序。
4.  更新 Jinja2 表达式，使用 `{{ steps.node_id.result }}` 来引用其他节点的输出。

## 7. 最佳实践

1.  **拥抱图思维 (Think in Graphs)**: 在设计任务时，首先考虑“哪些操作可以并行执行？”。将这些操作作为图的起始节点。这对于 I/O 密集型任务（如多个 API 调用）的性能提升尤为显著。

2.  **模块化与复用**: 将复杂的图分解成更小的、功能单一的子任务图。使用 `run_task` 来调用它们。将所有方案通用的子任务（如 `login`, `logout`, `error_reporting`）放在一个共享的 `tasks/common.yaml` 文件中。

3.  **清晰的节点ID**: 为你的节点使用清晰、有描述性的ID。这将使 `depends_on` 依赖和 `{{ steps.node_id.result }}` 表达式更易于阅读和维护。

4.  **声明式状态优先**: 优先使用 `required_initial_state` 来确保前置条件，而不是在每个任务的开头都手动编写一个 `check_and_fix_state` 节点。让框架的 `StatePlanner` 为你工作。

5.  **精细的错误处理**:
    *   使用 `try/catch` 节点来处理那些**预期可能发生**并需要优雅恢复的错误（例如，API 调用超时）。
    *   使用任务级的 `on_failure` 来处理**意外的、灾难性的**失败，用于执行最终的清理、发送警报等。

6.  **使用 `resource_tags`**: 对于需要独占访问共享资源（如一个登录会话、一个硬件设备）的操作，务必使用 `resource_tags` 来防止竞态条件和冲突。

7.  **保持依赖关系清晰**: 避免创建过于复杂的“意大利面式”依赖。一个好的图应该有一个或多个清晰的起点，并大致从左到右或从上到下地流动，最终汇集到一个或多个终点。

---

## 结论

Aura v6 的任务文件格式提供了一个极其强大和富有表现力的平台，用于定义从简单线性脚本到复杂并发工作流的各种自动化任务。通过掌握**图结构定义**、**声明式依赖**、**高级流程控制节点**以及**模块化**这几个核心概念，你将能够构建出比以往任何时候都更高效、更健壮、更易于维护的自动化解决方案。




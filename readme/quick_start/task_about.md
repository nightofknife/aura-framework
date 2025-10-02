# Aura框架任务编写完全指南

## 目录
1. [任务基础语法](#任务基础语法)
2. [任务结构详解](#任务结构详解)
3. [特殊关键字](#特殊关键字)
4. [流程控制](#流程控制)
5. [依赖管理](#依赖管理)
6. [Action库参考](#action库参考)
7. [高级用法](#高级用法)
8. [错误处理](#错误处理)
9. [实战示例](#实战示例)

---

## 任务基础语法

### 基本任务结构

```yaml
# meta.yaml - 任务元数据文件
meta:
  title: "示例任务"
  description: "这是一个示例任务定义"
  version: "1.0.0"
  author: "your_name"
  tags: ["example", "demo"]

# 执行模式设置
execution_mode: "async"  # sync 或 async

# 任务步骤定义
steps:
  step1:
    action: "core/log"
    params:
      message: "任务开始执行"
      
  step2:
    action: "core/http_get"
    params:
      url: "https://api.example.com/data"
    depends_on: ["step1"]

# 任务返回值定义
returns:
  final_result: "{{ steps.step2.result }}"
  execution_time: "{{ meta.duration }}"
```

### 最小任务示例

```yaml
# tasks/simple.yaml
steps:
  hello:
    action: "core/log"
    params:
      message: "Hello, World!"
```

---

## 任务结构详解

### 1. Meta 部分

```yaml
meta:
  title: "任务标题"                    # 必需：任务显示名称
  description: "任务描述"              # 可选：详细描述
  version: "1.0.0"                    # 可选：版本号
  author: "author_name"               # 可选：作者
  tags: ["tag1", "tag2"]              # 可选：标签列表
  category: "data_processing"         # 可选：分类
  priority: 100                       # 可选：优先级（数字越小优先级越高）
  timeout: 300                        # 可选：超时时间（秒）
```

### 2. 执行模式

```yaml
# 同步执行 - 适合简单、快速的任务
execution_mode: "sync"

# 异步执行 - 适合复杂、长时间运行的任务（默认）
execution_mode: "async"
```

### 3. 步骤定义

每个步骤可以包含以下字段：

```yaml
steps:
  step_name:
    action: "plugin/action"            # 必需：要执行的动作
    params: {}                         # 可选：动作参数
    depends_on: []                     # 可选：依赖的步骤列表
    condition: "{{ expr }}"            # 可选：执行条件
    retry: 3                          # 可选：重试次数
    retry_delay: 1                    # 可选：重试延迟（秒）
    timeout: 60                       # 可选：超时时间（秒）
    on_success: {}                    # 可选：成功时的操作
    on_failure: {}                    # 可选：失败时的操作
    on_timeout: {}                    # 可选：超时时的操作
    loop: {}                          # 可选：循环配置
    switch: {}                        # 可选：条件分支
    try_catch: {}                     # 可选：异常处理
```

---

## 特殊关键字

### 1. 上下文引用

```yaml
# 引用初始数据
{{ initial.param_name }}

# 引用其他步骤的结果
{{ steps.step_name.result }}
{{ steps.step_name.result.data }}
{{ steps.step_name.result.status }}

# 引用元数据
{{ meta.start_time }}
{{ meta.task_name }}
{{ meta.version }}

# 引用系统变量
{{ env.VARIABLE_NAME }}
{{ config.plugin_name.setting }}
```

### 2. 过滤器

```yaml
# 字符串处理
{{ steps.data.result | upper }}
{{ steps.data.result | lower }}
{{ steps.data.result | title }}
{{ steps.data.result | replace('old', 'new') }}

# 数字处理
{{ steps.data.result | round(2) }}
{{ steps.data.result | int }}
{{ steps.data.result | abs }}

# 日期时间
{{ meta.start_time | datetime }}
{{ meta.start_time | date('Y-m-d') }}
{{ meta.start_time | time('H:i:s') }}

# 数据结构
{{ steps.data.result | to_json }}
{{ steps.data.result | from_json }}
{{ steps.data.result | length }}
{{ steps.data.result | first }}
{{ steps.data.result | last }}

# 默认值
{{ steps.data.result | default('fallback') }}
{{ steps.data.result | default('') }}
```

### 3. 条件表达式

```yaml
# 比较操作
{{ steps.step1.result.status == 'success' }}
{{ steps.step1.result.count > 0 }}
{{ steps.step1.result.value <= 100 }}

# 逻辑操作
{{ steps.step1.result.status == 'success' and steps.step2.result.count > 0 }}
{{ steps.step1.result.status == 'success' or steps.step2.result.status == 'success' }}
{{ not steps.step1.result.failed }}

# 成员测试
{{ 'item' in steps.step1.result.list }}
{{ steps.step1.result.status in ['success', 'partial'] }}

# 函数调用
{{ steps.step1.result.startswith('prefix') }}
{{ steps.step1.result.endswith('suffix') }}
```

---

## 流程控制

### 1. 条件分支 (switch)

```yaml
steps:
  check_status:
    action: "core/http_get"
    params:
      url: "https://api.example.com/status"
      
  process_by_status:
    switch:
      - condition: "{{ steps.check_status.result.status_code == 200 }}"
        steps:
          process_success:
            action: "core/process_data"
            params:
              data: "{{ steps.check_status.result.json }}"
              
      - condition: "{{ steps.check_status.result.status_code == 404 }}"
        steps:
          handle_not_found:
            action: "core/log"
            params:
              message: "数据未找到"
              level: "warning"
              
      - condition: "{{ steps.check_status.result.status_code >= 500 }}"
        steps:
          handle_server_error:
            action: "core/log"
            params:
              message: "服务器错误"
              level: "error"
              
      - default:  # 默认分支
          steps:
            handle_other:
              action: "core/log"
              params:
                message: "未知状态"
                level: "error"
```

### 2. 循环 (for_each)

```yaml
steps:
  fetch_items:
    action: "core/http_get"
    params:
      url: "https://api.example.com/items"
      
  process_each_item:
    for_each:
      items: "{{ steps.fetch_items.result.json.items }}"  # 要遍历的列表
      as: "item"                                          # 循环变量名
      index_as: "idx"                                    # 索引变量名（可选）
      parallel: false                                    # 是否并行执行（默认false）
    steps:
      process_item:
        action: "core/process_item"
        params:
          item: "{{ item }}"
          index: "{{ idx }}"
          
      log_progress:
        action: "core/log"
        params:
          message: "处理完成 {{ idx + 1 }}/{{ steps.fetch_items.result.json.items | length }}"
```

### 3. 条件循环 (while)

```yaml
steps:
  initialize_cursor:
    action: "core/set_variable"
    params:
      name: "cursor"
      value: ""
      
  fetch_pages:
    while:
      condition: "{{ cursor is not none }}"  # 循环条件
      max_iterations: 100                    # 最大迭代次数（可选）
    steps:
      fetch_page:
        action: "core/http_get"
        params:
          url: "https://api.example.com/data"
          params:
            cursor: "{{ cursor | default('') }}"
            
      update_cursor:
        action: "core/set_variable"
        params:
          name: "cursor"
          value: "{{ steps.fetch_page.result.json.next_cursor }}"
          
      process_page:
        action: "core/process_data"
        params:
          data: "{{ steps.fetch_page.result.json.data }}"
```

### 4. 异常处理 (try_catch)

```yaml
steps:
  risky_operation:
    try_catch:
      try:
        steps:
          fetch_data:
            action: "core/http_get"
            params:
              url: "{{ initial.api_endpoint }}"
              timeout: 30
              
          process_data:
            action: "core/process_data"
            params:
              data: "{{ steps.fetch_data.result.json }}"
              
      catch:
        - exception: "requests.exceptions.Timeout"
          steps:
            handle_timeout:
              action: "core/log"
              params:
                message: "请求超时，重试中..."
                level: "warning"
                
        - exception: "requests.exceptions.ConnectionError"
          steps:
            handle_connection_error:
              action: "core/log"
              params:
                message: "连接失败"
                level: "error"
                
        - exception: "*"  # 捕获所有其他异常
          steps:
            handle_other:
              action: "core/log"
              params:
                message: "未知错误: {{ exception.message }}"
                level: "error"
                
      finally:
        steps:
          cleanup:
            action: "core/cleanup_resources"
            params: {}
```

---

## 依赖管理

### 1. 基本依赖 (depends_on)

```yaml
steps:
  step1:
    action: "core/log"
    params:
      message: "第一步"
      
  step2:
    action: "core/log"
    params:
      message: "第二步"
    depends_on: ["step1"]  # 依赖step1完成
    
  step3:
    action: "core/log"
    params:
      message: "第三步"
    depends_on: ["step1"]  # 可以和step2并行执行
    
  step4:
    action: "core/log"
    params:
      message: "第四步"
    depends_on: ["step2", "step3"]  # 等待step2和step3都完成
```

### 2. 复杂依赖关系

```yaml
steps:
  # 数据准备阶段
  fetch_users:
    action: "core/http_get"
    params:
      url: "https://api.example.com/users"
      
  fetch_products:
    action: "core/http_get"
    params:
      url: "https://api.example.com/products"
      
  # 数据处理阶段（并行）
  process_users:
    action: "core/process_users"
    params:
      users: "{{ steps.fetch_users.result.json }}"
    depends_on: ["fetch_users"]
    
  process_products:
    action: "core/process_products"
    params:
      products: "{{ steps.fetch_products.result.json }}"
    depends_on: ["fetch_products"]
    
  # 数据关联阶段
  generate_recommendations:
    action: "core/generate_recommendations"
    params:
      users: "{{ steps.process_users.result }}"
      products: "{{ steps.process_products.result }}"
    depends_on: ["process_users", "process_products"]
    
  # 结果输出阶段
  save_results:
    action: "core/save_to_database"
    params:
      data: "{{ steps.generate_recommendations.result }}"
    depends_on: ["generate_recommendations"]
    
  send_notification:
    action: "core/send_email"
    params:
      subject: "推荐系统更新完成"
      body: "处理了 {{ steps.process_users.result.count }} 个用户的数据"
    depends_on: ["save_results"]
```

### 3. 条件依赖

```yaml
steps:
  check_source:
    action: "core/check_data_source"
    params:
      source: "{{ initial.data_source }}"
      
  fetch_from_api:
    action: "core/http_get"
    params:
      url: "https://api.example.com/data"
    condition: "{{ steps.check_source.result.type == 'api' }}"
    
  fetch_from_database:
    action: "core/query_database"
    params:
      query: "SELECT * FROM data_table"
    condition: "{{ steps.check_source.result.type == 'database' }}"
    
  process_data:
    action: "core/process_data"
    params:
      data: "{{ steps.fetch_from_api.result.json or steps.fetch_from_database.result }}"
    depends_on: ["fetch_from_api", "fetch_from_database"]
```

---

## Action库参考

### 1. 核心动作 (core)

#### 日志记录
```yaml
action: "core/log"
params:
  message: "日志消息"                    # 必需：日志内容
  level: "info"                         # 可选：日志级别 (debug, info, warning, error, critical)
  context: {}                          # 可选：额外上下文信息
```

#### 变量操作
```yaml
action: "core/set_variable"
params:
  name: "variable_name"                 # 必需：变量名
  value: "variable_value"               # 必需：变量值
  scope: "task"                         # 可选：作用域 (task, global, session)

action: "core/get_variable"
params:
  name: "variable_name"                 # 必需：变量名
  default: "default_value"              # 可选：默认值
```

#### HTTP请求
```yaml
action: "core/http_get"
params:
  url: "https://api.example.com"        # 必需：URL
  params: {}                           # 可选：查询参数
  headers: {}                          # 可选：请求头
  timeout: 30                          # 可选：超时时间
  auth: ["username", "password"]       # 可选：基本认证

action: "core/http_post"
params:
  url: "https://api.example.com"        # 必需：URL
  data: {}                             # 可选：请求数据
  json: {}                             # 可选：JSON数据
  headers: {}                          # 可选：请求头
  timeout: 30                          # 可选：超时时间
```

#### 文件操作
```yaml
action: "core/read_file"
params:
  path: "/path/to/file.txt"             # 必需：文件路径
  encoding: "utf-8"                     # 可选：编码格式

action: "core/write_file"
params:
  path: "/path/to/file.txt"             # 必需：文件路径
  content: "文件内容"                   # 必需：文件内容
  encoding: "utf-8"                     # 可选：编码格式
  append: false                         # 可选：是否追加

action: "core/list_files"
params:
  path: "/path/to/directory"            # 必需：目录路径
  pattern: "*.txt"                      # 可选：文件模式
  recursive: false                      # 可选：是否递归
```

#### 数据处理
```yaml
action: "core/parse_json"
params:
  data: '{"key": "value"}'              # 必需：JSON字符串

action: "core/format_json"
params:
  data: {"key": "value"}               # 必需：数据对象
  indent: 2                             # 可选：缩进

action: "core/merge_dicts"
params:
  dicts: [{"a": 1}, {"b": 2}]          # 必需：要合并的字典列表
  deep: false                          # 可选：是否深度合并
```

### 2. 视觉动作 (vision)

#### 图像查找
```yaml
action: "vision/find_image"
params:
  template: "template.png"              # 必需：模板图片路径
  region: [0, 0, 1920, 1080]            # 可选：搜索区域 [x, y, width, height]
  threshold: 0.8                        # 可选：匹配阈值

action: "vision/find_all_images"
params:
  template: "template.png"              # 必需：模板图片路径
  region: [0, 0, 1920, 1080]            # 可选：搜索区域
  threshold: 0.8                        # 可选：匹配阈值

action: "vision/wait_for_image"
params:
  template: "template.png"              # 必需：模板图片路径
  timeout: 10                           # 可选：超时时间
  interval: 0.5                         # 可选：检查间隔
```

#### 屏幕操作
```yaml
action: "vision/screenshot"
params:
  region: [0, 0, 1920, 1080]            # 可选：截图区域
  filename: "screenshot.png"            # 可选：保存文件名

action: "vision/click"
params:
  point: [100, 200]                     # 必需：点击坐标 [x, y]
  button: "left"                        # 可选：鼠标按钮
  clicks: 1                             # 可选：点击次数

action: "vision/move_mouse"
params:
  point: [100, 200]                     # 必需：目标坐标 [x, y]
  duration: 0.5                         # 可选：移动时间
```

### 3. OCR动作 (ocr)

#### 文本识别
```yaml
action: "ocr/recognize_text"
params:
  region: [0, 0, 1920, 1080]            # 可选：识别区域
  language: "chi_sim"                   # 可选：语言模型
  detail: 1                             # 可选：详细级别

action: "ocr/recognize_text_in_image"
params:
  image_path: "image.png"               # 必需：图片路径
  language: "chi_sim"                   # 可选：语言模型

action: "ocr/wait_for_text"
params:
  text: "目标文本"                      # 必需：要查找的文本
  region: [0, 0, 1920, 1080]            # 可选：搜索区域
  timeout: 10                           # 可选：超时时间
```

### 4. 应用控制动作 (app)

#### 窗口操作
```yaml
action: "app/focus_window"
params:
  title: "窗口标题"                     # 必需：窗口标题（支持正则表达式）
  timeout: 5                            # 可选：超时时间

action: "app/get_window_rect"
params:
  title: "窗口标题"                     # 必需：窗口标题

action: "app/move_window"
params:
  title: "窗口标题"                     # 必需：窗口标题
  rect: [100, 100, 800, 600]            # 必需：新位置和大小 [x, y, width, height]
```

#### 应用启动
```yaml
action: "app/launch"
params:
  path: "/path/to/application"          # 必需：应用路径
  args: []                             # 可选：启动参数
  wait_for_window: "窗口标题"           # 可选：等待窗口出现
  timeout: 10                          # 可选：超时时间

action: "app/close"
params:
  title: "窗口标题"                     # 必需：窗口标题
  force: false                         # 可选：是否强制关闭
```

---

## 高级用法

### 1. Jinja2模板

#### 复杂表达式

```yaml
steps:
  process_data:
    action: "core/process_data"
    params:
      # 使用if表达式
      mode: "{{ 'advanced' if steps.check.result.complex else 'basic' }}"
      
      # 使用数学运算
      offset: "{{ steps.get_base.result.value + 100 }}"
      
      # 使用字符串格式化
      filename: "data_{{ meta.start_time | date('Ymd_His') }}.json"
      
      # 使用列表推导式
      filtered_items: "{{ [item for item in steps.get_items.result if item.active] }}"
      
      # 使用字典操作
      config: "{{ dict(steps.base_config.result, **steps.override_config.result) }}"
```

#### 自定义过滤器

```yaml
# 使用内置过滤器链
steps:
  format_output:
    action: "core/format_string"
    params:
      template: "{{ steps.data.result | upper | replace(' ', '_') | truncate(50) }}"
```

### 2. 上下文变量生命周期

#### 任务级变量
```yaml
steps:
  set_task_var:
    action: "core/set_variable"
    params:
      name: "task_data"
      value: {"key": "value"}
      scope: "task"  # 只在当前任务中有效
      
  use_task_var:
    action: "core/log"
    params:
      message: "{{ task_data.key }}"
    depends_on: ["set_task_var"]
```

#### 会话级变量
```yaml
steps:
  set_session_var:
    action: "core/set_variable"
    params:
      name: "session_id"
      value: "{{ meta.start_time | timestamp }}"
      scope: "session"  # 在整个会话中有效
```

#### 全局变量
```yaml
steps:
  set_global_var:
    action: "core/set_variable"
    params:
      name: "api_token"
      value: "{{ initial.token }}"
      scope: "global"  # 在所有任务中有效
```

### 3. 动态步骤生成

```yaml
steps:
  get_config:
    action: "core/read_file"
    params:
      path: "config/processes.yaml"
      
  generate_steps:
    action: "core/generate_steps"
    params:
      template: |
        {% for process in steps.get_config.result.processes %}
        process_{{ process.name }}:
          action: "{{ process.action }}"
          params:
            {% for key, value in process.params.items() %}
            {{ key }}: {{ value }}
            {% endfor %}
          depends_on: ["get_config"]
        {% endfor %}
```

---

## 错误处理

### 1. 重试机制

```yaml
steps:
  unstable_api:
    action: "core/http_get"
    params:
      url: "https://unstable-api.example.com/data"
    retry: 5                          # 最多重试5次
    retry_delay: 2                    # 每次重试间隔2秒
    retry_on:
      - "requests.exceptions.ConnectionError"
      - "requests.exceptions.Timeout"
    retry_condition: "{{ steps.unstable_api.result.status_code >= 500 }}"
```

### 2. 失败处理

```yaml
steps:
  critical_operation:
    action: "core/critical_task"
    params:
      data: "{{ initial.critical_data }}"
    on_failure:
      action: "core/handle_failure"
      params:
        error: "{{ error }}"
        context: "{{ context }}"
        notify_admin: true
        save_error_log: true
```

### 3. 超时处理

```yaml
steps:
  long_running_task:
    action: "core/long_task"
    params:
      data: "{{ initial.large_dataset }}"
    timeout: 300                      # 5分钟超时
    on_timeout:
      action: "core/handle_timeout"
      params:
        save_partial_results: true
        notify_user: true
        cleanup_temp_files: true
```

### 4. 综合错误处理

```yaml
steps:
  robust_operation:
    try_catch:
      try:
        steps:
          validate_input:
            action: "core/validate"
            params:
              data: "{{ initial.input_data }}"
              
          process_data:
            action: "core/process"
            params:
              data: "{{ steps.validate_input.result }}"
            retry: 3
            timeout: 60
            
      catch:
        - exception: "ValidationError"
          steps:
            handle_validation_error:
              action: "core/log"
              params:
                message: "输入数据验证失败"
                level: "error"
              
        - exception: "TimeoutError"
          steps:
            handle_timeout:
              action: "core/log"
              params:
                message: "处理超时"
                level: "warning"
                
        - exception: "*"
          steps:
            handle_unknown:
              action: "core/log"
              params:
                message: "未知错误: {{ exception.message }}"
                level: "error"
                
      finally:
        steps:
          cleanup:
            action: "core/cleanup"
            params: {}
            
    on_failure:
      action: "core/notify_failure"
      params:
        task_name: "{{ meta.title }}"
        error_context: "{{ error }}"
```

---

## 实战示例

### 1. 简单线性流程

```yaml
# tasks/linear_process.yaml
meta:
  title: "简单数据处理流程"
  description: "从API获取数据并处理的线性流程"

steps:
  fetch_data:
    action: "core/http_get"
    params:
      url: "https://api.example.com/users"
      headers:
        Authorization: "Bearer {{ initial.api_token }}"
        
  validate_data:
    action: "core/validate_json"
    params:
      data: "{{ steps.fetch_data.result.json }}"
      schema: "user_list_schema"
    depends_on: ["fetch_data"]
    
  process_users:
    action: "core/process_users"
    params:
      users: "{{ steps.validate_data.result }}"
    depends_on: ["validate_data"]
    
  save_results:
    action: "core/save_to_database"
    params:
      table: "users"
      data: "{{ steps.process_users.result }}"
    depends_on: ["process_users"]
    
  send_notification:
    action: "core/send_email"
    params:
      to: "admin@example.com"
      subject: "用户数据更新完成"
      body: "成功处理了 {{ steps.process_users.result.count }} 个用户数据"
    depends_on: ["save_results"]

returns:
  processed_count: "{{ steps.process_users.result.count }}"
  status: "success"
```

### 2. 条件分支流程

```yaml
# tasks/conditional_process.yaml
meta:
  title: "条件数据处理流程"
  description: "根据数据源类型选择不同处理方式"

steps:
  detect_source:
    action: "core/detect_data_source"
    params:
      source: "{{ initial.data_source }}"
      
  process_by_type:
    switch:
      - condition: "{{ steps.detect_source.result.type == 'api' }}"
        steps:
          fetch_from_api:
            action: "core/http_get"
            params:
              url: "{{ initial.data_source }}"
              
          validate_api_data:
            action: "core/validate_api_response"
            params:
              response: "{{ steps.fetch_from_api.result }}"
              
          process_api_data:
            action: "core/process_api_data"
            params:
              data: "{{ steps.validate_api_data.result }}"
              
      - condition: "{{ steps.detect_source.result.type == 'database' }}"
        steps:
          connect_database:
            action: "database/connect"
            params:
              connection_string: "{{ initial.db_connection }}"
              
          query_data:
            action: "database/query"
            params:
              connection: "{{ steps.connect_database.result }}"
              query: "SELECT * FROM data_table"
              
          process_database_data:
            action: "core/process_database_data"
            params:
              rows: "{{ steps.query_data.result }}"
              
      - condition: "{{ steps.detect_source.result.type == 'file' }}"
        steps:
          read_file:
            action: "core/read_file"
            params:
              path: "{{ initial.data_source }}"
              
          parse_file:
            action: "core/parse_file"
            params:
              content: "{{ steps.read_file.result }}"
              format: "{{ steps.detect_source.result.format }}"
              
          process_file_data:
            action: "core/process_file_data"
            params:
              data: "{{ steps.parse_file.result }}"
              
      - default:
          steps:
            log_error:
              action: "core/log"
              params:
                message: "不支持的数据源类型: {{ steps.detect_source.result.type }}"
                level: "error"
                
            raise_error:
              action: "core/raise_exception"
              params:
                message: "数据源类型不支持"
                
  consolidate_results:
    action: "core/consolidate_results"
    params:
      api_result: "{{ steps.process_api_data.result | default(None) }}"
      db_result: "{{ steps.process_database_data.result | default(None) }}"
      file_result: "{{ steps.process_file_data.result | default(None) }}"
    depends_on: ["process_by_type"]

returns:
  final_result: "{{ steps.consolidate_results.result }}"
  source_type: "{{ steps.detect_source.result.type }}"
```

### 3. 并行处理流程

```yaml
# tasks/parallel_process.yaml
meta:
  title: "并行数据处理流程"
  description: "同时处理多个数据源的并行流程"

steps:
  # 数据获取阶段（并行）
  fetch_users:
    action: "core/http_get"
    params:
      url: "https://api.example.com/users"
      
  fetch_products:
    action: "core/http_get"
    params:
      url: "https://api.example.com/products"
      
  fetch_orders:
    action: "core/http_get"
    params:
      url: "https://api.example.com/orders"
      
  # 数据处理阶段（并行）
  process_users:
    action: "core/process_users"
    params:
      users: "{{ steps.fetch_users.result.json }}"
    depends_on: ["fetch_users"]
    
  process_products:
    action: "core/process_products"
    params:
      products: "{{ steps.fetch_products.result.json }}"
    depends_on: ["fetch_products"]
    
  process_orders:
    action: "core/process_orders"
    params:
      orders: "{{ steps.fetch_orders.result.json }}"
    depends_on: ["fetch_orders"]
    
  # 数据关联阶段（等待所有处理完成）
  generate_analytics:
    action: "core/generate_analytics"
    params:
      users: "{{ steps.process_users.result }}"
      products: "{{ steps.process_products.result }}"
      orders: "{{ steps.process_orders.result }}"
    depends_on: ["process_users", "process_products", "process_orders"]
    
  # 结果输出阶段
  save_analytics:
    action: "core/save_to_database"
    params:
      table: "analytics"
      data: "{{ steps.generate_analytics.result }}"
    depends_on: ["generate_analytics"]
    
  generate_reports:
    for_each:
      items: "{{ steps.generate_analytics.result.reports }}"
      as: "report"
      parallel: true                      # 并行生成报告
    steps:
      generate_report:
        action: "core/generate_report"
        params:
          report_type: "{{ report.type }}"
          data: "{{ report.data }}"
          
      send_report:
        action: "core/send_email"
        params:
          to: "{{ report.recipient }}"
          subject: "{{ report.title }}"
          attachment: "{{ steps.generate_report.result.file_path }}"
        depends_on: ["generate_report"]

returns:
  analytics_id: "{{ steps.save_analytics.result.id }}"
  report_count: "{{ steps.generate_analytics.result.reports | length }}"
  status: "success"
```

### 4. 循环处理流程

```yaml
# tasks/loop_process.yaml
meta:
  title: "循环数据处理流程"
  description: "处理分页数据的循环流程"

steps:
  initialize_pagination:
    action: "core/set_variable"
    params:
      name: "page"
      value: 1
      scope: "task"
      
  initialize_results:
    action: "core/set_variable"
    params:
      name: "all_results"
      value: []
      scope: "task"
      
  fetch_all_pages:
    while:
      condition: "{{ page is not none and page <= 100 }}"  # 最多100页
      max_iterations: 100
    steps:
      fetch_page:
        action: "core/http_get"
        params:
          url: "https://api.example.com/data"
          params:
            page: "{{ page }}"
            limit: 100
            
      process_page_data:
        action: "core/process_page"
        params:
          data: "{{ steps.fetch_page.result.json.data }}"
          page: "{{ page }}"
          
      update_results:
        action: "core/update_variable"
        params:
          name: "all_results"
          operation: "extend"
          value: "{{ steps.process_page_data.result }}"
          
      check_next_page:
        action: "core/set_variable"
        params:
          name: "page"
          value: "{{ steps.fetch_page.result.json.next_page }}"
          condition: "{{ steps.fetch_page.result.json.has_next }}"
          
      log_progress:
        action: "core/log"
        params:
          message: "已处理 {{ page - 1 }} 页，共 {{ all_results | length }} 条记录"
          level: "info"
          
      rate_limit:
        action: "core/sleep"
        params:
          seconds: 1                      # 避免API限流
          
  consolidate_final_results:
    action: "core/consolidate"
    params:
      data: "{{ all_results }}"
    depends_on: ["fetch_all_pages"]
    
  save_final_results:
    action: "core/save_to_database"
    params:
      table: "processed_data"
      data: "{{ steps.consolidate_final_results.result }}"
    depends_on: ["consolidate_final_results"]

returns:
  total_records: "{{ all_results | length }}"
  total_pages: "{{ page - 1 }}"
  processing_time: "{{ meta.duration }}"
  status: "success"
```

### 5. 错误处理流程

```yaml
# tasks/error_handling.yaml
meta:
  title: "健壮的错误处理流程"
  description: "包含完整错误处理机制的流程示例"

steps:
  main_process:
    try_catch:
      try:
        steps:
          validate_input:
            action: "core/validate_input"
            params:
              data: "{{ initial.input_data }}"
              schema: "input_schema"
              
          fetch_external_data:
            action: "core/http_get"
            params:
              url: "https://api.example.com/data"
              timeout: 30
            retry: 3
            retry_delay: 2
            retry_on:
              - "requests.exceptions.ConnectionError"
              - "requests.exceptions.Timeout"
              
          process_combined_data:
            action: "core/process_data"
            params:
              local_data: "{{ steps.validate_input.result }}"
              external_data: "{{ steps.fetch_external_data.result.json }}"
            timeout: 120
            
          save_results:
            action: "core/save_to_database"
            params:
              data: "{{ steps.process_combined_data.result }}"
              table: "results"
              
          send_success_notification:
            action: "core/send_email"
            params:
              to: "{{ initial.admin_email }}"
              subject: "数据处理成功"
              body: "成功处理了 {{ steps.process_combined_data.result.count }} 条记录"
            depends_on: ["save_results"]
            
      catch:
        - exception: "ValidationError"
          steps:
            log_validation_error:
              action: "core/log"
              params:
                message: "输入数据验证失败"
                level: "error"
                context: "{{ exception }}"
                
            send_validation_alert:
              action: "core/send_email"
              params:
                to: "{{ initial.admin_email }}"
                subject: "数据验证失败"
                body: "错误详情: {{ exception.message }}"
                
        - exception: "requests.exceptions.ConnectionError"
          steps:
            log_connection_error:
              action: "core/log"
              params:
                message: "外部API连接失败"
                level: "error"
                
            try_fallback_api:
              action: "core/http_get"
              params:
                url: "https://fallback-api.example.com/data"
                
            use_fallback_data:
              action: "core/process_data"
              params:
                local_data: "{{ steps.validate_input.result }}"
                external_data: "{{ steps.try_fallback_api.result.json | default({}) }}"
                
        - exception: "*"
          steps:
            log_unknown_error:
              action: "core/log"
              params:
                message: "未知错误发生"
                level: "error"
                context: "{{ exception }}"
                
            send_error_alert:
              action: "core/send_email"
              params:
                to: "{{ initial.admin_email }}"
                subject: "系统错误警报"
                body: |
                  发生未知错误:
                  错误类型: {{ exception.type }}
                  错误消息: {{ exception.message }}
                  堆栈跟踪: {{ exception.traceback }}
                
      finally:
        steps:
          cleanup_temp_files:
            action: "core/delete_files"
            params:
              pattern: "/tmp/process_*.tmp"
              
          update_task_status:
            action: "core/set_variable"
            params:
              name: "task_completed"
              value: true
              scope: "session"
              
  final_status:
    action: "core/log"
    params:
      message: "任务执行完成，状态: {{ 'success' if not error else 'failed' }}"
      level: "info"
    depends_on: ["main_process"]

returns:
  success: "{{ not error }}"
  error_type: "{{ error.type if error else None }}"
  error_message: "{{ error.message if error else None }}"
  processed_count: "{{ steps.process_combined_data.result.count if not error else 0 }}"
```

---

## 最佳实践

### 1. 任务设计原则

#### 保持简单
- 每个任务应该只负责一个明确的功能
- 复杂任务应该分解为多个简单任务
- 使用清晰的步骤命名

#### 错误处理
- 总是考虑可能的错误情况
- 提供有意义的错误消息
- 使用适当的日志级别

#### 性能优化
- 合理使用并行执行
- 避免不必要的同步等待
- 使用缓存减少重复计算

### 2. 模板使用技巧

#### 避免复杂逻辑
```yaml
# 好的做法：在Action中处理复杂逻辑
steps:
  prepare_data:
    action: "core/prepare_complex_data"
    params:
      input: "{{ initial.raw_data }}"
      
# 避免：在模板中写复杂逻辑
steps:
  bad_example:
    action: "core/process"
    params:
      # 避免复杂的模板表达式
      data: "{{ [x for x in initial.data if x.active and x.created_date > (meta.start_time - 86400)] }}"
```

#### 使用默认值
```yaml
steps:
  safe_operation:
    action: "core/safe_process"
    params:
      # 使用默认值避免错误
      timeout: "{{ initial.timeout | default(30) }}"
      retry_count: "{{ initial.retry_count | default(3) }}"
      api_url: "{{ initial.api_url | default('https://api.example.com') }}"
```

### 3. 调试技巧

#### 添加调试信息
```yaml
steps:
  debug_operation:
    action: "core/log"
    params:
      message: "调试信息"
      level: "debug"
      context:
        input_data: "{{ initial.input_data }}"
        current_step: "process_data"
        timestamp: "{{ meta.current_time }}"
```

#### 使用条件调试
```yaml
steps:
  conditional_debug:
    action: "core/log"
    params:
      message: "详细调试信息"
      level: "debug"
    condition: "{{ initial.debug_mode }}"
```

### 4. 安全性考虑

#### 敏感信息处理
```yaml
steps:
  secure_api_call:
    action: "core/http_get"
    params:
      url: "https://api.example.com/data"
      headers:
        # 使用环境变量或安全存储
        Authorization: "Bearer {{ env.API_TOKEN }}"
        # 避免在任务文件中硬编码敏感信息
        # 错误做法: Authorization: "Bearer hardcoded_token"
```

#### 输入验证
```yaml
steps:
  validate_and_process:
    action: "core/validate_and_process"
    params:
      data: "{{ initial.user_input }}"
      validation_rules:
        - field: "email"
          type: "email"
          required: true
        - field: "age"
          type: "integer"
          min: 18
          max: 120
```

---


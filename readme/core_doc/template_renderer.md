---
# 核心模块: `template_renderer.py`

## 概览
`TemplateRenderer` 基于 Jinja2 `NativeEnvironment`，支持异步渲染并返回原生类型。

## 作用域结构
- `state`: `StateStoreService` 持久化状态
- `initial`: 触发器/系统提供的初始数据（通常为空）
- `inputs`: 任务输入参数
- `loop`: 循环变量（`item` / `index`）
- `nodes`: 节点执行结果

## 渲染规则
- 递归渲染 dict / list / str
- 未定义变量会返回 `None` 并记录警告
- 不提供 `config()` helper，配置请通过 Service/Action 获取

## 示例
```yaml
steps:
  greet:
    action: log
    params:
      message: "Hello, {{ inputs.name }}"
```

```yaml
steps:
  fetch:
    action: http.get
    params:
      url: "{{ inputs.url }}"
    outputs:
      status: "{{ result.status_code }}"
      body: "{{ result.text }}"
```

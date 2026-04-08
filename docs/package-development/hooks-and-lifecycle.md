# Hook 与生命周期

Aura 当前对 package 生命周期支持两层概念：

- manifest 中声明的 lifecycle hook
- registry 中的 hook manager 触发点

## 1. Manifest 生命周期

manifest 支持：

- `on_install`
- `on_uninstall`
- `on_load`
- `on_unload`

格式：

```yaml
lifecycle:
  on_load: "src.bootstrap:init_plugin"
```

值必须是：

```text
module:function
```

`PackageManager` 会在加载过程中解析并调用对应函数。

## 2. `@register_hook`

```python
from packages.aura_core.api.decorators import register_hook


@register_hook("before_task_run")
def before_task_run(task_context):
    ...
```

这个装饰器只负责给函数附加 hook 名，实际注册和触发由 hook manager 负责。

## 3. 当前运行时中的关键 hook 触发点

`ExecutionManager.submit()` 会触发：

- `before_task_run`
- `after_task_success`
- `after_task_failure`
- `after_task_run`

它们都接收 `task_context`。

## 4. `task_context` 常见内容

执行前后会逐步补齐：

- `tasklet`
- `start_time`
- `end_time`
- `result`
- `exception`

适合用于：

- 任务级审计
- 执行统计
- 统一告警

## 5. Manifest lifecycle 与 runtime hook 的区别

### manifest lifecycle

- 面向 package 装载/卸载
- 由 `PackageManager` 调用
- 更适合初始化 package 级资源

### runtime hook

- 面向任务执行生命周期
- 由 hook manager 在执行阶段触发
- 更适合记录 task 运行结果或附加运行行为

## 6. 注意事项

- lifecycle hook 函数导入失败时会记录 warning
- hook 名称必须和 runtime 触发点匹配
- 不要在 hook 中假设 scheduler 一定运行在当前线程

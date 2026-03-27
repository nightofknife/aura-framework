# Hot Reload

Aura 当前支持基于 watchdog 的热重载。

## 1. 监控范围

当前监控的是 `base_path / plans` 目录。

会响应两类变化：

- `tasks` 目录下的 `.yaml`
- 任意 `.py`

忽略：

- 目录事件
- 隐藏文件
- `__pycache__`

## 2. 重载路径

### task YAML 改动

- 记录 task file changed
- 在 control loop 上调用 `scheduler.reload_task_file(file_path)`

### Python 改动

- 记录 python file changed
- 在 control loop 上调用 `scheduler.reload_plugin_from_py_file(file_path)`

## 3. 开启条件

热重载只能在 scheduler 已启动时开启。

否则会返回 scheduler not running 错误。

## 4. 管理接口

Scheduler 当前公开：

- `enable_hot_reload()`
- `disable_hot_reload()`
- `is_hot_reload_enabled()`
- `reload_task_file()`
- `reload_plugin_from_py_file()`

## 5. 使用建议

- 开发 task YAML 时优先使用 task 文件热重载
- 开发 package Python 代码时注意导入副作用
- 如果热重载状态异常，先关闭再重新开启

## 6. 限制

- 依赖 watchdog
- 只监控 `plans` 路径
- 热重载不等于完全无状态

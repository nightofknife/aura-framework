# Python 运行环境与入口

Aura 当前默认使用 Python 3.13 虚拟环境：

- venv 路径：`D:\Aura\Aura\.venv\Scripts\python.exe`
- 默认基础解释器：`C:\Python313\python.exe`

## 1. 初始化运行环境

在仓库根目录执行：

```powershell
.\scripts\setup_python_runtime.ps1
```

自定义基础解释器：

```powershell
.\scripts\setup_python_runtime.ps1 -BasePython "D:\Aura\_runtime\python313\python.exe"
```

关键行为：

- 强制基础 Python 为 `3.13.x`
- 创建或复用 `.venv`
- 强制 `include-system-site-packages = false`
- 安装 `requirements/runtime.lock`，或在 `-UseLock:$false` 时按 `requirements/runtime.txt` 安装并重新生成 lock
- 运行 `pip check`

## 2. 启动前校验

推荐在打包、发版或切换依赖后执行：

```powershell
.\scripts\build_preflight.ps1
```

当前会检查：

- `.venv` 必须是 Python 3.13
- `include-system-site-packages = false`
- `PYTHONNOUSERSITE=1` 生效
- 已安装包与 `requirements/runtime.lock` 一致
- `pip check` 通过
- `cli.py --help` 可运行
- `backend.api.app:create_app()` 可创建
- `GET /api/v1/system/health` 的 smoke test 通过

## 3. 启动入口

### PowerShell 脚本启动 API

```powershell
.\scripts\start_api.ps1
```

示例：

```powershell
.\scripts\start_api.ps1 -Host 0.0.0.0 -Port 8000 -LogLevel debug
```

脚本行为：

- 设置 `PYTHONNOUSERSITE=1`
- 调用 `python cli.py api serve`

### CLI 启动 API

```powershell
.venv\Scripts\python.exe cli.py api serve
```

常用参数：

- `--host`
- `--port`
- `--reload`
- `--log-level`
- `--workers`
- `--access-log`

默认端口来自 `backend.run.serve_api()`，是 `18098`。脚本 `start_api.ps1` 默认传入 `8000`，因此两种启动方式的默认端口不同。

### CLI 启动 TUI

```powershell
.venv\Scripts\python.exe cli.py tui
```

说明：

- TUI 入口使用 `tui_manual` profile
- 需要 `prompt_toolkit`
- 适合手动执行 entry task 或 schedule item，不启用自动调度、事件触发和中断循环

## 4. 其他可用入口

### API 服务主入口

```powershell
.venv\Scripts\python.exe -c "from backend.run import serve_api; serve_api()"
```

### package manifest 工具

```powershell
.venv\Scripts\python.exe packages\aura_core\cli\package_cli.py --help
```

支持的命令：

- `init`
- `build`
- `sync`
- `check`
- `validate`
- `info`

## 5. 依赖文件

- `requirements/runtime.txt`
  运行时直接依赖清单
- `requirements/runtime.lock`
  锁定依赖版本，用于可复现环境

重新生成 lock：

```powershell
.\scripts\setup_python_runtime.ps1 -UseLock:$false
```

## 6. 下一步

- 阅读 [架构总览](./02-architecture-overview.md)
- 开始编写任务时阅读 [任务 YAML 指南](./03-task-yaml-guide.md)
- 需要理解执行语义时阅读 [运行时行为](./04-runtime-behavior.md)

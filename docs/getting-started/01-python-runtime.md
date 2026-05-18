# Python 运行环境与入口

Aura 当前正式定义为一个 `Windows 本机桌面自动化工作区`。本仓库支持的部署方式只有一种：

- Windows
- PowerShell
- Python 3.13
- `venv`

本轮不支持 Docker、Poetry、`pyproject.toml` 迁移，也不把当前仓库定义成可直接裁剪成纯 headless core 的安装包。

## 1. 依赖档位

仓库使用 `requirements/` 下的 profile 分层：

- `workspace-default`
  默认运行时安装档。覆盖 API、scheduler，以及 `plans/aura_base` 的硬依赖。
- `test`
  pytest 和测试工具，只装到 `.venv-test`。
- `yolo`
  仅补 `ultralytics`，默认不装。
- `framework-core`
  仅供未来纯框架仓库或最小 smoke 使用，不是本仓库默认安装档。

V1 边界约定：

- `aura_core` 是框架核心。
- `plans/aura_base` 是官方 desktop capability package。
- `workspace-default` 是当前仓库默认工作区 profile。
- `framework-core` 用于验证 core 最小能力，不应隐式要求 OCR、视觉、键鼠或 YOLO 依赖。

`workspace-default` 当前包含的关键硬依赖：

- `opencv-python`
- `numpy`
- `pywin32`
- `screeninfo`
- `paddleocr`
- `cachetools`

`dxcam` 和 `mss` 仍然是可选 capture backend，不进入默认安装档。默认 capture backend 是 `gdi`，`dxgi` / `mss` 属于可选增强。

## 2. 安装 runtime

在仓库根目录执行：

```powershell
.\scripts\setup_python_runtime.ps1
```

默认行为：

- 使用 `workspace-default`
- 创建或复用 `.venv`
- 强制 Python `3.13.x`
- 强制 `include-system-site-packages = false`
- 优先按 `requirements/workspace-default.lock` 安装
- 运行 `pip check`

指定基础解释器：

```powershell
.\scripts\setup_python_runtime.ps1 -BasePython "C:\Python313\python.exe"
```

重新生成 runtime lock：

```powershell
.\scripts\setup_python_runtime.ps1 -UseLock:$false
```

说明：

- `requirements/runtime.txt` 和 `requirements/runtime.lock` 现在只是对 `workspace-default` 的包装入口。
- `plans/aura_base/requirements.txt` 不再单独维护真源，直接回指主 requirements 体系。

## 3. 安装测试环境

测试环境单独使用 `.venv-test`，避免 runtime lock 和 pytest 工具链混装：

```powershell
.\scripts\setup_test_runtime.ps1
```

包含 yolo profile：

```powershell
.\scripts\setup_test_runtime.ps1 -IncludeYolo
```

默认安装：

- `workspace-default`
- `test`

可选附加：

- `yolo`

## 4. 运行 preflight

`build_preflight.ps1` 只校验 runtime 环境 `.venv`：

```powershell
.\scripts\build_preflight.ps1
```

当前覆盖：

- Python 版本
- venv 隔离
- lock 一致性
- `pip check`
- `cli.py --help`
- `import backend.run`
- `create_app()` smoke
- `GET /api/v1/system/health`

## 5. 运行测试

固定从 `.venv-test` 运行：

```powershell
.\scripts\run_tests.ps1
```

默认 marker 表达式：

```text
not yolo and not slow
```

包含 yolo：

```powershell
.\scripts\run_tests.ps1 -IncludeYolo
```

pytest 分层：

- `unit`
- `api`
- `security`
- `desktop`
- `yolo`
- `slow`

## 6. 校验 Plan 与任务 YAML

V1 提供不执行 action 的静态校验入口：

```powershell
.venv-test\Scripts\python.exe cli.py validate
```

只校验某个 plan：

```powershell
.venv-test\Scripts\python.exe cli.py validate --plan aura_benchmark
```

输出 JSON：

```powershell
.venv-test\Scripts\python.exe cli.py validate --plan aura_benchmark --format json
```

校验单个任务并做 dry-run：

```powershell
.venv-test\Scripts\python.exe cli.py validate --plan aura_benchmark --dry-run --task-ref tasks:single_sleep.yaml
```

说明：

- validate 会解析 manifest 和 task YAML。
- validate 会检查 schema、`depends_on`、`task_ref`、输入 schema 和 action 引用格式。
- dry-run 不执行截图、键鼠、OCR、进程、文件写入等副作用 action。
- `--strict` 会要求 bare action 已在当前 plan manifest exports 中声明。

## 7. 启动 API

统一默认端口是 `18098`。

PowerShell 入口：

```powershell
.\scripts\start_api.ps1
```

CLI 入口：

```powershell
.venv\Scripts\python.exe cli.py api serve
```

GUI 默认连接：

```text
http://127.0.0.1:18098/api/v1
```

远程绑定示例：

```powershell
$env:AURA_API_REMOTE_ENABLED = "1"
$env:AURA_API_AUTH_KEY = "change-me"
$env:AURA_API_TRUSTED_HOSTS = "api.example,127.0.0.1"
.\scripts\start_api.ps1 -Host 0.0.0.0 -Port 18098
```

## 8. API 安全边界

默认模式是 `local_only`：

- 只允许 loopback bind
- 只允许 loopback client 访问受保护路由
- 本地 GUI 不需要 API key

公开路由只有：

- `GET /api/v1/system/health`
- `GET /api/v1/system/status`

remote mode 规则：

- 绑定非 loopback host 时，必须显式设置 `AURA_API_REMOTE_ENABLED=1`
- 必须提供 `AURA_API_AUTH_KEY`
- 必须提供 `AURA_API_TRUSTED_HOSTS`
- 受保护路由统一要求 `X-Aura-Api-Key`

高风险兼容接口默认关闭：

- `AURA_API_ENABLE_LOGS=1`
- `AURA_API_ENABLE_PLAN_EDITING=1`
- `AURA_API_ENABLE_HOT_RELOAD_ADMIN=1`

示例环境变量见根目录：

- [`.env.example`](/E:/aura/aura-framework/.env.example)
- [`config.example.yaml`](/E:/aura/aura-framework/config.example.yaml)

## 9. 下一步

- 阅读 [架构总览](./02-architecture-overview.md)
- 阅读 [本机 API 部署约定](../runtime-operations/local-api-deployment.md)
- 开始编写任务时阅读 [任务 YAML 指南](./03-task-yaml-guide.md)

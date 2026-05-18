# 本机 API 部署约定

## 支持范围

当前仓库只定义一种受支持的部署模式：

- Windows 本机
- PowerShell
- Python 3.13
- `venv`

本轮不引入：

- Docker
- Poetry
- `pyproject.toml`
- Windows Service 安装器
- 额外打包系统

## 三个固定入口

安装 runtime：

```powershell
.\scripts\setup_python_runtime.ps1
```

安装 test 环境：

```powershell
.\scripts\setup_test_runtime.ps1
```

启动 API：

```powershell
.\scripts\start_api.ps1
```

GUI 默认连接：

```text
http://127.0.0.1:18098/api/v1
```

## 依赖约定

默认工作区安装档必须使用 `workspace-default`。

原因：

- 当前工作区会 eager-import `plans/aura_base` 的 service / action
- 默认运行时不能假设存在一个可以直接运行的纯 headless core
- `framework-core` 只用于未来拆仓或最小 smoke

默认档之外的能力：

- `yolo`: 通过 `requirements/yolo.txt` 单独补装 `ultralytics`
- `dxcam` / `mss`: 保持可选 capture backend

默认 capture backend 是 `gdi`。

## 端口与配置

默认 host / port：

- host: `127.0.0.1`
- port: `18098`

示例配置文件：

- [`.env.example`](/E:/aura/aura-framework/.env.example)
- [`config.example.yaml`](/E:/aura/aura-framework/config.example.yaml)

说明：

- `AURA_BASE_PATH` 指向工作区根目录
- `AURA_STATE_STORE__PATH` 使用双下划线分隔层级，以保留 `state_store` 里的下划线
- `logging.log_dir` 可用 `AURA_LOGGING_LOG_DIR`

## 安全模型

默认模式：`local_only`

- 只允许 loopback bind
- 只允许 loopback request 访问受保护路由
- 本地 GUI 不要求 API key

只有以下公开路由对所有请求开放：

- `GET /api/v1/system/health`
- `GET /api/v1/system/status`

remote mode：

- 必须显式设置 `AURA_API_REMOTE_ENABLED=1`
- 必须设置 `AURA_API_AUTH_KEY`
- 必须设置 `AURA_API_TRUSTED_HOSTS`
- 受保护路由必须携带 `X-Aura-Api-Key`
- 开启 remote mode 后启用 `TrustedHostMiddleware`
- CORS 默认关闭，只在显式配置时打开

## 高风险兼容路由

默认关闭：

- `/api/v1/system/logs`
- `/api/v1/system/hot_reload/*`
- `/api/v1/plans/{plan}/files/*`
- `DELETE /api/v1/plans/{plan}`

显式开关：

- `AURA_API_ENABLE_LOGS=1`
- `AURA_API_ENABLE_PLAN_EDITING=1`
- `AURA_API_ENABLE_HOT_RELOAD_ADMIN=1`

本轮没有重写 plan 内路径校验逻辑，只是在网络暴露和权限边界上收口。

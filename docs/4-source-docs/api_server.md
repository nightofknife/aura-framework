# 文件: `api_server.py`

## 1. 核心目的

该文件使用 FastAPI 框架实现 Aura 系统的 RESTful API 服务器。它是整个 Aura 框架的主要外部接口，负责处理来自 Web UI 或第三方应用的所有 HTTP 请求。其核心职责是将标准的 HTTP 请求转化为对内部 `Scheduler` 服务的调用，从而实现对框架的控制、监控和交互。

## 2. 关键组件与功能

*   **`app = FastAPI(...)`**: 全局 FastAPI 应用实例，是整个 API 服务器的基石。

*   **`scheduler = Scheduler()`**: 全局的 `Scheduler` 核心实例。API 服务器中的几乎所有操作最终都会委托给这个实例来处理，`api_server.py` 本身不包含复杂的业务逻辑。

*   **`LogConnectionManager`**: 一个用于管理 WebSocket 连接的辅助类。它维护一个所有已连接客户端的列表，并提供向所有客户端广播日志消息的功能，是实现实时日志流的关键。

*   **`log_queue_listener()`**: 一个在后台运行的异步任务（`asyncio.Task`）。它持续不断地从 `scheduler.api_log_queue` 中获取日志条目，并通过 `LogConnectionManager` 将这些日志实时广播给所有连接的 WebSocket 客户端。

*   **Pydantic 模型 (例如 `AdHocTaskRequest`, `SystemStatusResponse`)**: 这些类定义了 API 端点的请求体和响应体的数据结构。FastAPI 利用它们来进行自动的数据校验、转换和文档生成，极大地提高了 API 的健壮性和可维护性。

*   **API 端点 (Endpoints)**:
    *   **系统控制 (`/api/system/...`)**: 提供启动 (`/start`)、停止 (`/stop`) 和查询状态 (`/status`) 等基本控制功能。
    *   **资源发现 (`/api/plans/...`)**: 允许客户端发现框架中加载了哪些 Plans (`/api/plans`) 以及每个 Plan 下有哪些具体的 Tasks (`/api/plans/{plan_name}/tasks`)。
    *   **任务执行 (`/api/tasks/run`, `/api/tasks/batch`)**: 核心功能入口，允许用户提交单个或批量的任务以供执行。
    *   **任务管理 (`/api/tasks/{cid}/...`)**: 提供对正在运行或排队中任务的控制能力，例如取消 (`/cancel`) 或调整优先级 (`/priority`)。
    *   **状态监控 (`/api/runs/active`, `/api/queue/...`)**: 提供对系统内部状态的洞察，例如当前活跃的任务、队列的概览和内容等。
    *   **WebSocket 日志流 (`/ws/logs`)**: 唯一的 WebSocket 端点，专门用于向客户端实时推送框架日志。

## 3. 核心逻辑解析

`api_server.py` 的设计哲学是**“瘦AP层，胖服务层”**。它的核心逻辑在于将 HTTP 协议的交互模型优雅地适配到 Aura 内部基于事件和队列的异步模型。

以**执行单个临时任务 (`/api/tasks/run`)** 的端点为例，其处理流程充分体现了这一设计：

1.  **接收与校验**: 当一个 `POST` 请求到达 `/api/tasks/run` 时，FastAPI 首先会根据 `AdHocTaskRequest` 这个 Pydantic 模型来解析和校验请求体 (JSON)。如果请求体缺少字段（如 `plan_name`）或字段类型不匹配，FastAPI 会自动拒绝该请求并返回 `422 Unprocessable Entity` 错误，这一步完全自动化，无需在端点函数中编写任何校验代码。

2.  **委托给核心服务**: 端点函数 `run_ad_hoc_task` 的实现非常简洁。它直接调用 `scheduler.run_ad_hoc_task()` 方法，并将从请求中解析出的 `plan_name`, `task_name` 和 `inputs` 作为参数传递过去。

3.  **异步解耦**: `scheduler.run_ad_hoc_task()` 方法内部会将这个任务请求封装成一个 `Tasklet` 对象，并将其放入一个异步任务队列 (`asyncio.Queue`) 中。这个放入队列的操作通常非常快，因此 API 调用可以几乎立即返回响应给客户端，告知其“任务已成功入队”，而无需等待任务实际执行完成。这种设计使得 API 具备了高吞吐和高响应性的特点。

4.  **错误处理**: 如果 `scheduler.run_ad_hoc_task()` 在入队前检测到错误（例如，找不到对应的 Plan 或 Task），它会返回一个包含错误信息的字典。API 端点会检查这个返回值，如果发现是错误状态，就会通过 `raise HTTPException(...)` 将其转化为一个标准的 HTTP 错误响应（例如 `400 Bad Request`），并附带清晰的错误信息。

通过这种方式，`api_server.py` 成功地将无状态、请求-响应式的 HTTP 协议与 Aura 框架内部有状态、异步的执行模型解耦，使其成为一个职责单一、清晰高效的外部网关。
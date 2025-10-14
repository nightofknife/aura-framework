# -*- coding: utf-8 -*-
"""Aura 框架的 FastAPI 服务器。

该模块提供了用于控制和监控 Aura 自动化框架的实时 API 服务器。
它利用 FastAPI 构建 RESTful API 端点，并通过 WebSocket 将实时事件和日志
流式传输到客户端（如 Aura GUI）。

主要功能:
- **系统控制**: 启动、停止、重载和获取 Aura 调度器的状态。
- **资源发现**: 列出所有已加载的方案（Plans）和任务（Tasks）。
- **任务执行**: 支持以临时（Ad-hoc）方式触发任何任务的执行。
- **状态监控**: 提供对活动任务、任务队列和历史运行时间线的洞察。
- **实时通信**: 使用 WebSocket 将核心事件和日志实时推送到前端。
- **热重载**: 支持动态启用或禁用插件的自动热重载功能。
"""

import asyncio
import logging
from typing import List, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 导入你的核心Aura Scheduler
from packages.aura_core.scheduler import Scheduler
from packages.aura_core.event_bus import Event

# --- 1. 全局核心实例 ---
# 这是整个API服务器的“大脑”，它持有并管理Aura框架的实例。
# 我们在启动时将日志级别设置为DEBUG，以便捕获所有日志进行流式传输。
# 注意：logger.setup() 在 Scheduler 的 __init__ 中已经调用过一次，
# 这里的调用是为了确保API日志队列被正确设置。
logger = logging.getLogger("AuraFramework")
logger.setLevel(logging.DEBUG)

app = FastAPI(
    title="Aura Framework API",
    description="A real-time API server to control and observe the Aura automation framework.",
    version="1.0.0"
)
scheduler = Scheduler()

# --- 2. CORS中间件 ---
# 允许你的Electron GUI（其源通常是 http://localhost:xxxx）访问此API。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应收紧为你的GUI的具体地址
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 3. WebSocket 连接管理器 ---
class ConnectionManager:
    """管理所有活跃的 WebSocket 连接。

    这是一个辅助类，用于跟踪所有连接到服务器的客户端，并提供向所有客户端
    广播消息的功能。

    Attributes:
        active_connections (List[WebSocket]): 当前活跃的 WebSocket 连接列表。
    """
    def __init__(self):
        """初始化 ConnectionManager。"""
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """接受一个新的 WebSocket 连接并将其添加到活跃连接列表。

        Args:
            websocket (WebSocket): 要接受的 WebSocket 连接对象。
        """
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """从活跃连接列表中移除一个已断开的 WebSocket 连接。

        Args:
            websocket (WebSocket): 要移除的 WebSocket 连接对象。
        """
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """向所有活跃的 WebSocket 连接广播一条 JSON 消息。

        此方法会并发地将消息发送给所有客户端，以提高效率。

        Args:
            message (dict): 要发送的 JSON 消息体（以字典形式）。
        """
        tasks = [connection.send_json(message) for connection in self.active_connections]
        await asyncio.gather(*tasks, return_exceptions=True)


manager = ConnectionManager()


# --- 4. 后台任务：连接Aura核心与WebSocket的桥梁 ---
async def event_bus_listener(event: Event):
    """订阅 Aura 事件总线的回调函数。

    每当框架内部发布一个事件，此函数就会被调用，并将事件数据通过 WebSocket
    广播到所有连接的客户端。

    Args:
        event (Event): 从事件总线接收到的事件对象。
    """
    await manager.broadcast({"type": "event", "payload": event.to_dict()})


async def log_queue_listener():
    """持续从 Aura 日志队列中消费日志记录并进行广播。

    这是一个异步的、长时运行的后台任务。它安全地从线程安全的日志队列中获取
    日志条目，并将其通过 WebSocket 广播出去，从而避免阻塞主事件循环。
    """
    logger.info("Log queue listener started. Awaiting logs...")
    loop = asyncio.get_running_loop()
    while True:
        try:
            # 在一个单独的线程中执行阻塞的 get() 方法，然后 await 它的结果
            # 这可以防止阻塞 FastAPI 的主事件循环
            log_entry = await loop.run_in_executor(
                None,  # 使用默认的线程池
                scheduler.api_log_queue.get
            )

            await manager.broadcast({"type": "log", "payload": log_entry})
            # 注意：由于 get() 是阻塞的，task_done() 必须在它成功返回后调用
            loop.run_in_executor(None, scheduler.api_log_queue.task_done)
        except Exception as e:
            # 使用print以防日志系统本身出问题
            print(f"CRITICAL: Log listener background task failed: {e}")
            await asyncio.sleep(1)  # 发生错误时稍作等待


@app.on_event("startup")
async def startup_event():
    """FastAPI 应用启动时执行的钩子函数。

    此函数负责启动所有必要的后台任务，将 Aura 核心与 WebSocket 世界连接起来，
    包括日志监听器和事件总线订阅者。
    """
    # 获取当前（FastAPI的）事件循环
    current_loop = asyncio.get_running_loop()

    # 启动日志监听器
    asyncio.create_task(log_queue_listener())

    # 将我们的WebSocket广播回调订阅到EventBus
    # 订阅时，传入当前循环，以便EventBus知道如何安全地调用它
    await scheduler.event_bus.subscribe(
        event_pattern='*',
        callback=event_bus_listener,
        channel='*',
        loop=current_loop,
        persistent=True,
    )
    logger.info("Aura API server started. WebSocket listeners are active.")


# --- 5. Pydantic API 模型 ---
# 使用Pydantic模型能让FastAPI自动进行数据验证和生成API文档，非常强大。
class SystemStatusResponse(BaseModel):
    """系统状态响应的数据模型。"""
    is_running: bool


class PlanResponse(BaseModel):
    """方案信息响应的数据模型。"""
    name: str
    task_count: int


class TaskMeta(BaseModel):
    """任务元数据的数据模型。"""
    title: str | None = None
    description: str | None = None
    inputs: List[Dict] | None = None


class TaskDefinitionResponse(BaseModel):
    """任务定义详情响应的数据模型。"""
    full_task_id: str
    task_name_in_plan: str
    meta: TaskMeta


class AdHocTaskRequest(BaseModel):
    """临时任务执行请求的数据模型。"""
    plan_name: str
    task_name: str
    inputs: Dict[str, Any] = Field(default_factory=dict)


class AdHocTaskResponse(BaseModel):
    """临时任务执行响应的数据模型。"""
    status: str
    message: str


class ActiveRunResponse(BaseModel):
    """活跃运行任务信息的数据模型。"""
    task_id: str


class QueuePlanCount(BaseModel):
    """按方案统计的队列数量。"""
    plan: str
    count: int


class QueuePriorityCount(BaseModel):
    """按优先级统计的队列数量。"""
    priority: int
    count: int


class QueueOverviewResponse(BaseModel):
    """任务队列概览信息的数据模型。"""
    ready_length: int
    delayed_length: int
    by_plan: List[QueuePlanCount]
    by_priority: List[QueuePriorityCount]
    avg_wait_sec: float
    p95_wait_sec: float
    oldest_age_sec: float
    throughput: Dict[str, int]  # e.g. {"m5":0,"m15":0,"m60":0}


class QueueItem(BaseModel):
    """队列中单个任务条目的数据模型。"""
    run_id: str | None = None
    plan_name: str | None = None
    task_name: str | None = None
    priority: int | None = None
    enqueued_at: float | None = None
    delay_until: float | None = None
    __key: str | None = None


class QueueListResponse(BaseModel):
    """任务队列列表的响应数据模型。"""
    items: List[QueueItem]
    next_cursor: str | None = None


class TimelineNode(BaseModel):
    """运行时间线中单个节点的数据模型。"""
    node_id: str
    startMs: int | None = None
    endMs: int | None = None
    status: str | None = None


class RunTimelineResponse(BaseModel):
    """任务运行时间线的响应数据模型。"""
    run_id: str
    plan_name: str | None = None
    task_name: str | None = None
    started_at: int | None = None
    finished_at: int | None = None
    status: str | None = None
    nodes: List[TimelineNode] = Field(default_factory=list)


# --- 6. WebSocket Endpoint ---
@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    """处理 WebSocket 连接的主端点。

    此端点负责接受新的客户端连接，并无限期地保持连接开放以进行实时通信。
    它处理连接的建立和断开。

    Args:
        websocket (WebSocket): 客户端的 WebSocket 连接对象。
    """
    await manager.connect(websocket)
    logger.info("New GUI client connected via WebSocket.")
    try:
        while True:
            # 保持连接开放。未来可以接收来自客户端的消息，例如 "ping"。
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("GUI client disconnected.")


# --- 7. REST API Endpoints ---

# --- 系统控制 ---
@app.post("/api/system/start", tags=["System"])
def system_start():
    """启动 Aura 框架的后台调度器。

    这是一个同步操作，会立即返回，并在后台启动调度器。
    """
    scheduler.start_scheduler()
    return {"status": "starting", "message": "Scheduler startup initiated."}


@app.post("/api/system/stop", tags=["System"])
def system_stop():
    """优雅地停止 Aura 框架。

    此操作会等待所有正在运行的任务完成后再停止调度器。
    """
    scheduler.stop_scheduler()
    return {"status": "stopping", "message": "Scheduler shutdown initiated."}


@app.get("/api/system/status", response_model=SystemStatusResponse, tags=["System"])
def system_status():
    """获取框架的宏观运行状态。

    Returns:
        SystemStatusResponse: 包含 `is_running` 标志的响应对象。
    """
    return scheduler.get_master_status()


# --- 资源发现 ---
@app.get("/api/plans", response_model=List[PlanResponse], tags=["Discovery"])
def list_plans():
    """获取所有已加载的 Plan 列表及其包含的任务数量。

    Returns:
        List[PlanResponse]: 一个包含所有方案及其任务计数的列表。
    """
    plan_names = scheduler.get_all_plans()
    all_tasks = scheduler.get_all_task_definitions_with_meta()

    plan_counts = {name: 0 for name in plan_names}
    for task in all_tasks:
        if task['plan_name'] in plan_counts:
            plan_counts[task['plan_name']] += 1

    return [{"name": name, "task_count": count} for name, count in plan_counts.items()]


@app.get("/api/plans/{plan_name}/tasks", response_model=List[TaskDefinitionResponse], tags=["Discovery"])
def list_tasks_in_plan(plan_name: str):
    """获取指定 Plan 下所有 Task 的详细定义信息。

    Args:
        plan_name (str): 要查询的方案名称。

    Raises:
        HTTPException: 如果找不到指定的方案，则返回 404 错误。

    Returns:
        List[TaskDefinitionResponse]: 指定方案下的所有任务定义列表。
    """
    all_tasks = scheduler.get_all_task_definitions_with_meta()
    plan_tasks = [task for task in all_tasks if task['plan_name'] == plan_name]

    if not plan_tasks and plan_name not in scheduler.get_all_plans():
        raise HTTPException(status_code=404, detail=f"Plan '{plan_name}' not found.")

    return plan_tasks


# --- 任务执行 ---
@app.post("/api/tasks/run", response_model=AdHocTaskResponse, status_code=202, tags=["Execution"])
def run_ad_hoc_task(request: AdHocTaskRequest):
    """以临时（Ad-hoc）方式执行任何一个指定的 Task。

    这是 GUI 上“立即运行”功能的核心实现。任务将被立即加入执行队列。

    Args:
        request (AdHocTaskRequest): 包含 `plan_name`, `task_name` 和 `inputs` 的请求体。

    Raises:
        HTTPException: 如果任务入队失败，则返回 400 错误。

    Returns:
        AdHocTaskResponse: 包含任务入队状态和消息的响应。
    """
    result = scheduler.run_ad_hoc_task(
        plan_name=request.plan_name,
        task_name=request.task_name,
        params=request.inputs
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


# --- 状态查询 ---
@app.get("/api/runs/active", response_model=List[ActiveRunResponse], tags=["Observability"])
async def get_active_runs():
    """获取当前所有正在执行的任务的快照。

    这是一个异步端点，它会安全地从调度器的运行上下文中读取数据。

    Returns:
        List[ActiveRunResponse]: 一个包含所有活动任务 ID 的列表。
    """
    # 安全地从异步上下文中读取共享数据
    async with scheduler.get_async_lock():
        # scheduler.running_tasks 的键是任务的唯一ID
        active_task_ids = list(scheduler.running_tasks.keys())
    return [{"task_id": task_id} for task_id in active_task_ids]


# --- Queue Overview ---
@app.get("/api/queue/overview", response_model=QueueOverviewResponse, tags=["Observability"])
def api_queue_overview():
    """获取任务队列的综合概览统计信息。

    如果查询失败，会返回一个包含默认值的空响应体，以便前端能够优雅地处理。

    Returns:
        QueueOverviewResponse: 包含队列长度、等待时间、吞吐量等统计数据的响应。
    """
    try:
        data = scheduler.get_queue_overview()
        return data
    except Exception as e:
        logging.exception("queue overview failed")
        # 返回空也行，前端会优雅处理
        return QueueOverviewResponse(
            ready_length=0, delayed_length=0,
            by_plan=[], by_priority=[],
            avg_wait_sec=0.0, p95_wait_sec=0.0, oldest_age_sec=0.0,
            throughput={'m5': 0, 'm15': 0, 'm60': 0}
        )


# --- Queue List ---
@app.get("/api/queue/list", response_model=QueueListResponse, tags=["Observability"])
def api_queue_list(state: str, limit: int = 200):
    """列出处于特定状态（就绪或延迟）的任务队列中的条目。

    Args:
        state (str): 要查询的队列状态，必须是 'ready' 或 'delayed'。
        limit (int): 返回的最大条目数。

    Raises:
        HTTPException: 如果 `state` 参数无效，则返回 400 错误。

    Returns:
        QueueListResponse: 包含任务条目列表和分页游标的响应。
    """
    state = (state or 'ready').lower()
    if state not in ('ready', 'delayed'):
        raise HTTPException(status_code=400, detail="state must be 'ready' or 'delayed'")
    try:
        data = scheduler.list_queue(state=state, limit=limit)
        return data
    except Exception as e:
        logging.exception("queue list failed")
        return QueueListResponse(items=[], next_cursor=None)


# --- Run Timeline ---
@app.get("/api/run/{run_id}/timeline", response_model=RunTimelineResponse, tags=["Observability"])
def api_run_timeline(run_id: str):
    """获取指定任务运行（run_id）的详细时间线数据。

    Args:
        run_id (str): 要查询的任务运行的唯一 ID。

    Raises:
        HTTPException: 如果找不到指定的 `run_id`，则返回 404 错误。

    Returns:
        RunTimelineResponse: 包含该次运行所有执行节点状态和耗时的时间线数据。
    """
    data = scheduler.get_run_timeline(run_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"run_id '{run_id}' not found.")
    # Pydantic 会自动校验/转换
    return data


@app.post("/api/system/reload", tags=["System"])
async def system_reload():
    """执行一次完整的全量重载。

    此操作会清空所有当前的插件注册表和定义，然后重新从磁盘加载所有插件。
    这是一个破坏性操作，仅当没有任务正在执行时才能成功。

    Raises:
        HTTPException: 如果重载因有任务正在运行而失败，则返回 409 Conflict 错误。

    Returns:
        dict: 包含重载操作结果状态和消息的字典。
    """
    result = await scheduler.reload_all()
    if result.get("status") == "error":
        raise HTTPException(status_code=409, detail=result.get("message")) # 409 Conflict
    return result

@app.post("/api/system/hot_reload/enable", tags=["System"])
def enable_hot_reload():
    """启用基于文件系统监控的自动热重载功能。

    启用后，对插件文件的任何更改都将自动触发重载。

    Raises:
        HTTPException: 如果启用失败，则返回 400 错误。

    Returns:
        dict: 包含操作结果的字典。
    """
    result = scheduler.enable_hot_reload()
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result

@app.post("/api/system/hot_reload/disable", tags=["System"])
def disable_hot_reload():
    """禁用自动热重载功能。

    Returns:
        dict: 包含操作结果的字典。
    """
    result = scheduler.disable_hot_reload()
    return result
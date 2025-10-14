# api_server.py

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
# 一个标准的辅助类，用于跟踪所有连接到服务器的GUI客户端。
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        # 并发地将消息发送给所有连接的客户端
        tasks = [connection.send_json(message) for connection in self.active_connections]
        await asyncio.gather(*tasks, return_exceptions=True)


manager = ConnectionManager()


# --- 4. 后台任务：连接Aura核心与WebSocket的桥梁 ---
async def event_bus_listener(event: Event):
    """
    这是一个回调函数，它将被订阅到Aura的EventBus。
    每当框架内部发布一个事件，此函数就会被调用，并将事件广播到所有WebSocket客户端。
    """

    await manager.broadcast({"type": "event", "payload": event.to_dict()})


async def log_queue_listener():
    """
    这是一个长时运行的任务，它会持续地从Aura的日志队列中消费日志记录。
    它使用 run_in_executor 来安全地桥接线程安全的 queue 和 asyncio 事件循环。
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
    """
    FastAPI应用启动时执行的钩子函数。
    我们在这里启动后台监听任务，将Aura核心与WebSocket世界连接起来。
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
        persistent = True,
    )
    logger.info("Aura API server started. WebSocket listeners are active.")

# --- 5. Pydantic API 模型 ---
# 使用Pydantic模型能让FastAPI自动进行数据验证和生成API文档，非常强大。
class SystemStatusResponse(BaseModel):
    is_running: bool


class PlanResponse(BaseModel):
    name: str
    task_count: int


class TaskMeta(BaseModel):
    title: str | None = None
    description: str | None = None
    inputs: List[Dict] | None = None


class TaskDefinitionResponse(BaseModel):
    full_task_id: str
    task_name_in_plan: str
    meta: TaskMeta


class AdHocTaskRequest(BaseModel):
    plan_name: str
    task_name: str
    inputs: Dict[str, Any] = Field(default_factory=dict)


class AdHocTaskResponse(BaseModel):
    status: str
    message: str


class ActiveRunResponse(BaseModel):
    task_id: str

class QueuePlanCount(BaseModel):
    plan: str
    count: int

class QueuePriorityCount(BaseModel):
    priority: int
    count: int

class QueueOverviewResponse(BaseModel):
    ready_length: int
    delayed_length: int
    by_plan: List[QueuePlanCount]
    by_priority: List[QueuePriorityCount]
    avg_wait_sec: float
    p95_wait_sec: float
    oldest_age_sec: float
    throughput: Dict[str, int]  # e.g. {"m5":0,"m15":0,"m60":0}

class QueueItem(BaseModel):
    run_id: str | None = None
    plan_name: str | None = None
    task_name: str | None = None
    priority: int | None = None
    enqueued_at: float | None = None
    delay_until: float | None = None
    __key: str | None = None

class QueueListResponse(BaseModel):
    items: List[QueueItem]
    next_cursor: str | None = None

class TimelineNode(BaseModel):
    node_id: str
    startMs: int | None = None
    endMs: int | None = None
    status: str | None = None

class RunTimelineResponse(BaseModel):
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
    """启动Aura框架的后台调度器。"""
    scheduler.start_scheduler()
    return {"status": "starting", "message": "Scheduler startup initiated."}


@app.post("/api/system/stop", tags=["System"])
def system_stop():
    """优雅地停止Aura框架。"""
    scheduler.stop_scheduler()
    return {"status": "stopping", "message": "Scheduler shutdown initiated."}


@app.get("/api/system/status", response_model=SystemStatusResponse, tags=["System"])
def system_status():
    """获取框架的宏观运行状态。"""
    return scheduler.get_master_status()


# --- 资源发现 ---
@app.get("/api/plans", response_model=List[PlanResponse], tags=["Discovery"])
def list_plans():
    """获取所有已加载的Plan列表及其任务数量。"""
    plan_names = scheduler.get_all_plans()
    all_tasks = scheduler.get_all_task_definitions_with_meta()

    plan_counts = {name: 0 for name in plan_names}
    for task in all_tasks:
        if task['plan_name'] in plan_counts:
            plan_counts[task['plan_name']] += 1

    return [{"name": name, "task_count": count} for name, count in plan_counts.items()]


@app.get("/api/plans/{plan_name}/tasks", response_model=List[TaskDefinitionResponse], tags=["Discovery"])
def list_tasks_in_plan(plan_name: str):
    """获取指定Plan下所有Task的详细信息。"""
    all_tasks = scheduler.get_all_task_definitions_with_meta()
    plan_tasks = [task for task in all_tasks if task['plan_name'] == plan_name]

    if not plan_tasks and plan_name not in scheduler.get_all_plans():
        raise HTTPException(status_code=404, detail=f"Plan '{plan_name}' not found.")

    return plan_tasks


# --- 任务执行 ---
@app.post("/api/tasks/run", response_model=AdHocTaskResponse, status_code=202, tags=["Execution"])
def run_ad_hoc_task(request: AdHocTaskRequest):
    """
    以Ad-hoc（临时）方式执行任何一个Task。
    这是GUI上“立即运行”按钮的核心。
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
    """获取当前所有正在执行的任务的快照。"""
    # 安全地从异步上下文中读取共享数据
    async with scheduler.get_async_lock():
        # scheduler.running_tasks 的键是任务的唯一ID
        active_task_ids = list(scheduler.running_tasks.keys())
    return [{"task_id": task_id} for task_id in active_task_ids]

# --- Queue Overview ---
@app.get("/api/queue/overview", response_model=QueueOverviewResponse, tags=["Observability"])
def api_queue_overview():
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
            throughput={'m5':0,'m15':0,'m60':0}
        )

# --- Queue List ---
@app.get("/api/queue/list", response_model=QueueListResponse, tags=["Observability"])
def api_queue_list(state: str, limit: int = 200):
    """
    state: 'ready' | 'delayed'
    """
    state = (state or 'ready').lower()
    if state not in ('ready','delayed'):
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
    data = scheduler.get_run_timeline(run_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"run_id '{run_id}' not found.")
    # Pydantic 会自动校验/转换
    return data

# -*- coding: utf-8 -*-
"""Aura 框架的 FastAPI 服务器（REST API 版本）。

该模块提供了用于控制和监控 Aura 自动化框架的 RESTful API 服务器。
所有状态同步和任务控制都通过 REST API 实现，只保留日志流的 WebSocket。

主要功能:
- **系统控制**: 启动、停止、重载和获取 Aura 调度器的状态。
- **资源发现**: 列出所有已加载的方案（Plans）和任务（Tasks）。
- **任务执行**: 支持单个和批量任务派发。
- **任务管理**: 取消任务、调整优先级。
- **状态监控**: 提供对活动任务、任务队列和历史运行时间线的洞察。
- **实时日志**: 使用 WebSocket 将日志实时推送到前端。
- **热重载**: 支持动态启用或禁用插件的自动热重载功能。
"""

import asyncio
import logging
from typing import List, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from packages.aura_core.scheduler import Scheduler
from packages.aura_core.event_bus import Event

# --- 1. 全局核心实例 ---
logger = logging.getLogger("AuraFramework")
logger.setLevel(logging.DEBUG)

app = FastAPI(
    title="Aura Framework API (REST Edition)",
    description="A RESTful API server to control and observe the Aura automation framework.",
    version="2.0.0"
)
scheduler = Scheduler()

# --- 2. CORS中间件 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 3. WebSocket 连接管理器（仅用于日志流） ---
class LogConnectionManager:
    """管理所有日志 WebSocket 连接。"""

    def __init__(self):
        self.log_connections: List[WebSocket] = []
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self.lock:
            self.log_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self.lock:
            if websocket in self.log_connections:
                self.log_connections.remove(websocket)

    async def broadcast_logs(self, message: dict):
        if not self.log_connections:
            return
        connections = self.log_connections[:]
        tasks = [conn.send_json(message) for conn in connections]
        await asyncio.gather(*tasks, return_exceptions=True)


log_manager = LogConnectionManager()


# --- 4. 后台任务：日志流监听器 ---
async def log_queue_listener():
    """持续从 Aura 日志队列中消费日志记录并广播到日志通道。"""
    logger.info("Log queue listener started. Awaiting logs for the LOGS channel...")
    loop = asyncio.get_running_loop()
    while True:
        try:
            log_entry = await loop.run_in_executor(None, scheduler.api_log_queue.get)
            await log_manager.broadcast_logs({"type": "log", "payload": log_entry})
            loop.run_in_executor(None, scheduler.api_log_queue.task_done)
        except Exception as e:
            print(f"CRITICAL: Log listener background task failed: {e}")
            await asyncio.sleep(1)


@app.on_event("startup")
async def startup_event():
    """FastAPI 应用启动时执行的钩子函数。"""
    asyncio.create_task(log_queue_listener())
    logger.info("Aura API server (REST Edition) started. Log streaming is active.")


# --- 5. Pydantic API 模型 ---
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


class BatchTaskRequest(BaseModel):
    """批量任务派发请求。"""
    tasks: List[AdHocTaskRequest]


class TaskDispatchResult(BaseModel):
    """单个任务派发结果。"""
    plan_name: str
    task_name: str
    status: str
    message: str
    cid: str | None = None


class BatchTaskResponse(BaseModel):
    """批量任务派发响应。"""
    results: List[TaskDispatchResult]
    success_count: int
    failed_count: int


class CancelTaskResponse(BaseModel):
    """任务取消响应。"""
    status: str
    message: str


class UpdatePriorityRequest(BaseModel):
    """任务优先级更新请求。"""
    priority: int


class UpdatePriorityResponse(BaseModel):
    """任务优先级更新响应。"""
    status: str
    message: str


class BatchStatusRequest(BaseModel):
    """批量状态查询请求。"""
    cids: List[str]


class TaskStatusItem(BaseModel):
    """单个任务状态。"""
    cid: str
    status: str | None = None
    plan_name: str | None = None
    task_name: str | None = None
    started_at: int | None = None
    finished_at: int | None = None
    nodes: List[Dict] | None = None


class BatchStatusResponse(BaseModel):
    """批量状态查询响应。"""
    tasks: List[TaskStatusItem]


class ActiveRunResponse(BaseModel):
    """活跃运行任务信息（增强版）。"""
    run_id: str
    cid: str | None = None
    plan_name: str | None = None
    task_name: str | None = None
    started_at: int | None = None
    status: str | None = None


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
    throughput: Dict[str, int]


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

class QueueInsertRequest(BaseModel):
    index: int
    plan_name: str
    task_name: str
    inputs: Dict[str, Any] = Field(default_factory=dict)


class QueueMoveRequest(BaseModel):
    position: int


class QueueReorderRequest(BaseModel):
    cid_order: List[str]



# --- 6. WebSocket Endpoint (仅日志流) ---
@app.websocket("/ws/logs")
async def websocket_endpoint_logs(websocket: WebSocket):
    """处理日志流的 WebSocket 连接。"""
    await log_manager.connect(websocket)
    client_info = f"{websocket.client.host}:{websocket.client.port}"
    logger.info(f"Client {client_info} connected to LOGS channel.")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info(f"Client {client_info} disconnected from LOGS channel.")
    finally:
        await log_manager.disconnect(websocket)


# --- 7. REST API Endpoints ---

# === 系统控制 ===
@app.post("/api/system/start", tags=["System"])
def system_start():
    """启动 Aura 框架的后台调度器。"""
    scheduler.start_scheduler()
    return {"status": "starting", "message": "Scheduler startup initiated."}


@app.post("/api/system/stop", tags=["System"])
def system_stop():
    """优雅地停止 Aura 框架。"""
    scheduler.stop_scheduler()
    return {"status": "stopping", "message": "Scheduler shutdown initiated."}


@app.get("/api/system/status", response_model=SystemStatusResponse, tags=["System"])
def system_status():
    """获取框架的宏观运行状态。"""
    return scheduler.get_master_status()


# === 资源发现 ===
@app.get("/api/plans", response_model=List[PlanResponse], tags=["Discovery"])
def list_plans():
    """获取所有已加载的 Plan 列表及其包含的任务数量。"""
    plan_names = scheduler.get_all_plans()
    all_tasks = scheduler.get_all_task_definitions_with_meta()

    plan_counts = {name: 0 for name in plan_names}
    for task in all_tasks:
        if task['plan_name'] in plan_counts:
            plan_counts[task['plan_name']] += 1

    return [{"name": name, "task_count": count} for name, count in plan_counts.items()]


@app.get("/api/plans/{plan_name}/tasks", response_model=List[TaskDefinitionResponse], tags=["Discovery"])
def list_tasks_in_plan(plan_name: str):
    """获取指定 Plan 下所有 Task 的详细定义信息。"""
    all_tasks = scheduler.get_all_task_definitions_with_meta()
    plan_tasks = [task for task in all_tasks if task['plan_name'] == plan_name]

    if not plan_tasks and plan_name not in scheduler.get_all_plans():
        raise HTTPException(status_code=404, detail=f"Plan '{plan_name}' not found.")

    return plan_tasks


# === 任务执行 ===
@app.post("/api/tasks/run", status_code=202, tags=["Execution"])
def run_ad_hoc_task(request: AdHocTaskRequest):
    """执行单个临时任务。"""
    result = scheduler.run_ad_hoc_task(
        plan_name=request.plan_name,
        task_name=request.task_name,
        params=request.inputs
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@app.post("/api/tasks/batch", response_model=BatchTaskResponse, status_code=202, tags=["Execution"])
def run_batch_tasks(request: BatchTaskRequest):
    """批量执行多个临时任务。"""
    tasks_input = [
        {
            "plan_name": task.plan_name,
            "task_name": task.task_name,
            "inputs": task.inputs
        }
        for task in request.tasks
    ]

    result = scheduler.run_batch_ad_hoc_tasks(tasks_input)
    return result


# === 任务管理 ===
@app.post("/api/tasks/{cid}/cancel", response_model=CancelTaskResponse, tags=["Task Management"])
def cancel_task(cid: str):
    """取消指定 cid 的任务。"""
    result = scheduler.cancel_task(cid)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@app.patch("/api/tasks/{cid}/priority", response_model=UpdatePriorityResponse, tags=["Task Management"])
def update_task_priority(cid: str, request: UpdatePriorityRequest):
    """调整指定任务的优先级。"""
    result = scheduler.update_task_priority(cid, request.priority)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


# === 状态查询 ===
@app.get("/api/runs/active", response_model=List[ActiveRunResponse], tags=["Observability"])
def get_active_runs():
    """获取当前所有正在执行的任务的快照（增强版）。"""
    active_runs = scheduler.get_active_runs_snapshot()
    return active_runs


@app.post("/api/tasks/status/batch", response_model=BatchStatusResponse, tags=["Observability"])
def get_batch_task_status(request: BatchStatusRequest):
    """批量获取多个任务的状态。"""
    result = scheduler.get_batch_task_status(request.cids)
    return {"tasks": result}


@app.get("/api/queue/overview", response_model=QueueOverviewResponse, tags=["Observability"])
def api_queue_overview():
    """获取任务队列的综合概览统计信息。"""
    try:
        data = scheduler.get_queue_overview()
        return data
    except Exception as e:
        logging.exception("queue overview failed")
        return QueueOverviewResponse(
            ready_length=0, delayed_length=0,
            by_plan=[], by_priority=[],
            avg_wait_sec=0.0, p95_wait_sec=0.0, oldest_age_sec=0.0,
            throughput={'m5': 0, 'm15': 0, 'm60': 0}
        )


@app.get("/api/queue/list", response_model=QueueListResponse, tags=["Observability"])
def api_queue_list(state: str, limit: int = 200):
    """列出处于特定状态（就绪或延迟）的任务队列中的条目。"""
    state = (state or 'ready').lower()
    if state not in ('ready', 'delayed'):
        raise HTTPException(status_code=400, detail="state must be 'ready' or 'delayed'")
    try:
        data = scheduler.list_queue(state=state, limit=limit)
        return data
    except Exception as e:
        logging.exception("queue list failed")
        return QueueListResponse(items=[], next_cursor=None)


@app.get("/api/run/{run_id}/timeline", response_model=RunTimelineResponse, tags=["Observability"])
def api_run_timeline(run_id: str):
    """获取指定任务运行（run_id）的详细时间线数据。"""
    data = scheduler.get_run_timeline(run_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"run_id '{run_id}' not found.")
    return data


# === 系统管理 ===
@app.post("/api/system/reload", tags=["System"])
async def system_reload():
    """执行一次完整的全量重载。"""
    result = await scheduler.reload_all()
    if result.get("status") == "error":
        raise HTTPException(status_code=409, detail=result.get("message"))
    return result


@app.post("/api/system/hot_reload/enable", tags=["System"])
def enable_hot_reload():
    """启用基于文件系统监控的自动热重载功能。"""
    result = scheduler.enable_hot_reload()
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@app.post("/api/system/hot_reload/disable", tags=["System"])
def disable_hot_reload():
    """禁用自动热重载功能。"""
    result = scheduler.disable_hot_reload()
    return result

@app.post("/api/queue/insert", tags=["Queue Management"])
async def queue_insert(request: QueueInsertRequest):
    """在队列的指定位置插入任务。"""
    result = await scheduler.queue_insert_at(
        index=request.index,
        plan_name=request.plan_name,
        task_name=request.task_name,
        params=request.inputs
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@app.delete("/api/queue/{cid}", tags=["Queue Management"])
async def queue_remove(cid: str):
    """从队列中删除指定任务。"""
    result = await scheduler.queue_remove_task(cid)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@app.post("/api/queue/{cid}/move-to-front", tags=["Queue Management"])
async def queue_move_front(cid: str):
    """将任务移动到队列头部。"""
    result = await scheduler.queue_move_to_front(cid)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@app.post("/api/queue/{cid}/move-to-position", tags=["Queue Management"])
async def queue_move_position(cid: str, request: QueueMoveRequest):
    """将任务移动到指定位置。"""
    result = await scheduler.queue_move_to_position(cid, request.position)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@app.get("/api/queue/all", tags=["Queue Management"])
async def queue_list_all():
    """获取队列中所有任务。"""
    return await scheduler.queue_list_all()


@app.delete("/api/queue/clear", tags=["Queue Management"])
async def queue_clear():
    """清空队列。"""
    return await scheduler.queue_clear()


@app.post("/api/queue/reorder", tags=["Queue Management"])
async def queue_reorder(request: QueueReorderRequest):
    """重新排序队列。"""
    result = await scheduler.queue_reorder(request.cid_order)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


# --- 8. 主程序入口 ---
if __name__ == "__main__":
    import uvicorn
    from pathlib import Path

    print("=" * 80)
    print(" " * 20 + "AURA FRAMEWORK API SERVER (REST Edition)")
    print("=" * 80)
    print(f"  Server will start on: http://0.0.0.0:18098")
    print(f"  API Documentation:    http://localhost:18098/docs")
    print(f"  WebSocket Log Stream: ws://localhost:18098/ws/logs")
    print("=" * 80)
    print()

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=18098,
        log_level="info"
    )

import asyncio
import json
from typing import List

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)


manager = ConnectionManager()


async def broadcast_updates():
    while True:
        await asyncio.sleep(1)
        log_entry = {
            "type": "log_entry",
            "data": {
                "level": "INFO",
                "message": "Broadcasting a log entry.",
                "timestamp": "2024-01-01T12:00:00Z",
            },
        }
        await manager.broadcast(json.dumps(log_entry))
        task_status_update = {
            "type": "task_status_update",
            "data": {"task_id": "some_task_id", "status": "RUNNING"},
        }
        await manager.broadcast(json.dumps(task_status_update))
        scheduler_status_update = {
            "type": "scheduler_status_update",
            "data": {"is_running": True, "is_paused": False},
        }
        await manager.broadcast(json.dumps(scheduler_status_update))
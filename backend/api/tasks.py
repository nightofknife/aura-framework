from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, Any
from ..mock_scheduler import mock_scheduler

router = APIRouter()

class RunTaskRequest(BaseModel):
    plan_name: str
    task_name: str
    params: Dict[str, Any]

@router.post("/run")
def run_task(request: RunTaskRequest):
    task = mock_scheduler.run_task(request.plan_name, request.task_name, request.params)
    return {"message": "Task started.", "task": task}

@router.get("/history")
def get_task_history(n: int = 20):
    return mock_scheduler.get_task_history(n)
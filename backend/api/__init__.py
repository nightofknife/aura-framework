from fastapi import APIRouter

api_router = APIRouter()

from . import scheduler, tasks, workspace

api_router.include_router(scheduler.router, prefix="/scheduler", tags=["scheduler"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(workspace.router, prefix="/workspace", tags=["workspace"])
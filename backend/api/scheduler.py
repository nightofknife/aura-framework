from fastapi import APIRouter
from ..mock_scheduler import mock_scheduler

router = APIRouter()

@router.get("/status")
def get_status():
    return mock_scheduler.get_status()

@router.post("/start")
def start_scheduler():
    mock_scheduler.start()
    return {"message": "Scheduler started."}

@router.post("/stop")
def stop_scheduler():
    mock_scheduler.stop()
    return {"message": "Scheduler stopped."}

@router.post("/pause")
def pause_scheduler():
    mock_scheduler.pause()
    return {"message": "Scheduler paused."}

@router.post("/resume")
def resume_scheduler():
    mock_scheduler.resume()
    return {"message": "Scheduler resumed."}

@router.post("/reload")
def reload_scheduler():
    mock_scheduler.reload()
    return {"message": "Plans and tasks reloaded."}
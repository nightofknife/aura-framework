from fastapi import APIRouter

router = APIRouter()

@router.get("/plans")
def get_plans():
    # Mock data for plans
    return [
        {
            "name": "MyTestPlan",
            "tasks": [
                {"name": "task_1", "meta": {"description": "This is the first task."}},
                {"name": "task_2", "meta": {"description": "This is the second task."}},
            ],
        }
    ]

@router.get("/actions")
def get_actions():
    # Mock data for actions
    return [
        {"name": "action_1", "definition": "Does something."},
        {"name": "action_2", "definition": "Does something else."},
    ]

@router.get("/services")
def get_services():
    # Mock data for services
    return [
        {"name": "service_1", "status": "RUNNING"},
        {"name": "service_2", "status": "STOPPED"},
    ]

@router.get("/interrupts")
def get_interrupts():
    # Mock data for interrupts
    return [
        {"name": "interrupt_1", "status": "ENABLED"},
        {"name": "interrupt_2", "status": "DISABLED"},
    ]
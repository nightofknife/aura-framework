import asyncio
from datetime import datetime

class MockScheduler:
    def __init__(self):
        self.is_running = False
        self.is_paused = False
        self.logs = []
        self.task_history = []

    def start(self):
        self.is_running = True
        self.is_paused = False
        self.logs.append(self._create_log_entry("INFO", "Scheduler started."))

    def stop(self):
        self.is_running = False
        self.is_paused = False
        self.logs.append(self._create_log_entry("INFO", "Scheduler stopped."))

    def pause(self):
        if self.is_running:
            self.is_paused = True
            self.logs.append(self._create_log_entry("INFO", "Scheduler paused."))

    def resume(self):
        if self.is_running:
            self.is_paused = False
            self.logs.append(self._create_log_entry("INFO", "Scheduler resumed."))

    def reload(self):
        self.logs.append(self._create_log_entry("INFO", "Plans and tasks reloaded."))

    def get_status(self):
        return {"is_running": self.is_running, "is_paused": self.is_paused}

    def run_task(self, plan_name, task_name, params):
        task_id = f"{plan_name}_{task_name}_{len(self.task_history) + 1}"
        task = {
            "task_id": task_id,
            "plan_name": plan_name,
            "task_name": task_name,
            "params": params,
            "status": "QUEUED",
            "start_time": None,
            "end_time": None,
            "result": None,
        }
        self.task_history.append(task)
        self.logs.append(self._create_log_entry("INFO", f"Task {task_id} queued."))
        asyncio.create_task(self._execute_task(task))
        return task

    async def _execute_task(self, task):
        task["status"] = "RUNNING"
        task["start_time"] = datetime.now().isoformat()
        self.logs.append(self._create_log_entry("INFO", f"Task {task['task_id']} started."))

        await asyncio.sleep(5)  # Simulate task execution

        task["status"] = "SUCCESS"
        task["end_time"] = datetime.now().isoformat()
        task["result"] = {"output": "Task completed successfully"}
        self.logs.append(self._create_log_entry("INFO", f"Task {task['task_id']} finished."))

    def get_task_history(self, n=20):
        return self.task_history[-n:]

    def _create_log_entry(self, level, message):
        return {
            "level": level,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        }

mock_scheduler = MockScheduler()
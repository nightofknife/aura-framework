class TaskControlException(Exception):
    """用于控制任务流程的基类异常。"""
    pass


class StopTaskException(TaskControlException):
    """当需要停止任务时抛出。"""

    def __init__(self, message: str, success: bool = True):
        self.message = message
        self.success = success
        super().__init__(self.message)

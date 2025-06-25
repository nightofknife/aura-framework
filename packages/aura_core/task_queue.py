# aura_core/task_queue.py

import queue
import threading
from dataclasses import dataclass
from typing import Dict, Any, Optional

from packages.aura_core.event_bus import Event

@dataclass
class Tasklet:
    """
    一个轻量级的待办任务单元，将被放入任务队列。
    """
    task_name: str
    triggering_event: Optional[Event] = None # 触发此任务的事件

class TaskQueue:
    """一个简单的、线程安全的任务队列。"""
    def __init__(self):
        self._queue = queue.Queue()

    def put(self, tasklet: Tasklet):
        """将一个任务单元放入队列。"""
        self._queue.put(tasklet)

    def get(self, block: bool = True, timeout: Optional[float] = None) -> Tasklet:
        """
        从队列中获取一个任务单元。
        :raises: queue.Empty 如果队列为空且非阻塞。
        """
        return self._queue.get(block, timeout)

    def task_done(self):
        """通知队列一个任务已完成。"""
        self._queue.task_done()

    def join(self):
        """阻塞直到队列中的所有任务都被处理完毕。"""
        self._queue.join()

    def empty(self) -> bool:
        """检查队列是否为空。"""
        return self._queue.empty()


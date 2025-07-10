# packages/aura_core/task_queue.py (已修复)

import queue
from dataclasses import dataclass, field
from typing import Any, Optional

from packages.aura_core.event_bus import Event

@dataclass(order=True)
class PriorityTasklet:
    """
    一个带优先级的任务单元。
    优先级数字越小，优先级越高。
    """
    priority: int
    # 使用 field(compare=False) 使这些字段不参与优先级比较
    tasklet: 'Tasklet' = field(compare=False)

@dataclass
class Tasklet:
    """
    一个轻量级的待办任务单元，将被放入任务队列。
    【修改】增加了更多字段以支持不同类型的任务。
    """
    task_name: str
    payload: Optional[dict] = None
    is_ad_hoc: bool = False
    triggering_event: Optional[Event] = None

class TaskQueue:
    """
    【修改】一个支持优先级的、线程安全的任务队列。
    """
    def __init__(self):
        # 使用 PriorityQueue 来处理高优先级任务
        self._queue = queue.PriorityQueue()

    def put(self, tasklet: Tasklet, high_priority: bool = False):
        """
        将一个任务单元放入队列。
        :param tasklet: 要放入的任务单元。
        :param high_priority: 如果为 True，任务将被优先处理。
        """
        # 优先级: 0 for high, 1 for normal
        priority = 0 if high_priority else 1
        self._queue.put(PriorityTasklet(priority, tasklet))

    def get(self, block: bool = True, timeout: Optional[float] = None) -> Tasklet:
        """
        从队列中获取一个任务单元。
        :raises: queue.Empty 如果队列为空且非阻塞。
        """
        priority_tasklet = self._queue.get(block, timeout)
        return priority_tasklet.tasklet

    def task_done(self):
        """通知队列一个任务已完成。"""
        self._queue.task_done()

    def join(self):
        """阻塞直到队列中的所有任务都被处理完毕。"""
        self._queue.join()

    def empty(self) -> bool:
        """检查队列是否为空。"""
        return self._queue.empty()

    def qsize(self) -> int:
        """返回队列的大致大小。"""
        return self._queue.qsize()

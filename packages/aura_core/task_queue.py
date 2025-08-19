import asyncio
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Literal

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
    【Async Refactor】增加了执行模式和并发控制元数据。
    """
    task_name: str
    payload: Optional[Dict[str, Any]] = None
    is_ad_hoc: bool = False
    triggering_event: Optional[Event] = None

    # --- 新增字段支持异步调度 ---
    execution_mode: Literal['sync', 'async'] = 'sync'
    resource_tags: List[str] = field(default_factory=list)
    timeout: Optional[float] = 3600.0  # 默认1小时超时
    cpu_bound: bool = False


class TaskQueue:
    """
    【Async Refactor】一个支持优先级的、异步的、有界任务队列。
    """

    def __init__(self, maxsize: int = 1000):
        """
        :param maxsize: 队列的最大容量，用于实现背压。
        """
        self._queue = asyncio.PriorityQueue(maxsize=maxsize)

    async def put(self, tasklet: Tasklet, high_priority: bool = False):
        """
        将一个任务单元异步放入队列。如果队列已满，此操作将等待。
        :param tasklet: 要放入的任务单元。
        :param high_priority: 如果为 True，任务将被优先处理。
        """
        # 优先级: 0 for high, 1 for normal
        priority = 0 if high_priority else 1
        await self._queue.put(PriorityTasklet(priority, tasklet))

    def put_nowait(self, tasklet: Tasklet, high_priority: bool = False):
        """
        从同步代码中非阻塞地将任务放入队列。
        :raises: asyncio.QueueFull 如果队列已满。
        """
        priority = 0 if high_priority else 1
        self._queue.put_nowait(PriorityTasklet(priority, tasklet))

    async def get(self) -> Tasklet:
        """
        从队列中异步获取一个任务单元。如果队列为空，此操作将等待。
        """
        priority_tasklet = await self._queue.get()
        return priority_tasklet.tasklet

    def task_done(self):
        """通知队列一个任务已完成。"""
        self._queue.task_done()

    async def join(self):
        """阻塞直到队列中的所有任务都被处理完毕。"""
        await self._queue.join()

    def empty(self) -> bool:
        """检查队列是否为空。"""
        return self._queue.empty()

    def qsize(self) -> int:
        """返回队列的大致大小。"""
        return self._queue.qsize()


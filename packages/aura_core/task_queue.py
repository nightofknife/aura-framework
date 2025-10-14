# -*- coding: utf-8 -*-
"""提供了 Aura 框架内部使用的异步任务队列和任务单元定义。

此模块定义了三个核心类：
- `Tasklet`: 一个轻量级的数据类，代表一个待执行的任务单元。
- `PriorityTasklet`: `Tasklet` 的一个包装器，为其增加了优先级属性。
- `TaskQueue`: 一个基于 `asyncio.PriorityQueue` 的、支持优先级的
  异步任务队列。
"""
import asyncio
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Literal

from packages.aura_core.event_bus import Event


@dataclass(order=True)
class PriorityTasklet:
    """一个带优先级的任务单元包装器。

    此类用于在 `asyncio.PriorityQueue` 中实现任务的优先级排序。
    优先级数字越小，优先级越高。

    Attributes:
        priority (int): 任务的优先级。
        tasklet (Tasklet): 被包装的实际任务单元。`compare=False` 确保
            它不参与优先级比较。
    """
    priority: int
    tasklet: 'Tasklet' = field(compare=False)


@dataclass
class Tasklet:
    """一个轻量级的待办任务单元，将被放入任务队列。

    它封装了执行一个任务所需的所有信息。

    Attributes:
        task_name (str): 要执行的任务的完全限定ID (e.g., "my_plan/my_task")。
        payload (Optional[Dict[str, Any]]): 与任务相关的任意数据字典。
        is_ad_hoc (bool): 标记此任务是否为临时（ad-hoc）任务。
        triggering_event (Optional[Event]): 触发此任务的事件对象（如有）。
        initial_context (Optional[Dict[str, Any]]): 传递给任务的初始输入参数。
        execution_mode (Literal['sync', 'async']): 任务的执行模式。
        resource_tags (List[str]): 用于并发控制的资源标签列表。
        timeout (Optional[float]): 任务的执行超时时间（秒）。
        cpu_bound (bool): 标记此任务是否为CPU密集型。
    """
    task_name: str
    payload: Optional[Dict[str, Any]] = None
    is_ad_hoc: bool = False
    triggering_event: Optional[Event] = None
    initial_context: Optional[Dict[str, Any]] = field(default_factory=dict)
    execution_mode: Literal['sync', 'async'] = 'sync'
    resource_tags: List[str] = field(default_factory=list)
    timeout: Optional[float] = 3600.0
    cpu_bound: bool = False


class TaskQueue:
    """一个支持优先级的、异步的、有界任务队列。

    它基于 `asyncio.PriorityQueue` 实现，并提供了与标准队列类似的接口。
    """

    def __init__(self, maxsize: int = 1000):
        """初始化任务队列。

        Args:
            maxsize (int): 队列的最大容量，用于实现背压（back-pressure）。
        """
        self._queue = asyncio.PriorityQueue(maxsize=maxsize)

    async def put(self, tasklet: Tasklet, high_priority: bool = False):
        """将一个任务单元异步放入队列。

        如果队列已满，此操作将会阻塞等待，直到有空间可用。

        Args:
            tasklet: 要放入的任务单元。
            high_priority: 如果为 True，任务将被赋予高优先级。
        """
        priority = 0 if high_priority else 1
        await self._queue.put(PriorityTasklet(priority, tasklet))

    def put_nowait(self, tasklet: Tasklet, high_priority: bool = False):
        """从同步代码中非阻塞地将任务放入队列。

        Args:
            tasklet: 要放入的任务单元。
            high_priority: 如果为 True，任务将被赋予高优先级。

        Raises:
            asyncio.QueueFull: 如果队列已满。
        """
        priority = 0 if high_priority else 1
        self._queue.put_nowait(PriorityTasklet(priority, tasklet))

    async def get(self) -> Tasklet:
        """从队列中异步获取一个任务单元。

        如果队列为空，此操作将会阻塞等待，直到有任务可用。
        """
        priority_tasklet = await self._queue.get()
        return priority_tasklet.tasklet

    def task_done(self):
        """通知队列一个任务已处理完毕。

        这对于使用 `join()` 方法等待队列清空非常重要。
        """
        self._queue.task_done()

    async def join(self):
        """阻塞直到队列中的所有任务都被获取并处理完毕。"""
        await self._queue.join()

    def empty(self) -> bool:
        """检查队列是否为空。"""
        return self._queue.empty()

    def qsize(self) -> int:
        """返回队列中的大致项目数量。"""
        return self._queue.qsize()


"""
定义了 Aura 框架内部使用的任务队列和任务单元的数据结构。

该模块提供了三个核心类：
- `Tasklet`: 一个轻量级的数据类，用于封装一个待执行的任务及其所有相关元数据，
  如触发事件、执行模式、资源标签等。
- `PriorityTasklet`: `Tasklet` 的一个包装器，为其增加了一个优先级字段，
  以便在 `asyncio.PriorityQueue` 中进行排序。
- `TaskQueue`: 一个基于 `asyncio.PriorityQueue` 的、支持优先级的、有界
  的异步任务队列，用于在框架的不同组件之间传递 `Tasklet`。
"""
import asyncio
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Literal

from packages.aura_core.event_bus import Event


@dataclass(order=True)
class PriorityTasklet:
    """
    一个带优先级的任务单元包装器，用于在 `TaskQueue` 中排序。

    `asyncio.PriorityQueue` 会根据此对象的排序行为来决定任务的执行顺序。
    `priority` 值越小，优先级越高。

    Attributes:
        priority (int): 任务的优先级，数字越小优先级越高。
        tasklet (Tasklet): 被包装的实际任务单元。此字段不参与比较。
    """
    priority: int
    tasklet: 'Tasklet' = field(compare=False)


@dataclass
class Tasklet:
    """
    一个轻量级的待办任务单元，代表一个将被放入任务队列并最终被执行的任务。

    它封装了执行一个任务所需的所有信息。

    Attributes:
        task_name (str): 任务的完全限定ID，格式通常为 `plan_name/task_name`。
        payload (Optional[Dict[str, Any]]): 与任务相关的任意数据负载，
            通常来自 `schedule.yaml` 的定义。
        is_ad_hoc (bool): 标记此任务是否是临时手动触发的，而非由调度器或事件触发。
        triggering_event (Optional[Event]): 触发此任务的事件对象（如果有）。
        initial_context (Optional[Dict[str, Any]]): 传递给任务的初始上下文或输入参数。
        execution_mode (Literal['sync', 'async']): 任务的执行模式。
            【已弃用】此字段在旧版中用于选择执行器，现已保留但功能简化。
        resource_tags (List[str]): 用于并发控制的资源标签列表。
            例如 `['gpu:1']` 表示该任务需要独占一个名为 'gpu' 的资源。
        timeout (Optional[float]): 任务的执行超时时间（秒）。默认为 3600 秒（1小时）。
        cpu_bound (bool): 【已弃用】标记任务是否为CPU密集型。
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
    """
    一个支持优先级的、异步的、有界任务队列。

    它封装了 `asyncio.PriorityQueue`，提供了一个更符合 Aura 框架
    需求的接口，并处理了 `Tasklet` 和 `PriorityTasklet` 之间的转换。
    """

    def __init__(self, maxsize: int = 1000):
        """
        初始化一个任务队列。

        Args:
            maxsize (int): 队列的最大容量。当队列满时，`put` 操作将会阻塞，
                这提供了一种自然的背压（back-pressure）机制。
        """
        self._queue: asyncio.PriorityQueue[PriorityTasklet] = asyncio.PriorityQueue(maxsize=maxsize)

    async def put(self, tasklet: Tasklet, high_priority: bool = False):
        """
        将一个任务单元异步地放入队列中。

        如果队列已满，此协程将会阻塞，直到队列中有空间可用。

        Args:
            tasklet (Tasklet): 要放入队列的任务单元。
            high_priority (bool): 如果为 True，任务将被赋予高优先级（优先执行）。
                默认为 False（正常优先级）。
        """
        # 优先级: 0 for high, 1 for normal
        priority = 0 if high_priority else 1
        await self._queue.put(PriorityTasklet(priority, tasklet))

    def put_nowait(self, tasklet: Tasklet, high_priority: bool = False):
        """
        尝试立即将一个任务单元放入队列，不会阻塞。

        此方法适用于从同步代码（例如，不同的线程）向队列中添加任务。

        Args:
            tasklet (Tasklet): 要放入队列的任务单元。
            high_priority (bool): 是否设为高优先级。

        Raises:
            asyncio.QueueFull: 如果队列已满且无法立即放入。
        """
        priority = 0 if high_priority else 1
        self._queue.put_nowait(PriorityTasklet(priority, tasklet))

    async def get(self) -> Tasklet:
        """
        从队列中异步地获取一个任务单元。

        如果队列为空，此协程将会阻塞，直到有任务可用。
        它会自动处理优先级，总是返回当前队列中优先级最高的任务。

        Returns:
            Tasklet: 从队列中取出的任务单元。
        """
        priority_tasklet = await self._queue.get()
        return priority_tasklet.tasklet

    def task_done(self):
        """
        通知队列一个先前取出的任务已经处理完毕。

        对于每个通过 `get()` 获取的任务，都应该在处理完成后调用一次 `task_done()`。
        这对于 `join()` 方法正确工作至关重要。
        """
        self._queue.task_done()

    async def join(self):
        """
        阻塞，直到队列中的所有任务都被获取并处理完毕。

        当所有任务的 `task_done()`都被调用后，此协程才会返回。
        """
        await self._queue.join()

    def empty(self) -> bool:
        """
        检查队列是否为空。

        注意：由于并发的存在，返回 True 并不保证后续的 `get()` 不会阻塞。

        Returns:
            bool: 如果队列为空，则为 True；否则为 False。
        """
        return self._queue.empty()

    def qsize(self) -> int:
        """
        返回队列中项目的大致数量。

        注意：这个数字不是完全可靠的，不应在并发代码中依赖它来做逻辑判断。

        Returns:
            int: 队列中的项目数。
        """
        return self._queue.qsize()


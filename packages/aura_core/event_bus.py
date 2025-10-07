"""
定义了 Aura 框架的异步事件总线。

该模块提供了 `Event` 数据类和一个核心的 `EventBus` 类，共同实现了一个
高性能、异步、支持通配符的发布-订阅（Pub/Sub）系统。这是 Aura 框架中
各组件之间进行解耦通信的关键机制。

主要特性:
- **完全异步**: 基于 `asyncio`，所有操作都是非阻塞的。
- **并发处理**: 使用 `asyncio.gather` 并发执行所有匹配的回调，提高了响应速度。
- **线程安全**: 使用 `asyncio.Lock` 保护内部订阅者列表，可在多任务环境中安全使用。
- **通配符支持**: 订阅时可使用 `*` 和 `?` 等 `fnmatch` 通配符来匹配多种事件名称。
- **多频道**: 支持将事件发布到不同频道，实现逻辑隔离。
- **同步/异步回调兼容**: 能透明地处理同步和异步的回调函数，将同步函数安全地在线程池中执行。
- **熔断机制**: 通过 `max_depth` 防止因事件循环触发导致的无限递归调用。
"""
import asyncio
import fnmatch
import time
import uuid
import dataclasses
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from packages.aura_core.logger import logger


@dataclass
class Event:
    """
    表示在事件总线中传递的单个事件。

    这是一个数据类，封装了事件的所有相关信息，使其易于创建、传递和检查。

    Attributes:
        name (str): 事件的名称，例如 "task.succeeded"。
        channel (str): 事件发布的频道，默认为 "global"。
        payload (Dict[str, Any]): 携带的任意数据负载。
        source (Optional[str]): 事件来源的标识符，例如 "Scheduler" 或 "PluginA"。
        id (str): 事件的唯一标识符（UUID）。
        timestamp (float): 事件创建时的时间戳。
        causation_chain (List[str]): 一个ID列表，用于追踪导致此事件的事件链。
        depth (int): 事件在因果链中的深度，用于防止无限循环。
    """
    name: str
    channel: str = "global"
    payload: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    causation_chain: List[str] = field(default_factory=list)
    depth: int = 0

    def __post_init__(self):
        """在初始化后确保当前事件ID在因果链中。"""
        if self.id not in self.causation_chain:
            self.causation_chain.append(self.id)

    def __repr__(self) -> str:
        """返回事件的简洁字符串表示。"""
        return (f"Event(name='{self.name}', channel='{self.channel}', "
                f"payload={self.payload}, source='{self.source}', depth={self.depth})")


    def to_dict(self) -> Dict[str, Any]:
        """将 Event 实例转换为字典，方便序列化。"""
        return dataclasses.asdict(self)


class EventBus:
    """
    一个异步的、支持通配符的、高性能的事件总线。

    它允许系统中的不同部分在不知道彼此的情况下进行通信。发布者发布事件，
    而订阅者则监听特定模式的事件并作出反应。
    """

    def __init__(self, max_depth: int = 10):
        """
        初始化事件总线。

        Args:
            max_depth (int): 事件因果链的最大深度。如果一个事件是由另一个事件触发的，
                其深度会增加。当深度达到此限制时，事件将被阻止发布，以防止无限递归。
        """
        self._subscribers: Dict[str, Dict[str, List[Callable[[Event], Any]]]] = defaultdict(lambda: defaultdict(list))
        self._lock = asyncio.Lock()
        self.max_depth = max_depth
        logger.info(f"EventBus已初始化，最大事件深度设置为 {self.max_depth}。")

    async def subscribe(self, event_pattern: str, callback: Callable[[Event], Any], channel: str = "global") -> Tuple[str, str, Callable]:
        """
        订阅一种或多种事件。

        回调函数可以是同步函数，也可以是异步协程。

        Args:
            event_pattern (str): 要订阅的事件名称模式。支持 `fnmatch` 通配符，
                例如 `'task.*'` 或 `'plugin.a.finished?'`。
            callback (Callable[[Event], Any]): 当匹配的事件发布时要调用的函数。
                该函数应接受一个 `Event` 对象作为其唯一参数。
            channel (str): 要订阅的频道。默认为 "global"。

        Returns:
            Tuple[str, str, Callable]: 一个订阅句柄，可用于之后取消订阅。
        """
        async with self._lock:
            if callback not in self._subscribers[channel][event_pattern]:
                self._subscribers[channel][event_pattern].append(callback)
                logger.debug(f"新订阅: 频道 '{channel}', 模式 '{event_pattern}' -> 回调 {getattr(callback, '__name__', callback)}")
            else:
                logger.warning(
                    f"重复订阅尝试: 频道 '{channel}', 模式 '{event_pattern}' -> 回调 {getattr(callback, '__name__', callback)} 已存在。")
        return channel, event_pattern, callback

    async def unsubscribe(self, subscription_handle: Tuple[str, str, Callable]):
        """
        根据订阅时返回的句柄取消订阅。

        Args:
            subscription_handle (Tuple[str, str, Callable]): `subscribe` 方法返回的元组。
        """
        if not isinstance(subscription_handle, tuple) or len(subscription_handle) != 3:
            logger.error(f"取消订阅失败：提供了无效的句柄 '{subscription_handle}'。")
            return

        channel, event_pattern, callback = subscription_handle
        async with self._lock:
            try:
                self._subscribers[channel][event_pattern].remove(callback)
                logger.debug(f"取消订阅成功: 频道 '{channel}', 模式 '{event_pattern}' -> 回调 {getattr(callback, '__name__', callback)}")
                if not self._subscribers[channel][event_pattern]:
                    del self._subscribers[channel][event_pattern]
                if not self._subscribers[channel]:
                    del self._subscribers[channel]
            except (KeyError, ValueError):
                logger.warning(
                    f"取消订阅警告: 无法找到匹配的订阅。句柄: "
                    f"频道='{channel}', 模式='{event_pattern}', 回调={getattr(callback, '__name__', 'N/A')}"
                )

    async def publish(self, event: Event):
        """
        发布一个事件，并异步地通知所有匹配的订阅者。

        此方法会：
        1. 检查事件链深度是否超过 `max_depth`，如果超过则触发熔断。
        2. 查找指定频道和通配符频道 `*` 中所有匹配事件名称模式的订阅者。
        3. 并发地执行所有匹配的回调函数。

        Args:
            event (Event): 要发布的事件对象。
        """
        # 创建一个事件的副本进行处理，避免修改原始对象
        # 并且在这里就增加深度和更新因果链
        event_copy = Event(
            name=event.name,
            channel=event.channel,
            payload=event.payload,
            source=event.source,
            id=str(uuid.uuid4()),  # 每个发布的实例都应有新ID
            timestamp=time.time(),
            causation_chain=event.causation_chain + [event.id],
            depth=event.depth + 1
        )

        if event_copy.depth >= self.max_depth:
            logger.critical(
                f"**熔断器触发**！事件链深度达到最大值 {self.max_depth}。"
                f"事件 '{event_copy.name}' (ID: {event_copy.id}) 已被阻止发布。"
                f"调用链: {' -> '.join(event_copy.causation_chain)}"
            )
            return

        logger.info(f"发布事件: {event_copy!r}")
        matching_callbacks = []
        async with self._lock:
            # 复制一份以避免在迭代时修改
            subscribers_copy = self._subscribers.copy()

        # 后续所有操作都使用 event_copy
        channel_subs = subscribers_copy.get(event_copy.channel, {})
        for pattern, callbacks in channel_subs.items():
            if fnmatch.fnmatch(event_copy.name, pattern):
                matching_callbacks.extend(callbacks)
        if event_copy.channel != '*':
            wildcard_channel_subs = subscribers_copy.get('*', {})
            for pattern, callbacks in wildcard_channel_subs.items():
                if fnmatch.fnmatch(event_copy.name, pattern):
                    matching_callbacks.extend(callbacks)

        if not matching_callbacks:
            logger.debug(f"事件 '{event_copy.name}' 在频道 '{event_copy.channel}' 上已发布，但没有订阅者。")
            return

        unique_callbacks = list(dict.fromkeys(matching_callbacks))
        logger.debug(f"事件 '{event_copy.name}' 匹配到 {len(unique_callbacks)} 个订阅者。")

        # 使用 asyncio.gather 并发执行所有回调
        tasks = [self._execute_callback(cb, event_copy) for cb in unique_callbacks]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_callback(self, callback: Callable[[Event], Any], event: Event):
        """
        安全地执行单个回调函数。

        它能处理同步和异步回调，并捕获和记录执行期间发生的任何异常。

        Args:
            callback (Callable[[Event], Any]): 要执行的回调函数。
            event (Event): 传递给回调的事件对象。
        """
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(event)
            else:
                # 在默认的线程池中运行同步回调，避免阻塞事件循环
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, callback, event)
        except Exception as e:
            logger.error(
                f"执行事件 '{event.name}' 的回调 '{getattr(callback, '__name__', callback)}' 时发生错误: {e}",
                exc_info=True
            )

    async def shutdown(self):
        """关闭事件总线并清除所有订阅。"""
        await self.clear_subscriptions()
        logger.info("EventBus已关闭。")

    async def clear_subscriptions(self):
        """清除所有频道的全部订阅。"""
        async with self._lock:
            self._subscribers.clear()
        logger.info("EventBus的所有订阅已清除。")

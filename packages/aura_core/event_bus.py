import asyncio
import fnmatch
import time
import uuid
import dataclasses
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Awaitable

from packages.aura_core.logger import logger


@dataclass
class Event:
    name: str
    channel: str = "global"
    payload: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    causation_chain: List[str] = field(default_factory=list)
    depth: int = 0

    def __post_init__(self):
        if self.id not in self.causation_chain:
            self.causation_chain.append(self.id)

    def __repr__(self):
        return (f"Event(name='{self.name}', channel='{self.channel}', "
                f"payload={self.payload}, source='{self.source}', depth={self.depth})")


    def to_dict(self) -> Dict[str, Any]:
        """将 Event 实例转换为字典，方便序列化。"""
        return dataclasses.asdict(self)


class EventBus:
    """
    【Async Refactor】一个异步的、高性能的事件总线。
    - 使用 asyncio.Lock 保证异步安全。
    - 使用 asyncio.create_task 并发处理回调，取代了低效的线程模型。
    - 兼容同步和异步的回调函数。
    """

    def __init__(self, max_depth: int = 10):
        self._subscribers: Dict[str, Dict[str, List[Callable[[Event], Any]]]] = defaultdict(lambda: defaultdict(list))
        self._lock = asyncio.Lock()
        self.max_depth = max_depth
        logger.info(f"EventBus已初始化，最大事件深度设置为 {self.max_depth}。")

    async def subscribe(self, event_pattern: str, callback: Callable[[Event], Any], channel: str = "global") -> Tuple[str, str, Callable]:
        """
        订阅一种或多种事件。
        :param callback: 回调函数 (可以是同步或异步函数)。
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
        # 【修复】创建一个事件的副本进行处理，避免修改原始对象
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

        # 【修复】后续所有操作都使用 event_copy
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
        async with self._lock:
            self._subscribers.clear()
        logger.info("EventBus已关闭，所有订阅已清除。")

    async def clear_subscriptions(self):
        async with self._lock:
            self._subscribers.clear()
        logger.info("EventBus的所有订阅已清除。")

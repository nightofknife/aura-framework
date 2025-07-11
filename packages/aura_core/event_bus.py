# packages/aura_core/event_bus.py (最终优化版)

import fnmatch
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from packages.aura_shared_utils.utils.logger import logger


@dataclass
class Event:
    # ... (Event 类保持不变) ...
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


class EventBus:
    """
    一个线程安全的事件总线，支持频道隔离、通配符订阅和细粒度的取消订阅。
    """

    def __init__(self, max_depth: int = 10):
        self._subscribers: Dict[str, Dict[str, List[Callable[[Event], None]]]] = defaultdict(lambda: defaultdict(list))
        self._lock = threading.RLock()
        self.max_depth = max_depth
        logger.info(f"EventBus已初始化，最大事件深度设置为 {self.max_depth}。")

    def subscribe(self, event_pattern: str, callback: Callable[[Event], None], channel: str = "global"):
        """
        订阅一种或多种事件。

        :param event_pattern: 事件名称模式。
        :param callback: 回调函数。
        :param channel: 订阅的频道。
        :return: 一个包含 (channel, event_pattern, callback) 的元组，作为取消订阅的句柄。
        """
        with self._lock:
            # 检查是否重复订阅
            if callback not in self._subscribers[channel][event_pattern]:
                self._subscribers[channel][event_pattern].append(callback)
                logger.debug(f"新订阅: 频道 '{channel}', 模式 '{event_pattern}' -> 回调 {callback.__name__}")
            else:
                logger.warning(
                    f"重复订阅尝试: 频道 '{channel}', 模式 '{event_pattern}' -> 回调 {callback.__name__} 已存在。")

        # 【新增】返回一个句柄，用于取消订阅
        return channel, event_pattern, callback

    def unsubscribe(self, subscription_handle: Tuple[str, str, Callable]):
        """
        【全新方法】取消一个特定的事件订阅。

        :param subscription_handle: 调用 subscribe() 时返回的句柄。
        """
        if not isinstance(subscription_handle, tuple) or len(subscription_handle) != 3:
            logger.error(f"取消订阅失败：提供了无效的句柄 '{subscription_handle}'。")
            return

        channel, event_pattern, callback = subscription_handle
        with self._lock:
            try:
                # 从订阅者列表中移除回调
                self._subscribers[channel][event_pattern].remove(callback)
                logger.debug(f"取消订阅成功: 频道 '{channel}', 模式 '{event_pattern}' -> 回调 {callback.__name__}")

                # 如果一个模式下没有回调了，可以清理掉这个模式
                if not self._subscribers[channel][event_pattern]:
                    del self._subscribers[channel][event_pattern]

                # 如果一个频道下没有模式了，可以清理掉这个频道
                if not self._subscribers[channel]:
                    del self._subscribers[channel]

            except (KeyError, ValueError):
                # 如果句柄无效或回调已不存在，静默处理或记录警告
                logger.warning(
                    f"取消订阅警告: 无法找到匹配的订阅。句柄: "
                    f"频道='{channel}', 模式='{event_pattern}', 回调={getattr(callback, '__name__', 'N/A')}"
                )

    def publish(self, event: Event):
        # ... (publish 方法和 _execute_callback 方法保持不变) ...
        if event.depth >= self.max_depth:
            logger.critical(
                f"**熔断器触发**！事件链深度达到最大值 {self.max_depth}。"
                f"事件 '{event.name}' (ID: {event.id}) 已被阻止发布。"
                f"调用链: {' -> '.join(event.causation_chain)}"
            )
            return
        logger.info(f"发布事件: {event!r}")
        matching_callbacks = []
        with self._lock:
            channel_subs = self._subscribers.get(event.channel, {})
            for pattern, callbacks in channel_subs.items():
                if fnmatch.fnmatch(event.name, pattern):
                    matching_callbacks.extend(callbacks)
            if event.channel != '*':
                wildcard_channel_subs = self._subscribers.get('*', {})
                for pattern, callbacks in wildcard_channel_subs.items():
                    if fnmatch.fnmatch(event.name, pattern):
                        matching_callbacks.extend(callbacks)
        if not matching_callbacks:
            logger.debug(f"事件 '{event.name}' 在频道 '{event.channel}' 上已发布，但没有订阅者。")
            return
        unique_callbacks = list(dict.fromkeys(matching_callbacks))
        logger.debug(f"事件 '{event.name}' 匹配到 {len(unique_callbacks)} 个订阅者。")
        for callback in unique_callbacks:
            thread = threading.Thread(target=self._execute_callback, args=(callback, event))
            thread.daemon = True
            thread.start()

    def _execute_callback(self, callback: Callable[[Event], None], event: Event):
        try:
            callback(event)
        except Exception as e:
            logger.error(
                f"执行事件 '{event.name}' 的回调 '{callback.__name__}' 时发生错误: {e}",
                exc_info=True
            )

    def shutdown(self):
        with self._lock:
            self._subscribers.clear()
        logger.info("EventBus已关闭，所有订阅已清除。")

    def clear_subscriptions(self):
        with self._lock:
            self._subscribers.clear()
        logger.info("EventBus的所有订阅已清除。")

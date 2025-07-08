# packages/aura_core/event_bus.py (修改后)

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid
import time
import fnmatch

from packages.aura_shared_utils.utils.logger import logger


@dataclass
class Event:
    """
    代表一个在系统中流动的瞬时信号。
    """
    name: str
    # 【新增】频道属性，默认为 'global'
    channel: str = "global"
    payload: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None  # 事件来源，如插件名或任务名
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)

    # --- 用于熔断和追踪的核心元数据 ---
    causation_chain: List[str] = field(default_factory=list)
    depth: int = 0

    def __post_init__(self):
        if self.id not in self.causation_chain:
            self.causation_chain.append(self.id)

    def __repr__(self):
        # 【新增】在 repr 中显示 channel
        return (f"Event(name='{self.name}', channel='{self.channel}', "
                f"payload={self.payload}, source='{self.source}', depth={self.depth})")


class EventBus:
    """
    一个线程安全的事件总线，支持频道隔离、通配符订阅和基于调用链的熔断机制。
    """

    def __init__(self, max_depth: int = 10):
        """
        初始化事件总线。
        :param max_depth: 事件链的最大深度，用于防止无限循环（熔断器）。
        """
        # 【修改】订阅者存储结构变为: {channel: {event_pattern: [callbacks]}}
        self._subscribers: Dict[str, Dict[str, List[Callable[[Event], None]]]] = defaultdict(lambda: defaultdict(list))
        self._lock = threading.RLock()
        self.max_depth = max_depth
        logger.info(f"EventBus已初始化，最大事件深度设置为 {self.max_depth}。")

    def subscribe(self, event_pattern: str, callback: Callable[[Event], None], channel: str = "global"):
        """
        订阅一种或多种事件。

        :param event_pattern: 事件名称模式。支持通配符 '*' 和 '?'。
        :param callback: 当匹配的事件发布时要调用的回调函数。
        :param channel: 要订阅的频道。默认为 'global'。使用 '*' 可订阅所有频道。
        """
        with self._lock:
            # 【修改】将回调注册到指定的频道
            self._subscribers[channel][event_pattern].append(callback)
            logger.debug(f"新订阅: 频道 '{channel}', 模式 '{event_pattern}' -> 回调 {callback.__name__}")

    def publish(self, event: Event):
        """
        发布一个事件，并异步通知所有匹配的订阅者。
        事件将被发送到其自身的频道以及全局通配符频道 ('*')。

        :param event: 要发布的事件对象。
        """
        if event.depth >= self.max_depth:
            logger.critical(
                f"**熔断器触发**！事件链深度达到最大值 {self.max_depth}。"
                f"事件 '{event.name}' (ID: {event.id}) 已被阻止发布。"
                f"调用链: {' -> '.join(event.causation_chain)}"
            )
            return

        logger.info(f"发布事件: {event!r}")

        # 【修改】分发逻辑
        matching_callbacks = []
        with self._lock:
            # 1. 获取特定频道的订阅者
            channel_subs = self._subscribers.get(event.channel, {})
            for pattern, callbacks in channel_subs.items():
                if fnmatch.fnmatch(event.name, pattern):
                    matching_callbacks.extend(callbacks)

            # 2. 获取全局通配符频道的订阅者 (避免重复添加)
            if event.channel != '*':
                wildcard_channel_subs = self._subscribers.get('*', {})
                for pattern, callbacks in wildcard_channel_subs.items():
                    if fnmatch.fnmatch(event.name, pattern):
                        matching_callbacks.extend(callbacks)

        if not matching_callbacks:
            logger.debug(f"事件 '{event.name}' 在频道 '{event.channel}' 上已发布，但没有订阅者。")
            return

        # 去重，以防万一有重复订阅
        unique_callbacks = list(dict.fromkeys(matching_callbacks))
        logger.debug(f"事件 '{event.name}' 匹配到 {len(unique_callbacks)} 个订阅者。")

        for callback in unique_callbacks:
            thread = threading.Thread(target=self._execute_callback, args=(callback, event))
            thread.daemon = True
            thread.start()

    def _execute_callback(self, callback: Callable[[Event], None], event: Event):
        """安全地执行回调函数。"""
        try:
            callback(event)
        except Exception as e:
            logger.error(
                f"执行事件 '{event.name}' 的回调 '{callback.__name__}' 时发生错误: {e}",
                exc_info=True
            )

    def shutdown(self):
        """清理资源（如果需要）。"""
        with self._lock:
            self._subscribers.clear()
        logger.info("EventBus已关闭，所有订阅已清除。")

    def clear_subscriptions(self):
        """【新增】清理所有订阅，但保留EventBus实例本身。"""
        with self._lock:
            self._subscribers.clear()
        logger.info("EventBus的所有订阅已清除。")


# aura_core/event_bus.py

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
    payload: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None  # 事件来源，如插件名或任务名
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)

    # --- 用于熔断和追踪的核心元数据 ---
    # 调用链，记录了从初始事件到当前事件的所有事件ID
    causation_chain: List[str] = field(default_factory=list)
    # 调用深度，即调用链的长度
    depth: int = 0

    def __post_init__(self):
        # 确保每个事件ID都在其自身的调用链中
        if self.id not in self.causation_chain:
            self.causation_chain.append(self.id)


class EventBus:
    """
    一个线程安全的事件总线，支持通配符订阅和基于调用链的熔断机制。
    """

    def __init__(self, max_depth: int = 10):
        """
        初始化事件总线。
        :param max_depth: 事件链的最大深度，用于防止无限循环（熔断器）。
        """
        # 订阅者存储：{ event_pattern: [callback1, callback2, ...] }
        self._subscribers: Dict[str, List[Callable[[Event], None]]] = defaultdict(list)
        self._lock = threading.RLock()
        self.max_depth = max_depth
        logger.info(f"EventBus已初始化，最大事件深度设置为 {self.max_depth}。")

    def subscribe(self, event_pattern: str, callback: Callable[[Event], None]):
        """
        订阅一种或多种事件。

        :param event_pattern: 事件名称模式。支持通配符 '*' 和 '?'。
                              例如: 'orders:*', 'payments:PaymentSucceeded', 'users:*:updated'
        :param callback: 当匹配的事件发布时要调用的回调函数。
        """
        with self._lock:
            self._subscribers[event_pattern].append(callback)
            logger.debug(f"新订阅: 模式 '{event_pattern}' -> 回调 {callback.__name__}")

    def publish(self, event: Event):
        """
        发布一个事件，并异步通知所有匹配的订阅者。

        :param event: 要发布的事件对象。
        """
        # --- 熔断器检查 ---
        if event.depth >= self.max_depth:
            logger.critical(
                f"**熔断器触发**！事件链深度达到最大值 {self.max_depth}。"
                f"事件 '{event.name}' (ID: {event.id}) 已被阻止发布。"
                f"调用链: {' -> '.join(event.causation_chain)}"
            )
            return

        logger.info(f"发布事件: '{event.name}' (来源: {event.source}, 深度: {event.depth})")

        # 寻找所有匹配的回调
        matching_callbacks = []
        with self._lock:
            for pattern, callbacks in self._subscribers.items():
                if fnmatch.fnmatch(event.name, pattern):
                    matching_callbacks.extend(callbacks)

        if not matching_callbacks:
            logger.debug(f"事件 '{event.name}' 已发布，但没有订阅者。")
            return

        logger.debug(f"事件 '{event.name}' 匹配到 {len(matching_callbacks)} 个订阅者。")

        # 在独立的线程中执行回调，避免阻塞发布者
        for callback in matching_callbacks:
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


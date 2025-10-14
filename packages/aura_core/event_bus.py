# -*- coding: utf-8 -*-
"""提供一个线程安全的、异步的事件总线。

此模块是 Aura 框架内部组件间通信的核心。它实现了一个发布/订阅（Pub/Sub）模式，
允许系统不同部分在不直接相互引用的情况下，通过发布和订阅事件来进行解耦通信。

主要组件:
- `Event`: 一个标准化的事件数据结构。
- `EventBus`: 事件总线的实现，管理订阅和发布逻辑。

功能特性:
- **主题过滤**: 支持使用 `*` 和 `?` 等通配符进行事件名称匹配。
- **频道隔离**: 支持按频道发布和订阅事件。
- **跨线程安全**: 可以在不同的 asyncio 事件循环之间安全地发布事件。
- **持久化订阅**: 支持在清理时保留某些关键的订阅。
"""
import asyncio
import fnmatch
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, Any, List, Optional, Awaitable
import threading

def get_utc_timestamp() -> str:
    """获取当前时间的 UTC ISO 格式字符串。"""
    return datetime.now(timezone.utc).isoformat()

@dataclass
class Event:
    """代表一个在事件总线中传递的事件。

    Attributes:
        name (str): 事件的名称，例如 "task.started" 或 "plugin.loaded"。
        payload (Dict[str, Any]): 与事件相关的任意数据。
        id (str): 事件的唯一标识符，默认为 UUID。
        timestamp (str): 事件创建时的 UTC 时间戳。
        channel (str): 事件发布的频道，默认为通配符 '*'。
    """
    name: str
    payload: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=get_utc_timestamp)
    channel: str = '*'

    def to_dict(self) -> Dict[str, Any]:
        """将事件对象序列化为字典。

        Returns:
            一个包含事件所有属性的字典。
        """
        return {
            "id": self.id,
            "name": self.name,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "channel": self.channel
        }

@dataclass
class Subscription:
    """代表一个对特定事件模式的订阅。

    Attributes:
        callback (Callable[[Event], Awaitable[None]]): 当匹配的事件发生时
            要执行的异步回调函数。
        loop (Optional[asyncio.AbstractEventLoop]): 此回调函数所属的事件循环。
            如果为 None，则假定在当前事件循环中执行。
        persistent (bool): 如果为 True，此订阅在调用 `clear_subscriptions`
            时不会被移除。
    """
    callback: Callable[[Event], Awaitable[None]]
    loop: Optional[asyncio.AbstractEventLoop] = None
    persistent: bool = False

class EventBus:
    """实现发布/订阅模式的事件总线。

    这是一个线程安全的类，用于管理所有事件订阅和处理事件发布。
    """
    def __init__(self):
        """初始化 EventBus。"""
        self._subscriptions: Dict[str, List[Subscription]] = defaultdict(list)
        self._lock = threading.Lock()

    async def subscribe(
            self,
            event_pattern: str,
            callback: Callable[[Event], Awaitable[None]],
            channel: str = '*',
            *,
            loop: Optional[asyncio.AbstractEventLoop] = None,
            persistent: bool = False
    ):
        """订阅一个或多个事件。

        Args:
            event_pattern (str): 要订阅的事件名称模式。支持 `*` 和 `?` 通配符。
            callback: 匹配到事件时要执行的异步回调函数。
            channel (str): 要订阅的频道。默认为 `*`，表示所有频道。
            loop (Optional[asyncio.AbstractEventLoop]): 回调函数应在哪个事件循环
                中执行。如果为 None，则在发布者的事件循环中执行。
            persistent (bool): 是否为持久化订阅。
        """
        key = f"{channel}::{event_pattern}"
        with self._lock:
            for sub in self._subscriptions[key]:
                if sub.callback is callback and sub.loop is loop and sub.persistent == persistent:
                    return
            self._subscriptions[key].append(Subscription(callback=callback, loop=loop, persistent=persistent))

    async def publish(self, event: Event):
        """发布一个事件到事件总线。

        此方法会查找所有匹配该事件名称和频道的订阅，并异步地执行它们的回调函数。
        如果订阅者属于不同的事件循环，它会安全地将回调任务提交到对应的循环中。

        Args:
            event (Event): 要发布的事件对象。
        """
        tasks = []
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        with self._lock:
            all_subscriptions = list(self._subscriptions.items())

        for key, subscriptions in all_subscriptions:
            channel, pattern = key.split('::', 1)
            if (channel == '*' or event.channel == channel) and fnmatch.fnmatch(event.name, pattern):
                for sub in subscriptions:
                    if sub.loop and sub.loop is not current_loop:
                        sub.loop.call_soon_threadsafe(
                            sub.loop.create_task,
                            sub.callback(event)
                        )
                    elif current_loop:
                        tasks.append(current_loop.create_task(sub.callback(event)))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def clear_subscriptions(self):
        """清除所有非持久化的订阅。

        此方法会遍历所有订阅，并移除那些 `persistent` 标志为 False 的订阅。
        """
        with self._lock:
            for key, subs in list(self._subscriptions.items()):
                self._subscriptions[key] = [s for s in subs if s.persistent]


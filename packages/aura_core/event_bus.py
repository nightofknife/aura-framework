# packages/aura_core/event_bus.py

import asyncio
import fnmatch
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, Any, List, Optional, Awaitable
import threading  # <--- 导入 threading

def get_utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

@dataclass
class Event:
    name: str
    payload: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=get_utc_timestamp)
    channel: str = '*'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "channel": self.channel
        }

@dataclass
class Subscription:
    callback: Callable[[Event], Awaitable[None]]
    loop: Optional[asyncio.AbstractEventLoop] = None
    persistent: bool = False

class EventBus:
    def __init__(self):
        self._subscriptions: Dict[str, List[Subscription]] = defaultdict(list)
        # --- MODIFIED: 使用线程安全的 threading.Lock ---
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
        key = f"{channel}::{event_pattern}"
        # --- MODIFIED: 使用同步的 with self._lock ---
        with self._lock:
            # 规避重复注册（同时考虑 loop 与 persistent）
            for sub in self._subscriptions[key]:
                if sub.callback is callback and sub.loop is loop and sub.persistent == persistent:
                    return
            self._subscriptions[key].append(Subscription(callback=callback, loop=loop, persistent=persistent))

    async def publish(self, event: Event):
        tasks = []
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        # --- MODIFIED: 使用同步的 with self._lock ---
        with self._lock:
            # 创建一个订阅列表的副本以进行迭代，防止在迭代时修改原始列表
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
        # --- MODIFIED: 使用同步的 with self._lock ---
        with self._lock:
            for key, subs in list(self._subscriptions.items()):
                self._subscriptions[key] = [s for s in subs if s.persistent]


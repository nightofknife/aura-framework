# -*- coding: utf-8 -*-
"""Asynchronous observability persistence writer."""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Iterable, Tuple

from packages.aura_core.observability.logging.core_logger import logger
from packages.aura_core.observability.run_store import RunStore

EventRow = Tuple[str, Dict[str, Any], int]


@dataclass
class ObservabilityWriterStats:
    enqueued: int = 0
    flushed: int = 0
    dropped_debug: int = 0
    overflow_sync_writes: int = 0


class ObservabilityWriter:
    """Batch RunStore writes outside EventBus publish callbacks."""

    def __init__(
        self,
        run_store: RunStore,
        *,
        queue_max_size: int = 10000,
        flush_interval_ms: int = 100,
        batch_size: int = 200,
        drop_policy: str = "drop_debug_keep_terminal",
    ):
        self.run_store = run_store
        self.queue_max_size = int(queue_max_size)
        self.flush_interval_ms = int(flush_interval_ms)
        self.batch_size = int(batch_size)
        self.drop_policy = drop_policy
        self.stats = ObservabilityWriterStats()
        self._queue: Deque[EventRow] = deque()
        self._critical: Deque[EventRow] = deque()
        self._lock = threading.RLock()
        self._task: asyncio.Task | None = None
        self._stopping = False

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        try:
            self._stopping = False
            self._task = asyncio.create_task(self._run())
        except RuntimeError:
            self._task = None

    async def stop(self) -> None:
        self._stopping = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.flush_pending()

    def enqueue(self, name: str, payload: Dict[str, Any], timestamp_ms: int, *, critical: bool = True) -> None:
        row = (name, dict(payload), int(timestamp_ms))
        with self._lock:
            if critical:
                self._critical.append(row)
                self.stats.enqueued += 1
                return
            if len(self._queue) >= self.queue_max_size:
                self._queue.popleft()
                self.stats.dropped_debug += 1
            self._queue.append(row)
            self.stats.enqueued += 1

    def flush_pending(self) -> int:
        total = 0
        while True:
            batch = self._drain_batch()
            if not batch:
                break
            self._apply_batch(batch)
            total += len(batch)
        return total

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "queue_depth": len(self._queue) + len(self._critical),
                "critical_depth": len(self._critical),
                "debug_depth": len(self._queue),
                "queue_max_size": self.queue_max_size,
                "flush_interval_ms": self.flush_interval_ms,
                "batch_size": self.batch_size,
                "drop_policy": self.drop_policy,
                "stats": self.stats.__dict__.copy(),
            }

    async def _run(self) -> None:
        try:
            while not self._stopping:
                await asyncio.sleep(max(1, self.flush_interval_ms) / 1000.0)
                self.flush_pending()
        except asyncio.CancelledError:
            self.flush_pending()
            raise

    def _drain_batch(self) -> list[EventRow]:
        with self._lock:
            batch: list[EventRow] = []
            while self._critical and len(batch) < self.batch_size:
                batch.append(self._critical.popleft())
            while self._queue and len(batch) < self.batch_size:
                batch.append(self._queue.popleft())
            return batch

    def _apply_batch(self, batch: Iterable[EventRow]) -> None:
        rows = list(batch)
        if not rows:
            return
        try:
            self.run_store.apply_events_batch(rows)
            self.stats.flushed += len(rows)
        except Exception as exc:  # noqa: BLE001
            logger.error("ObservabilityWriter batch flush failed: %s", exc, exc_info=True)

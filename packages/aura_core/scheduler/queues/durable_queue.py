# -*- coding: utf-8 -*-
"""SQLite-backed main task queue with recoverable leases."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from packages.aura_core.observability.run_store import RunStore
from packages.aura_core.scheduler.queues.task_queue import Tasklet


class DurableTaskQueue:
    """TaskQueue-compatible facade backed by RunStore.queue_items."""

    def __init__(
        self,
        *,
        run_store: RunStore,
        maxsize: int = 1000,
        queue_name: str = "main",
        worker_id: str | None = None,
        lease_ttl_sec: float = 3600.0,
    ) -> None:
        self._run_store = run_store
        self._maxsize = int(maxsize)
        self._queue_name = queue_name
        self._worker_id = worker_id or f"aura-{uuid.uuid4().hex[:10]}"
        self._lease_ttl_ms = int(float(lease_ttl_sec) * 1000)
        self._condition = asyncio.Condition()
        self._leased: Dict[str, str] = {}
        self._poll_interval_sec = 0.5
        self._run_store.queue_recover_expired_leases(queue_name=self._queue_name)

    async def put(self, tasklet: Tasklet, high_priority: bool = False) -> None:
        await self._enqueue(tasklet, index=0 if high_priority else None)

    def put_nowait(self, tasklet: Tasklet, high_priority: bool = False) -> None:
        self._run_store.queue_enqueue(self._record_from_tasklet(tasklet), index=0 if high_priority else None)

    async def insert_at(self, index: int, tasklet: Tasklet) -> bool:
        await self._enqueue(tasklet, index=index)
        return True

    async def _enqueue(self, tasklet: Tasklet, *, index: int | None = None) -> None:
        async with self._condition:
            while self.qsize() >= self._maxsize:
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=self._poll_interval_sec)
                except asyncio.TimeoutError:
                    continue
            self._run_store.queue_enqueue(self._record_from_tasklet(tasklet), index=index)
            self._condition.notify_all()

    async def get(self) -> Tasklet:
        async with self._condition:
            while True:
                claimed = self._run_store.queue_claim_ready(
                    worker_id=self._worker_id,
                    queue_name=self._queue_name,
                    lease_ttl_ms=self._lease_ttl_ms,
                )
                if claimed:
                    tasklet = self._tasklet_from_record(claimed)
                    lease_token = claimed.get("lease_token")
                    if tasklet.cid and lease_token:
                        self._leased[tasklet.cid] = str(lease_token)
                        setattr(tasklet, "_queue_lease_token", str(lease_token))
                    self._condition.notify_all()
                    return tasklet
                await self._condition.wait()

    def task_done(self) -> None:
        # Durable queues ack by cid via ack(); this keeps TaskQueue compatibility.
        return None

    async def join(self) -> None:
        async with self._condition:
            while self.qsize() > 0:
                await self._condition.wait()

    def empty(self) -> bool:
        return self.qsize() == 0

    def qsize(self) -> int:
        overview = self._run_store.queue_overview(queue_name=self._queue_name)
        return int(overview.get("ready_length") or 0) + int(overview.get("delayed_length") or 0)

    async def ack(self, cid: str, lease_token: str | None = None) -> bool:
        token = lease_token or self._leased.get(cid)
        ok = self._run_store.queue_ack(cid, token)
        if ok:
            self._leased.pop(cid, None)
        async with self._condition:
            self._condition.notify_all()
        return ok

    async def release(self, cid: str, *, error: str | None = None) -> bool:
        token = self._leased.get(cid)
        if token:
            ok = self._run_store.queue_drop(cid, token, reason=error or "released")
        else:
            ok = self._run_store.queue_drop(cid, reason=error or "released")
        if ok:
            self._leased.pop(cid, None)
        async with self._condition:
            self._condition.notify_all()
        return ok

    async def remove_by_cid(self, cid: str) -> bool:
        ok = self._run_store.queue_remove(cid)
        async with self._condition:
            self._condition.notify_all()
        return ok

    async def remove_by_filter(self, predicate) -> int:
        removed = 0
        for item in await self.list_all():
            tasklet = self._tasklet_from_record(item)
            if predicate(tasklet):
                if self._run_store.queue_remove(str(item.get("cid"))):
                    removed += 1
        async with self._condition:
            self._condition.notify_all()
        return removed

    async def move_to_front(self, cid: str) -> bool:
        return await self.move_to_position(cid, 0)

    async def move_to_position(self, cid: str, new_index: int) -> bool:
        ok = self._run_store.queue_move_to_position(cid, new_index, queue_name=self._queue_name)
        async with self._condition:
            self._condition.notify_all()
        return ok

    async def list_all(self) -> List[Dict[str, Any]]:
        rows = self._run_store.queue_list(state="ready", queue_name=self._queue_name, limit=500)
        return [self._queue_item_for_api(row) for row in rows]

    async def clear(self) -> int:
        count = self._run_store.queue_clear(queue_name=self._queue_name)
        async with self._condition:
            self._condition.notify_all()
        return count

    async def reorder(self, cid_order: List[str]) -> bool:
        ok = self._run_store.queue_reorder(cid_order, queue_name=self._queue_name)
        async with self._condition:
            self._condition.notify_all()
        return ok

    def overview(self) -> Dict[str, Any]:
        return self._run_store.queue_overview(queue_name=self._queue_name)

    def recovery_status(self) -> Dict[str, Any]:
        return self._run_store.queue_recovery_status(queue_name=self._queue_name)

    def recover(self) -> Dict[str, Any]:
        result = self._run_store.queue_recover_expired_leases(queue_name=self._queue_name)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._notify())
        except RuntimeError:
            pass
        return result

    def abandon_stale(self) -> Dict[str, Any]:
        result = self._run_store.queue_abandon_stale(queue_name=self._queue_name)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._notify())
        except RuntimeError:
            pass
        return result

    async def _notify(self) -> None:
        async with self._condition:
            self._condition.notify_all()

    def _record_from_tasklet(self, tasklet: Tasklet) -> Dict[str, Any]:
        payload = tasklet.payload or {}
        plan_name = payload.get("plan_name")
        task_name = payload.get("task_name") or payload.get("task")
        if (not plan_name or not task_name) and isinstance(tasklet.task_name, str) and "/" in tasklet.task_name:
            plan_name, task_name = tasklet.task_name.split("/", 1)
        enqueued_at_ms = int((getattr(tasklet, "enqueued_at", None) or time.time()) * 1000)
        return {
            "cid": tasklet.cid,
            "queue_name": self._queue_name,
            "state": "ready",
            "plan_name": plan_name,
            "task_name": task_name or tasklet.task_name,
            "trace_id": tasklet.trace_id,
            "trace_label": tasklet.trace_label,
            "source": tasklet.source,
            "priority": int((payload.get("priority") if isinstance(payload, dict) else 0) or 0),
            "enqueued_at_ms": enqueued_at_ms,
            "payload": payload,
            "initial_context": tasklet.initial_context or {},
            "tasklet": _tasklet_to_dict(tasklet),
            "max_attempts": 2,
        }

    def _tasklet_from_record(self, record: Dict[str, Any]) -> Tasklet:
        raw = record.get("tasklet") or {}
        tasklet = Tasklet(
            task_name=str(raw.get("task_name") or record.get("task_name")),
            cid=record.get("cid") or raw.get("cid"),
            trace_id=record.get("trace_id") or raw.get("trace_id"),
            trace_label=record.get("trace_label") or raw.get("trace_label"),
            source=record.get("source") or raw.get("source"),
            payload=record.get("payload") or raw.get("payload") or {},
            is_ad_hoc=bool(raw.get("is_ad_hoc", False)),
            initial_context=record.get("initial_context") or raw.get("initial_context") or {},
            execution_mode=raw.get("execution_mode") or "sync",
            resource_tags=list(raw.get("resource_tags") or []),
            timeout=raw.get("timeout", 3600.0),
            cpu_bound=bool(raw.get("cpu_bound", False)),
            enqueued_at=float(record.get("enqueued_at") or time.time()),
            planning_depth=int(raw.get("planning_depth") or 0),
        )
        return tasklet

    def _queue_item_for_api(self, record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "cid": record.get("cid"),
            "task_name": record.get("task_name"),
            "plan_name": record.get("plan_name"),
            "trace_id": record.get("trace_id"),
            "trace_label": record.get("trace_label"),
            "source": record.get("source"),
            "enqueued_at": record.get("enqueued_at"),
            "payload": record.get("payload") or {},
            "state": record.get("state"),
        }


def _tasklet_to_dict(tasklet: Tasklet) -> Dict[str, Any]:
    return {
        "task_name": tasklet.task_name,
        "cid": tasklet.cid,
        "trace_id": tasklet.trace_id,
        "trace_label": tasklet.trace_label,
        "source": tasklet.source,
        "payload": tasklet.payload or {},
        "is_ad_hoc": bool(tasklet.is_ad_hoc),
        "initial_context": tasklet.initial_context or {},
        "execution_mode": tasklet.execution_mode,
        "resource_tags": list(tasklet.resource_tags or []),
        "timeout": tasklet.timeout,
        "cpu_bound": bool(tasklet.cpu_bound),
        "enqueued_at": tasklet.enqueued_at,
        "planning_depth": int(tasklet.planning_depth or 0),
    }

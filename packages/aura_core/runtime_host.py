# -*- coding: utf-8 -*-
"""Runtime host for coordinating Scheduler lifecycle."""
from __future__ import annotations

from typing import Any, Optional


class RuntimeHost:
    def __init__(self, scheduler: Any):
        self._scheduler = scheduler

    def start(self) -> None:
        self._scheduler.start_scheduler()

    def stop(self) -> None:
        self._scheduler.stop_scheduler()

    def wait_started(self, timeout: Optional[float] = None) -> bool:
        return self._scheduler.startup_complete_event.wait(timeout=timeout)

    def is_running(self) -> bool:
        status = self._scheduler.get_master_status() or {}
        return bool(status.get("is_running"))

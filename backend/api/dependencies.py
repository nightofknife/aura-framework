# -*- coding: utf-8 -*-
"""Dependency providers for backend API routes."""

from __future__ import annotations

import threading
from typing import Optional

from fastapi import Depends

from packages.aura_core.api import ACTION_REGISTRY, service_registry
from packages.aura_core.runtime.bootstrap import create_runtime, peek_runtime, reset_runtime
from packages.aura_core.scheduler import Scheduler

_scheduler_lock = threading.RLock()
_scheduler_instance: Optional[Scheduler] = None


def get_core_scheduler() -> Scheduler:
    """Return the lazily-created scheduler singleton."""

    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is None:
            _scheduler_instance = create_runtime(profile="api_full")
        return _scheduler_instance


def peek_core_scheduler() -> Optional[Scheduler]:
    """Return the scheduler singleton without creating it."""

    with _scheduler_lock:
        runtime = peek_runtime()
        if runtime is not None:
            return runtime
        return _scheduler_instance


def reset_core_scheduler() -> None:
    """Drop the current scheduler singleton reference."""

    global _scheduler_instance
    with _scheduler_lock:
        reset_runtime()
        ACTION_REGISTRY.clear()
        service_registry.clear()
        _scheduler_instance = None


CoreScheduler = Depends(get_core_scheduler)

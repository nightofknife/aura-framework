# -*- coding: utf-8 -*-
"""API server entrypoints."""

from __future__ import annotations

from typing import Optional

import uvicorn


def serve_api(
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    reload: Optional[bool] = None,
    log_level: Optional[str] = None,
    workers: Optional[int] = None,
    access_log: Optional[bool] = None,
) -> None:
    """Serve the Aura FastAPI application."""

    uvicorn.run(
        "backend.api.app:create_app",
        factory=True,
        host=host or "127.0.0.1",
        port=int(port or 18098),
        reload=bool(reload) if reload is not None else False,
        log_level=log_level or "info",
        workers=int(workers or 1),
        access_log=True if access_log is None else bool(access_log),
    )


# -*- coding: utf-8 -*-
"""API server entrypoints."""

from __future__ import annotations

import os
from typing import Optional

import uvicorn

from backend.api.security import build_api_security_settings
from packages.aura_core.config.loader import get_config_value


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

    resolved_host = str(host or get_config_value("api.host", "127.0.0.1") or "127.0.0.1").strip()
    resolved_port = int(port if port is not None else (get_config_value("api.port", 18098) or 18098))
    settings = build_api_security_settings(resolved_host)

    # Keep the app factory and the bind host in sync when the host is provided at launch time.
    previous_host = os.environ.get("AURA_API_HOST")
    os.environ["AURA_API_HOST"] = settings.bind_host
    try:
        uvicorn.run(
            "backend.api.app:create_app",
            factory=True,
            host=settings.bind_host,
            port=resolved_port,
            reload=bool(reload) if reload is not None else False,
            log_level=log_level or "info",
            workers=int(workers or 1),
            access_log=True if access_log is None else bool(access_log),
        )
    finally:
        if previous_host is None:
            os.environ.pop("AURA_API_HOST", None)
        else:
            os.environ["AURA_API_HOST"] = previous_host


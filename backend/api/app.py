# -*- coding: utf-8 -*-
"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.dependencies import peek_core_scheduler, reset_core_scheduler
from backend.api.security import apply_api_security
from backend.api.routes.catalog import router as catalog_router
from backend.api.routes.capabilities import router as capabilities_router
from backend.api.routes.diagnostics import router as diagnostics_router
from backend.api.routes.execution import router as execution_router
from backend.api.routes.migrations import router as migrations_router
from backend.api.routes.plans import router as plans_router
from backend.api.routes.policy import router as policy_router
from backend.api.routes.observability import router as observability_router
from backend.api.routes.queue import router as queue_router
from backend.api.routes.runs import router as runs_router
from backend.api.routes.runtime import router as runtime_router
from backend.api.routes.system import router as system_router
from backend.api.routes.workspace import router as workspace_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        scheduler = peek_core_scheduler()
        if scheduler is not None:
            try:
                master_status = scheduler.get_master_status()
                if master_status.get("is_running"):
                    scheduler.stop_scheduler()
            finally:
                reset_core_scheduler()


def create_app() -> FastAPI:
    """Create the Aura API application."""

    app = FastAPI(
        title="Aura API",
        version="0.1.0",
        lifespan=lifespan,
    )

    apply_api_security(app)

    app.include_router(system_router, prefix="/api/v1")
    app.include_router(execution_router, prefix="/api/v1")
    app.include_router(plans_router, prefix="/api/v1")
    app.include_router(queue_router, prefix="/api/v1")
    app.include_router(runs_router, prefix="/api/v1")
    app.include_router(catalog_router, prefix="/api/v1")
    app.include_router(capabilities_router, prefix="/api/v1")
    app.include_router(workspace_router, prefix="/api/v1")
    app.include_router(diagnostics_router, prefix="/api/v1")
    app.include_router(policy_router, prefix="/api/v1")
    app.include_router(observability_router, prefix="/api/v1")
    app.include_router(migrations_router, prefix="/api/v1")
    app.include_router(runtime_router, prefix="/api/v1")

    return app

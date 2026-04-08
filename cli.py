# -*- coding: utf-8 -*-
"""Aura unified launcher: TUI mode and API mode."""

from __future__ import annotations

import click

from backend.run import serve_api


@click.group()
def aura() -> None:
    """Aura launcher."""


@aura.command("tui")
def tui_command() -> None:
    """Run interactive TUI mode (manual task execution only)."""
    try:
        from packages.aura_core.cli.tui_app import run_tui
    except ModuleNotFoundError as exc:
        raise click.ClickException(
            "TUI mode requires `prompt_toolkit`. Please install dependencies first "
            "(`pip install -r requirements.txt`)."
        ) from exc

    run_tui()


@aura.group("api")
def api_group() -> None:
    """API mode commands."""


@api_group.command("serve")
@click.option("--host", type=str, default=None, help="API host.")
@click.option("--port", type=int, default=None, help="API port.")
@click.option("--reload/--no-reload", default=None, help="Enable auto-reload.")
@click.option("--log-level", type=str, default=None, help="Uvicorn log level.")
@click.option("--workers", type=int, default=None, help="Uvicorn workers.")
@click.option("--access-log/--no-access-log", default=None, help="Enable access log.")
def api_serve_command(
    host: str | None,
    port: int | None,
    reload: bool | None,
    log_level: str | None,
    workers: int | None,
    access_log: bool | None,
) -> None:
    """Run API service mode."""
    serve_api(
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
        workers=workers,
        access_log=access_log,
    )


if __name__ == "__main__":
    aura()

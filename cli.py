# -*- coding: utf-8 -*-
"""Aura unified launcher: TUI mode and API mode."""

from __future__ import annotations

import contextlib
import json
import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import click

from backend.run import serve_api
from packages.aura_core.compat import CompatibilityService
from packages.aura_core.debugging import DebugService
from packages.aura_core.diagnostics import DiagnosticsCollector
from packages.aura_core.fixtures import FixtureService
from packages.aura_core.cli.authoring_tools import (
    scaffold_package,
    scaffold_task,
    task_explain,
    task_graph,
    template_render,
)
from packages.aura_core.cli.validator_cli import validate_workspace
from packages.aura_core.observability.query import ObservabilityQueryService
from packages.aura_core.observability.persistence import PersistenceLifecycleService
from packages.aura_core.packaging.core.dependency_manager import PackageDependencyService
from packages.aura_core.packaging.core.workspace_lifecycle import WorkspaceLifecycleService
from packages.aura_core.policy import CAPABILITY_TAXONOMY, POLICY_PROFILES, get_active_policy_profile
from packages.aura_core.release_packaging import ReleasePackager


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


@aura.command("validate")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None, help="Workspace root.")
@click.option("--plan", type=str, default=None, help="Validate one plan by directory name.")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format.")
@click.option("--strict/--no-strict", default=False, help="Enable stricter static checks.")
@click.option("--dry-run/--no-dry-run", default=False, help="Validate one task without executing actions.")
@click.option("--task-ref", type=str, default=None, help="Canonical task_ref required by --dry-run.")
def validate_command(
    base_path: str | None,
    plan: str | None,
    output_format: str,
    strict: bool,
    dry_run: bool,
    task_ref: str | None,
) -> None:
    """Validate manifests and task YAML without executing actions."""

    try:
        with contextlib.redirect_stdout(sys.stderr):
            exit_code, rendered = validate_workspace(
                base_path=base_path,
                plan=plan,
                output_format=output_format,  # type: ignore[arg-type]
                strict=strict,
                dry_run=dry_run,
                task_ref=task_ref,
            )
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        raise click.exceptions.Exit(2) from exc
    click.echo(rendered)
    if exit_code:
        raise click.exceptions.Exit(exit_code)


@aura.group("core")
def core_group() -> None:
    """Core framework boundary commands."""


@core_group.command("smoke")
@click.option("--profile", default="framework-core", show_default=True)
@click.option("--minimal-workspace/--current-workspace", default=True, show_default=True)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def core_smoke_command(profile: str, minimal_workspace: bool, output_format: str) -> None:
    """Verify the minimal Aura core boundary without desktop capabilities."""

    result = _core_smoke(profile=profile, minimal_workspace=minimal_workspace)
    if output_format == "json":
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        click.echo(f"Core smoke: {result['status']}")
        click.echo(f"- profile: {result.get('profile')}")
        click.echo(f"- base_path: {result.get('base_path')}")
        for step in result.get("steps", []):
            click.echo(f"- {step['name']}: {step['status']}")
        for blocked in result.get("blocked_import_details", []):
            click.echo(f"- BLOCKED IMPORT: {blocked.get('module')} ({blocked.get('reason')})")
            click.echo(f"  hint: {blocked.get('dependency_hint')}")
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@aura.group("package")
def package_group() -> None:
    """Workspace package lifecycle commands."""


@package_group.command("list")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def package_list_command(base_path: str | None, output_format: str) -> None:
    service = WorkspaceLifecycleService(Path(base_path or Path.cwd()))
    rows = service.list_packages()
    if output_format == "json":
        click.echo(json.dumps({"packages": rows}, ensure_ascii=False, indent=2))
        return
    for row in rows:
        state = "enabled" if row.get("enabled") else "disabled"
        drift = " drift" if row.get("lock_drift") else ""
        click.echo(f"{row['id']} {row.get('version')} {state} {row.get('validation_status')}{drift} {row.get('source')}")


@package_group.command("validate")
@click.argument("package_or_path", required=False)
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def package_validate_command(package_or_path: str | None, base_path: str | None, output_format: str) -> None:
    service = WorkspaceLifecycleService(Path(base_path or Path.cwd()))
    result = service.validate_package(package_or_path)
    if output_format == "json":
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["status"] == "success":
        click.echo("Package validation passed.")
    else:
        click.echo(f"Package validation failed with {len(result['errors'])} error(s):")
        for error in result["errors"]:
            click.echo(f"- [{error.get('code')}] {error.get('message')}")
    if result["status"] != "success":
        raise click.exceptions.Exit(1)


@package_group.command("install")
@click.argument("path")
@click.option("--link/--copy", default=False)
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def package_install_command(path: str, link: bool, base_path: str | None) -> None:
    service = WorkspaceLifecycleService(Path(base_path or Path.cwd()))
    result = service.install_package(path, link=link)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@package_group.command("enable")
@click.argument("package_id")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def package_enable_command(package_id: str, base_path: str | None) -> None:
    _package_state_command(package_id, base_path, enabled=True)


@package_group.command("disable")
@click.argument("package_id")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def package_disable_command(package_id: str, base_path: str | None) -> None:
    _package_state_command(package_id, base_path, enabled=False)


@package_group.command("remove")
@click.argument("package_id")
@click.option("--keep-files/--delete-files", default=False)
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def package_remove_command(package_id: str, keep_files: bool, base_path: str | None) -> None:
    service = WorkspaceLifecycleService(Path(base_path or Path.cwd()))
    result = service.remove_package(package_id, keep_files=keep_files)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@package_group.command("lock")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def package_lock_command(base_path: str | None) -> None:
    service = WorkspaceLifecycleService(Path(base_path or Path.cwd()))
    lock = service.write_lock()
    click.echo(json.dumps({"status": "success", "lock_path": str(service.lock_path), "packages": lock.get("packages", [])}, ensure_ascii=False, indent=2))


@package_group.command("doctor")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def package_doctor_command(base_path: str | None, output_format: str) -> None:
    result = WorkspaceLifecycleService(Path(base_path or Path.cwd())).doctor()
    if output_format == "json":
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        click.echo(f"Package doctor: {result['status']}")
        for error in result.get("errors", []):
            click.echo(f"- ERROR [{error.get('code')}] {error}")
        for warning in result.get("warnings", []):
            click.echo(f"- WARN [{warning.get('code')}] {warning}")
    if result["status"] != "success":
        raise click.exceptions.Exit(1)


@package_group.group("deps")
def package_deps_group() -> None:
    """Explicit package Python dependency workflow."""


@package_deps_group.command("doctor")
@click.argument("package_id")
@click.option("--profile", default="workspace-default", show_default=True)
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def package_deps_doctor_command(package_id: str, profile: str, base_path: str | None, output_format: str) -> None:
    result = PackageDependencyService(Path(base_path or Path.cwd())).doctor(package_id, profile=profile)
    _emit_dependency_result(result, output_format=output_format, title="Package dependency doctor")


@package_deps_group.command("plan")
@click.argument("package_id")
@click.option("--profile", default="workspace-default", show_default=True)
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def package_deps_plan_command(package_id: str, profile: str, base_path: str | None, output_format: str) -> None:
    result = PackageDependencyService(Path(base_path or Path.cwd())).plan(package_id, profile=profile)
    _emit_dependency_result(result, output_format=output_format, title="Package dependency install plan", fail_on_missing=False)


@package_deps_group.command("install")
@click.argument("package_id")
@click.option("--profile", default="workspace-default", show_default=True)
@click.option("--apply", "apply_install", is_flag=True, default=False)
@click.option("--dry-run", "dry_run", is_flag=True, default=False)
@click.option("--trusted/--untrusted", default=False, help="Confirm this package is trusted to modify the local Python environment.")
@click.option("--allow-network/--no-network", default=False, help="Confirm pip may contact configured package indexes.")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def package_deps_install_command(
    package_id: str,
    profile: str,
    apply_install: bool,
    dry_run: bool,
    trusted: bool,
    allow_network: bool,
    base_path: str | None,
    output_format: str,
) -> None:
    result = PackageDependencyService(Path(base_path or Path.cwd())).install(
        package_id,
        profile=profile,
        apply=bool(apply_install and not dry_run),
        trusted=trusted,
        allow_network=allow_network,
    )
    _emit_dependency_result(result, output_format=output_format, title="Package dependency install", fail_on_missing=False)


@package_group.command("permissions")
@click.argument("package_id")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def package_permissions_command(package_id: str, base_path: str | None) -> None:
    scheduler = _load_runtime(base_path)
    normalized = package_id.strip().lstrip("@")
    actions = []
    services = []
    from packages.aura_core.api import ACTION_REGISTRY, service_registry

    for action in ACTION_REGISTRY.get_all_action_definitions():
        action_package = getattr(getattr(action.plugin, "package", None), "canonical_id", "").lstrip("@")
        if action_package == normalized:
            actions.append(_permission_row(action, key="fqid"))
    for service in service_registry.get_all_service_definitions():
        service_package = getattr(getattr(service.plugin, "package", None), "canonical_id", "").lstrip("@")
        if service_package == normalized:
            services.append(_permission_row(service, key="fqid"))
    click.echo(json.dumps({"package_id": normalized, "actions": actions, "services": services}, ensure_ascii=False, indent=2))


@package_group.command("pack")
@click.argument("package_id")
@click.option("--output", type=click.Path(file_okay=True, dir_okay=False), default=None)
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def package_pack_command(package_id: str, output: str | None, base_path: str | None) -> None:
    result = WorkspaceLifecycleService(Path(base_path or Path.cwd())).pack_package(package_id, output=output)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@package_group.command("diff")
@click.argument("old_package")
@click.argument("new_package")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def package_diff_command(old_package: str, new_package: str, base_path: str | None) -> None:
    result = WorkspaceLifecycleService(Path(base_path or Path.cwd())).diff_packages(old_package, new_package)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@package_group.command("compat")
@click.argument("package_id")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def package_compat_command(package_id: str, base_path: str | None) -> None:
    result = WorkspaceLifecycleService(Path(base_path or Path.cwd())).compat_package(package_id)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@package_group.command("upgrade-plan")
@click.argument("package_id")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def package_upgrade_plan_command(package_id: str, base_path: str | None) -> None:
    result = CompatibilityService(Path(base_path or Path.cwd())).upgrade_plan(package_id)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@package_group.command("upgrade")
@click.argument("package_id")
@click.option("--from", "from_path", required=True, type=click.Path(exists=True))
@click.option("--dry-run", "dry_run", is_flag=True, default=False)
@click.option("--apply", "apply_upgrade", is_flag=True, default=False)
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def package_upgrade_command(
    package_id: str,
    from_path: str,
    dry_run: bool,
    apply_upgrade: bool,
    base_path: str | None,
) -> None:
    result = WorkspaceLifecycleService(Path(base_path or Path.cwd())).upgrade_package(
        package_id,
        from_path,
        dry_run=dry_run or not apply_upgrade,
        apply=apply_upgrade,
    )
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@package_group.command("rollback")
@click.argument("package_id")
@click.option("--to-lock", type=click.Path(file_okay=True, dir_okay=False), default=None)
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def package_rollback_command(package_id: str, to_lock: str | None, base_path: str | None) -> None:
    result = WorkspaceLifecycleService(Path(base_path or Path.cwd())).rollback_package(package_id, to_lock=to_lock)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@package_group.command("migrations")
@click.argument("package_id")
@click.option("--execute/--dry-run", default=False, help="Execute trusted local hooks instead of only reporting them.")
@click.option("--trusted/--untrusted", default=False, help="Confirm the package is trusted for migration execution.")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def package_migrations_command(package_id: str, execute: bool, trusted: bool, base_path: str | None) -> None:
    result = WorkspaceLifecycleService(Path(base_path or Path.cwd())).package_migrations(
        package_id,
        execute=execute,
        trusted=trusted,
    )
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@package_group.command("reload")
@click.argument("package_id")
@click.option("--drain/--no-drain", default=False)
@click.option("--timeout-sec", type=float, default=30.0)
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def package_reload_command(package_id: str, drain: bool, timeout_sec: float, base_path: str | None) -> None:
    scheduler = _load_runtime(base_path)
    if scheduler._loop and scheduler._loop.is_running():
        result = scheduler.run_on_control_loop(
            scheduler.apply_runtime_reload(
                package_id=package_id,
                mode="package",
                drain=drain,
                timeout_sec=timeout_sec,
            ),
            timeout=max(5.0, timeout_sec + 5.0),
        )
    else:
        result = asyncio.run(
            scheduler.apply_runtime_reload(
                package_id=package_id,
                mode="package",
                drain=drain,
                timeout_sec=timeout_sec,
            )
        )
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@aura.group("policy")
def policy_group() -> None:
    """Runtime policy commands."""


@policy_group.command("inspect")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def policy_inspect_command(base_path: str | None) -> None:
    scheduler = _load_runtime(base_path)
    _ = scheduler
    payload = {
        "profile": get_active_policy_profile(),
        "capabilities": CAPABILITY_TAXONOMY,
        "profiles": {
            name: {"allow": sorted(rules["allow"]), "deny": sorted(rules["deny"])}
            for name, rules in POLICY_PROFILES.items()
        },
    }
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@policy_group.command("doctor")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def policy_doctor_command(base_path: str | None) -> None:
    result = _policy_doctor_payload(base_path)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("errors"):
        raise click.exceptions.Exit(1)


@aura.group("sdk")
def sdk_group() -> None:
    """Extension SDK commands."""


@sdk_group.command("doctor")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def sdk_doctor_command(base_path: str | None) -> None:
    result = _sdk_doctor_payload(base_path)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@sdk_group.command("docs")
def sdk_docs_command() -> None:
    click.echo(
        "\n".join(
            [
                "Aura SDK public imports:",
                "from packages.aura_core.sdk import ActionContext, EvidenceWriter, PolicyContext, ActionResultBuilder",
                "",
                "Injection:",
                "- Prefer type annotations for EvidenceWriter and PolicyContext.",
                "- Use parameter name action_context or annotation ActionContext for full context.",
                "- Legacy context/engine injection remains compatible but is not the recommended authoring surface.",
            ]
        )
    )


@aura.group("migration")
def migration_group() -> None:
    """SQLite migration commands."""


@migration_group.command("status")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def migration_status_command(base_path: str | None) -> None:
    scheduler = _load_runtime(base_path)
    legacy = scheduler.base_path / "logs" / "runs" / "run_store.sqlite3"
    click.echo(json.dumps(scheduler.observability.run_store.migration_status(legacy_db_path=legacy), ensure_ascii=False, indent=2))


@migration_group.command("plan")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def migration_plan_command(base_path: str | None) -> None:
    scheduler = _load_runtime(base_path)
    legacy = scheduler.base_path / "logs" / "runs" / "run_store.sqlite3"
    click.echo(json.dumps(scheduler.observability.run_store.migration_plan(legacy_db_path=legacy), ensure_ascii=False, indent=2))


@migration_group.command("apply")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def migration_apply_command(base_path: str | None) -> None:
    scheduler = _load_runtime(base_path)
    legacy = scheduler.base_path / "logs" / "runs" / "run_store.sqlite3"
    result = scheduler.observability.run_store.apply_migrations(legacy_db_path=legacy)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@aura.group("persistence")
def persistence_group() -> None:
    """Local SQLite retention, archive and export commands."""


@persistence_group.command("status")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def persistence_status_command(base_path: str | None) -> None:
    result = PersistenceLifecycleService(Path(base_path or Path.cwd())).status()
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@persistence_group.command("cleanup")
@click.option("--older-than", "older_than_days", type=int, required=True)
@click.option("--dry-run/--apply", default=True)
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def persistence_cleanup_command(older_than_days: int, dry_run: bool, base_path: str | None) -> None:
    result = PersistenceLifecycleService(Path(base_path or Path.cwd())).cleanup(
        older_than_days=older_than_days,
        dry_run=dry_run,
    )
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@persistence_group.command("archive")
@click.option("--older-than", "older_than_days", type=int, required=True)
@click.option("--output", required=True, type=click.Path(file_okay=True, dir_okay=True))
@click.option("--include-evidence/--no-include-evidence", default=False)
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def persistence_archive_command(
    older_than_days: int,
    output: str,
    include_evidence: bool,
    base_path: str | None,
) -> None:
    result = PersistenceLifecycleService(Path(base_path or Path.cwd())).archive(
        older_than_days=older_than_days,
        output=output,
        include_evidence=include_evidence,
    )
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@persistence_group.command("export")
@click.option("--format", "output_format", type=click.Choice(["jsonl", "sqlite"]), default="jsonl")
@click.option("--output", required=True, type=click.Path(file_okay=True, dir_okay=False))
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def persistence_export_command(output_format: str, output: str, base_path: str | None) -> None:
    result = PersistenceLifecycleService(Path(base_path or Path.cwd())).export(
        output=output,
        output_format=output_format,
    )
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@aura.group("diagnostics")
def diagnostics_group() -> None:
    """Diagnostics bundle commands."""


@diagnostics_group.command("collect")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--output", type=click.Path(file_okay=True, dir_okay=True), default=None)
@click.option("--include-evidence/--no-include-evidence", default=False)
def diagnostics_collect_command(base_path: str | None, output: str | None, include_evidence: bool) -> None:
    result = DiagnosticsCollector(Path(base_path or Path.cwd())).collect(output=output, include_evidence=include_evidence)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@diagnostics_group.command("recent")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--limit", type=int, default=20)
def diagnostics_recent_command(base_path: str | None, limit: int) -> None:
    rows = DiagnosticsCollector(Path(base_path or Path.cwd())).recent(limit=limit)
    click.echo(json.dumps({"diagnostics": rows}, ensure_ascii=False, indent=2))


@aura.group("compat")
def compat_group() -> None:
    """Compatibility matrix commands."""


@compat_group.command("matrix")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def compat_matrix_command(base_path: str | None, output_format: str) -> None:
    matrix = CompatibilityService(Path(base_path or Path.cwd())).matrix()
    if output_format == "json":
        click.echo(json.dumps(matrix, ensure_ascii=False, indent=2))
        return
    click.echo(f"Aura compat schema: {matrix.get('compat_schema_version')}")
    click.echo(f"Aura version: {matrix.get('aura_version')}")
    for name, contract in (matrix.get("contracts") or {}).items():
        click.echo(f"- {name}: {contract}")


@compat_group.command("check")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def compat_check_command(base_path: str | None, output_format: str) -> None:
    result = CompatibilityService(Path(base_path or Path.cwd())).check()
    _emit_result(result, output_format=output_format, success_text="Compatibility check passed.")


@compat_group.command("diff")
@click.option("--from-lock", "from_lock", required=True, type=click.Path(file_okay=True, dir_okay=False))
@click.option("--to-lock", "to_lock", required=True, type=click.Path(file_okay=True, dir_okay=False))
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def compat_diff_command(from_lock: str, to_lock: str, base_path: str | None) -> None:
    result = CompatibilityService(Path(base_path or Path.cwd())).diff_locks(from_lock, to_lock)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@compat_group.command("snapshot")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--update/--no-update", default=False)
def compat_snapshot_command(base_path: str | None, update: bool) -> None:
    result = CompatibilityService(Path(base_path or Path.cwd())).snapshot(update=update)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@compat_group.command("deprecations")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def compat_deprecations_command(base_path: str | None) -> None:
    result = CompatibilityService(Path(base_path or Path.cwd())).deprecations()
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@aura.group("fixture")
def fixture_group() -> None:
    """Golden fixture commands."""


@fixture_group.command("list")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--include-real/--fake-only", default=False)
def fixture_list_command(base_path: str | None, include_real: bool) -> None:
    rows = FixtureService(Path(base_path or Path.cwd())).list(include_real=include_real)
    click.echo(json.dumps({"fixtures": rows}, ensure_ascii=False, indent=2))


@fixture_group.command("run")
@click.argument("name")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--allow-side-effects/--no-allow-side-effects", default=False)
def fixture_run_command(name: str, base_path: str | None, allow_side_effects: bool) -> None:
    result = FixtureService(Path(base_path or Path.cwd())).run(name, allow_side_effects=allow_side_effects)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@fixture_group.command("verify")
@click.argument("name")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--update-snapshot/--no-update-snapshot", default=False)
@click.option("--allow-side-effects/--no-allow-side-effects", default=False)
def fixture_verify_command(name: str, base_path: str | None, update_snapshot: bool, allow_side_effects: bool) -> None:
    result = FixtureService(Path(base_path or Path.cwd())).verify(
        name,
        update_snapshot=update_snapshot,
        allow_side_effects=allow_side_effects,
    )
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@fixture_group.command("verify-all")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.option("--include-real/--fake-only", default=False)
@click.option("--allow-side-effects/--no-allow-side-effects", default=False)
def fixture_verify_all_command(base_path: str | None, output_format: str, include_real: bool, allow_side_effects: bool) -> None:
    result = FixtureService(Path(base_path or Path.cwd())).verify_all(
        include_real=include_real,
        allow_side_effects=allow_side_effects,
    )
    if output_format == "json":
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        click.echo(f"Fixture verify-all: {result['status']}")
        for item in result.get("fixtures", []):
            fixture = item.get("fixture", {})
            click.echo(f"- {fixture.get('id')}: {item.get('status')}")
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@fixture_group.command("doctor")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def fixture_doctor_command(base_path: str | None) -> None:
    result = FixtureService(Path(base_path or Path.cwd())).doctor()
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@fixture_group.command("update")
@click.argument("name")
@click.option("--snapshot-only/--full", default=True)
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def fixture_update_command(name: str, snapshot_only: bool, base_path: str | None) -> None:
    result = FixtureService(Path(base_path or Path.cwd())).update(name, snapshot_only=snapshot_only)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@aura.group("observability")
def observability_group() -> None:
    """Observability query commands."""


@observability_group.command("errors")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def observability_errors_command(base_path: str | None) -> None:
    result = ObservabilityQueryService(Path(base_path or Path.cwd())).error_summary()
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@observability_group.command("trace")
@click.argument("trace_id")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def observability_trace_command(trace_id: str, base_path: str | None) -> None:
    result = ObservabilityQueryService(Path(base_path or Path.cwd())).get_trace(trace_id)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("run") is None:
        raise click.exceptions.Exit(1)


@observability_group.command("backend-metrics")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def observability_backend_metrics_command(base_path: str | None) -> None:
    result = ObservabilityQueryService(Path(base_path or Path.cwd())).backend_metrics()
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@observability_group.command("service-metrics")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def observability_service_metrics_command(base_path: str | None) -> None:
    result = ObservabilityQueryService(Path(base_path or Path.cwd())).service_metrics()
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@observability_group.command("desktop-metrics")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def observability_desktop_metrics_command(base_path: str | None) -> None:
    result = ObservabilityQueryService(Path(base_path or Path.cwd())).desktop_metrics()
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@observability_group.command("resources")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--limit", type=int, default=200)
def observability_resources_command(base_path: str | None, limit: int) -> None:
    result = ObservabilityQueryService(Path(base_path or Path.cwd())).resources(limit=limit)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@observability_group.command("error-category")
@click.argument("category")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def observability_error_category_command(category: str, base_path: str | None) -> None:
    result = ObservabilityQueryService(Path(base_path or Path.cwd())).errors_by_category(category)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@aura.group("run")
def run_group() -> None:
    """Run inspection commands."""


@run_group.command("explain")
@click.argument("cid")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def run_explain_command(cid: str, base_path: str | None) -> None:
    result = ObservabilityQueryService(Path(base_path or Path.cwd())).run_explain(cid)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@aura.group("debug")
def debug_group() -> None:
    """Debug report and replay commands."""


@debug_group.command("report")
@click.option("--cid", required=True)
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--output", type=click.Path(file_okay=True, dir_okay=False), default=None)
def debug_report_command(cid: str, base_path: str | None, output: str | None) -> None:
    result = DebugService(Path(base_path or Path.cwd())).report(cid, output=output)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@debug_group.command("replay-step")
@click.option("--cid", required=True)
@click.option("--node", required=True)
@click.option("--backend", default="fake")
@click.option("--allow-side-effects/--no-allow-side-effects", default=False)
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--output", type=click.Path(file_okay=True, dir_okay=False), default=None)
def debug_replay_step_command(
    cid: str,
    node: str,
    backend: str,
    allow_side_effects: bool,
    base_path: str | None,
    output: str | None,
) -> None:
    result = DebugService(Path(base_path or Path.cwd())).replay_step(
        cid,
        node,
        backend=backend,
        allow_side_effects=allow_side_effects,
        output=output,
    )
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@aura.group("release")
def release_group() -> None:
    """Local release readiness commands."""


@release_group.command("check")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--skip-tests/--run-tests", default=False)
@click.option("--skip-gui-build/--run-gui-build", default=False)
def release_check_command(base_path: str | None, skip_tests: bool, skip_gui_build: bool) -> None:
    result = _release_check(Path(base_path or Path.cwd()), skip_tests=skip_tests, skip_gui_build=skip_gui_build)
    click.echo(json.dumps(result, ensure_ascii=True, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@release_group.command("pack")
@click.option("--version", required=True, help="Release version, for example 0.1.0.")
@click.option("--output", required=True, type=click.Path(file_okay=False, dir_okay=True))
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def release_pack_command(version: str, output: str, base_path: str | None) -> None:
    """Build Runtime, GUI and official base package release artifacts."""

    root = Path(base_path or Path.cwd())
    check = _release_check(root, skip_tests=False, skip_gui_build=False)
    if check.get("status") != "success":
        click.echo(json.dumps({"status": "error", "phase": "release_check", "release_check": check}, ensure_ascii=True, indent=2))
        raise click.exceptions.Exit(1)
    result = ReleasePackager(root).pack(version=version, output=output, release_check=check)
    click.echo(json.dumps(result, ensure_ascii=True, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


@aura.group("task")
def task_group() -> None:
    """Task authoring commands."""


@task_group.command("graph")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--plan", required=True)
@click.option("--task-ref", required=True)
@click.option("--format", "output_format", type=click.Choice(["mermaid", "json"]), default="mermaid")
def task_graph_command(base_path: str | None, plan: str, task_ref: str, output_format: str) -> None:
    click.echo(task_graph(base_path=base_path or Path.cwd(), plan=plan, task_ref=task_ref, output_format=output_format))


@task_group.command("explain")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--plan", required=True)
@click.option("--task-ref", required=True)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def task_explain_command(base_path: str | None, plan: str, task_ref: str, output_format: str) -> None:
    click.echo(task_explain(base_path=base_path or Path.cwd(), plan=plan, task_ref=task_ref, output_format=output_format))


@aura.group("template")
def template_group() -> None:
    """Template authoring commands."""


@template_group.command("render")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--plan", required=True)
@click.option("--task-ref", required=True)
@click.option("--context", "context_path", type=click.Path(file_okay=True, dir_okay=False), default=None)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def template_render_command(
    base_path: str | None,
    plan: str,
    task_ref: str,
    context_path: str | None,
    output_format: str,
) -> None:
    rendered = template_render(
        base_path=base_path or Path.cwd(),
        plan=plan,
        task_ref=task_ref,
        context_path=context_path,
        output_format=output_format,
    )
    click.echo(rendered)
    if output_format == "json" and json.loads(rendered).get("status") == "error":
        raise click.exceptions.Exit(1)


@aura.group("scaffold")
def scaffold_group() -> None:
    """Generate package and task scaffolds."""


@scaffold_group.command("package")
@click.argument("package_id")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
def scaffold_package_command(package_id: str, base_path: str | None) -> None:
    result = scaffold_package(base_path=base_path or Path.cwd(), package_id=package_id)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@scaffold_group.command("task")
@click.option("--base-path", type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option("--plan", required=True)
@click.option("--name", required=True)
def scaffold_task_command(base_path: str | None, plan: str, name: str) -> None:
    result = scaffold_task(base_path=base_path or Path.cwd(), plan=plan, name=name)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


def _emit_result(result: dict, *, output_format: str, success_text: str) -> None:
    if output_format == "json":
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    elif result.get("status") == "success":
        click.echo(success_text)
        for warning in result.get("warnings", []):
            click.echo(f"- WARN [{warning.get('code')}] {warning}")
    else:
        click.echo(f"Check failed with {len(result.get('errors', []))} error(s):")
        for error in result.get("errors", []):
            click.echo(f"- ERROR [{error.get('code')}] {error}")
        for warning in result.get("warnings", []):
            click.echo(f"- WARN [{warning.get('code')}] {warning}")
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


def _emit_dependency_result(
    result: dict,
    *,
    output_format: str,
    title: str,
    fail_on_missing: bool = True,
) -> None:
    if output_format == "json":
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        click.echo(f"{title}: {result.get('status')}")
        if result.get("package_id"):
            click.echo(f"- package: {result.get('package_id')}")
        if result.get("requirements_file"):
            click.echo(f"- requirements: {result.get('requirements_file')}")
        if result.get("will_install") is not None:
            click.echo(f"- will_install: {bool(result.get('will_install'))}")
        for row in result.get("dependencies", []):
            click.echo(
                f"- {row.get('status')} {row.get('requirement')} "
                f"(installed={row.get('installed_version') or '-'}) [{row.get('source')}]"
            )
        if result.get("pip_command"):
            click.echo("- command: " + " ".join(str(item) for item in result.get("pip_command")))
        for error in result.get("errors", []):
            click.echo(f"- ERROR [{error.get('code')}] {error}")
    if result.get("status") != "success" and (fail_on_missing or not _only_missing_dependency_errors(result.get("errors", []))):
        raise click.exceptions.Exit(1)


def _only_missing_dependency_errors(errors: list[dict] | None) -> bool:
    allowed = {"dependency_missing", "dependency_version_mismatch"}
    return bool(errors) and all(error.get("code") in allowed for error in errors)


def _release_check(base_path: Path, *, skip_tests: bool, skip_gui_build: bool) -> dict:
    checks = []
    from packages.aura_core.observability.logging.core_logger import logger

    console_handler = logger._get_handler("console")
    if console_handler:
        logger.logger.removeHandler(console_handler)
    try:
        core_smoke = _core_smoke(profile="framework-core", minimal_workspace=True)
        checks.append({"name": "core smoke", "status": core_smoke.get("status"), "detail": core_smoke})

        with contextlib.redirect_stdout(sys.stderr):
            validate_exit, validate_rendered = validate_workspace(
                base_path=base_path,
                output_format="json",
                strict=True,
            )
    finally:
        if console_handler and console_handler not in logger.logger.handlers:
            logger.logger.addHandler(console_handler)
    checks.append(
        {
            "name": "validate --strict",
            "status": "success" if validate_exit == 0 else "error",
            "detail": _loads_json(validate_rendered),
        }
    )

    package_doctor = WorkspaceLifecycleService(base_path).doctor()
    checks.append({"name": "package doctor", "status": package_doctor.get("status"), "detail": package_doctor})

    workspace_lifecycle = WorkspaceLifecycleService(base_path)
    dependency_service = PackageDependencyService(base_path)
    package_dependency_details = []
    package_dependency_status = "success"
    for ref in workspace_lifecycle.package_refs():
        if not ref.enabled:
            continue
        detail = dependency_service.doctor(ref.id)
        package_dependency_details.append(detail)
        if detail.get("status") != "success":
            package_dependency_status = "error"
    checks.append(
        {
            "name": "package dependency doctor",
            "status": package_dependency_status,
            "detail": {"packages": package_dependency_details},
        }
    )

    policy_doctor = _policy_doctor_payload(str(base_path))
    checks.append({"name": "policy doctor", "status": policy_doctor.get("status"), "detail": policy_doctor})

    sdk_doctor = _sdk_doctor_payload(str(base_path))
    checks.append({"name": "sdk doctor", "status": sdk_doctor.get("status"), "detail": sdk_doctor})

    scheduler_for_migration = _load_runtime(str(base_path))
    migration = scheduler_for_migration.observability.run_store.migration_status(
        legacy_db_path=scheduler_for_migration.base_path / "logs" / "runs" / "run_store.sqlite3"
    )
    checks.append({"name": "migration status", "status": "success" if not migration.get("pending") else "error", "detail": migration})

    compat = CompatibilityService(base_path).check()
    checks.append({"name": "compat check", "status": compat.get("status"), "detail": compat})

    fixtures = FixtureService(base_path).verify_all()
    checks.append({"name": "fixture verify-all", "status": fixtures.get("status"), "detail": fixtures})

    if skip_tests:
        checks.append({"name": "pytest -m not slow and not yolo", "status": "skipped"})
    else:
        checks.append(
            _subprocess_check(
                "pytest -m not slow and not yolo",
                [sys.executable, "-m", "pytest", "-m", "not slow and not yolo"],
                cwd=base_path,
            )
        )

    if skip_gui_build:
        checks.append({"name": "npm run build", "status": "skipped"})
    else:
        npm_cmd = "npm.cmd" if sys.platform.startswith("win") else "npm"
        checks.append(_subprocess_check("npm run build", [npm_cmd, "run", "build"], cwd=base_path / "aura_gui"))

    failed = [check for check in checks if check.get("status") not in {"success", "skipped"}]
    return {"status": "error" if failed else "success", "checks": checks, "failed": failed}


def _subprocess_check(name: str, command: list[str], *, cwd: Path) -> dict:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return {
        "name": name,
        "status": "success" if completed.returncode == 0 else "error",
        "returncode": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-4000:],
        "stderr_tail": (completed.stderr or "")[-4000:],
    }


def _policy_doctor_payload(base_path: str | None) -> dict:
    from packages.aura_core.observability.logging.core_logger import logger

    console_handler = logger._get_handler("console")
    if console_handler:
        logger.logger.removeHandler(console_handler)
    try:
        _load_runtime(base_path)
        from packages.aura_core.api import ACTION_REGISTRY, service_registry
    finally:
        if console_handler and console_handler not in logger.logger.handlers:
            logger.logger.addHandler(console_handler)

    errors = []
    warnings = []
    for action in ACTION_REGISTRY.get_all_action_definitions():
        if getattr(action, "stability", "stable") == "stable" and not getattr(action, "capabilities_declared", False):
            warnings.append({"code": "action_capability_inferred", "fqid": action.fqid})
    for service in service_registry.get_all_service_definitions():
        if getattr(service, "stability", "stable") == "stable" and not getattr(service, "capabilities_declared", False):
            warnings.append({"code": "service_capability_missing", "fqid": service.fqid})
    return {"status": "error" if errors else "success", "errors": errors, "warnings": warnings}


def _sdk_doctor_payload(base_path: str | None) -> dict:
    _load_runtime(base_path)
    from packages.aura_core.api import ACTION_REGISTRY
    from packages.aura_core.context.execution import ExecutionContext
    from packages.aura_core.sdk import ActionContext, EvidenceWriter, PolicyContext

    warnings = []
    for action in ACTION_REGISTRY.get_all_action_definitions():
        for param_name, param in action.signature.parameters.items():
            if param.annotation is ExecutionContext or param_name in {"context", "engine"}:
                warnings.append(
                    {
                        "code": "legacy_runtime_injection",
                        "action": action.fqid,
                        "parameter": param_name,
                    }
                )
            if param.annotation in {ActionContext, EvidenceWriter, PolicyContext} and param_name in {"policy", "evidence", "ctx"}:
                warnings.append(
                    {
                        "code": "ambiguous_sdk_parameter_name",
                        "action": action.fqid,
                        "parameter": param_name,
                    }
                )
    return {"status": "success", "errors": [], "warnings": warnings}


def _loads_json(raw: str) -> dict:
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {"value": value}
    except Exception:
        return {"raw": raw}


def _core_smoke(*, profile: str, minimal_workspace: bool) -> dict:
    blocked_imports = {
        "plans.aura_base": "framework-core must not import the official desktop capability package.",
        "paddleocr": "Move OCR usage behind plans/aura_base or an optional desktop profile.",
        "cv2": "OpenCV belongs to desktop/vision capability dependencies, not framework-core.",
        "win32api": "Win32 automation belongs to desktop backend implementations.",
        "win32gui": "Win32 automation belongs to desktop backend implementations.",
        "win32con": "Win32 automation belongs to desktop backend implementations.",
        "ultralytics": "YOLO belongs to optional desktop/vision capability dependencies.",
    }
    blocked_prefixes = tuple(blocked_imports)
    before = set(sys.modules)
    steps: list[dict] = []
    old_base = os.environ.get("AURA_BASE_PATH")
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        if minimal_workspace:
            temp_dir = tempfile.TemporaryDirectory(prefix="aura-core-smoke-", ignore_cleanup_errors=True)
            base_path = Path(temp_dir.name)
            (base_path / "plans").mkdir(parents=True, exist_ok=True)
            (base_path / "packages").mkdir(parents=True, exist_ok=True)
            (base_path / "workspace.yaml").write_text(
                "\n".join(
                    [
                        "workspace_schema_version: 1",
                        "workspace:",
                        "  name: core-smoke",
                        "  profile: framework-core",
                        "runtime:",
                        "  api_profile: local_only",
                        "  desktop_profile: none",
                        "  persistence: sqlite",
                        "packages: []",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            os.environ["AURA_BASE_PATH"] = str(base_path)
        else:
            base_path = Path.cwd()

        import packages.aura_core as aura_core  # noqa: F401

        steps.append({"name": "import aura_core", "status": "success"})

        from packages.aura_core.runtime.bootstrap import create_runtime, reset_runtime

        runtime = create_runtime(profile=profile)
        steps.append({"name": "create runtime", "status": "success", "runtime_profile": runtime.runtime_profile.name})

        plans = runtime.get_all_plans()
        steps.append({"name": "load empty/minimal workspace", "status": "success", "plan_count": len(plans)})

        from backend.api.app import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        response = TestClient(app).get("/api/v1/system/health")
        steps.append({"name": "api health", "status": "success" if response.status_code == 200 else "error", "status_code": response.status_code})
        reset_runtime()

        imported_after = set(sys.modules) - before
        blocked = sorted(name for name in imported_after if name in blocked_imports or name.startswith(blocked_prefixes))
        blocked_details = [
            {
                "module": name,
                "reason": _blocked_import_reason(name, blocked_imports),
                "dependency_hint": "Check requirements/framework-core.txt and defer desktop imports behind package loading.",
            }
            for name in blocked
        ]
        return {
            "status": "error" if blocked or any(step["status"] != "success" for step in steps) else "success",
            "profile": profile,
            "base_path": str(base_path),
            "steps": steps,
            "blocked_modules": blocked,
            "blocked_import_details": blocked_details,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "profile": profile,
            "base_path": os.environ.get("AURA_BASE_PATH") or str(Path.cwd()),
            "steps": steps,
            "blocked_modules": [],
            "blocked_import_details": [],
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    finally:
        from packages.aura_core.runtime.bootstrap import reset_runtime

        with contextlib.suppress(Exception):
            reset_runtime()
        if old_base is None:
            os.environ.pop("AURA_BASE_PATH", None)
        else:
            os.environ["AURA_BASE_PATH"] = old_base
        if temp_dir is not None:
            temp_dir.cleanup()


def _package_state_command(package_id: str, base_path: str | None, *, enabled: bool) -> None:
    service = WorkspaceLifecycleService(Path(base_path or Path.cwd()))
    result = service.enable_package(package_id) if enabled else service.disable_package(package_id)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "success":
        raise click.exceptions.Exit(1)


def _blocked_import_reason(name: str, reasons: dict[str, str]) -> str:
    for prefix, reason in reasons.items():
        if name == prefix or name.startswith(f"{prefix}."):
            return reason
    return "Blocked by framework-core import boundary."


def _load_runtime(base_path: str | None):
    if base_path:
        import os

        os.environ["AURA_BASE_PATH"] = str(Path(base_path).resolve())
    from packages.aura_core.runtime.bootstrap import create_runtime

    with contextlib.redirect_stdout(sys.stderr):
        return create_runtime(profile="api_full")


def _permission_row(obj, *, key: str) -> dict:
    return {
        key: getattr(obj, key),
        "capabilities": list(getattr(obj, "capabilities", []) or []),
        "capabilities_declared": bool(getattr(obj, "capabilities_declared", False)),
        "side_effect_level": getattr(obj, "side_effect_level", "read"),
        "requires_foreground": bool(getattr(obj, "requires_foreground", False)),
        "requires_admin": bool(getattr(obj, "requires_admin", False)),
        "stability": getattr(obj, "stability", "stable"),
    }


if __name__ == "__main__":
    aura()

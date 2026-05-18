# -*- coding: utf-8 -*-
"""Workspace validation helpers for the Aura CLI."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from packages.aura_core.packaging.core.task_loader import TaskLoader
from packages.aura_core.packaging.manifest.parser import ManifestParser
from packages.aura_core.scheduler.validation import InputValidator
from packages.aura_core.types import TaskRefResolver


OutputFormat = Literal["text", "json"]


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    plan_name: str | None
    file_path: str | None
    task_ref: str | None
    task_key: str | None
    step_id: str | None
    field_path: str | None
    error_code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_workspace(
    *,
    base_path: str | Path | None = None,
    plan: str | None = None,
    output_format: OutputFormat = "text",
    strict: bool = False,
    dry_run: bool = False,
    task_ref: str | None = None,
) -> tuple[int, str]:
    """Validate manifests and task YAML without executing actions."""

    root = Path(base_path or Path.cwd()).resolve()
    issues = _collect_workspace_issues(
        root=root,
        plan_filter=plan,
        strict=strict,
        dry_run=dry_run,
        task_ref=task_ref,
    )
    exit_code = 1 if issues else 0
    if output_format == "json":
        payload = {
            "status": "error" if issues else "success",
            "errors": [issue.to_dict() for issue in issues],
        }
        return exit_code, json.dumps(payload, ensure_ascii=False, indent=2)
    return exit_code, _format_text(issues)


def _collect_workspace_issues(
    *,
    root: Path,
    plan_filter: str | None,
    strict: bool,
    dry_run: bool,
    task_ref: str | None,
) -> list[ValidationIssue]:
    plans_dir = root / "plans"
    if not plans_dir.is_dir():
        return [
            ValidationIssue(
                plan_name=None,
                file_path=str(plans_dir),
                task_ref=None,
                task_key=None,
                step_id=None,
                field_path=None,
                error_code="plans_dir_missing",
                message=f"Plans directory not found: {plans_dir}",
            )
        ]

    plan_dirs = _iter_plan_dirs(plans_dir, plan_filter)
    if plan_filter and not plan_dirs:
        return [
            ValidationIssue(
                plan_name=plan_filter,
                file_path=str(plans_dir / plan_filter),
                task_ref=task_ref,
                task_key=None,
                step_id=None,
                field_path=None,
                error_code="plan_not_found",
                message=f"Plan '{plan_filter}' not found.",
            )
        ]

    issues: list[ValidationIssue] = []
    for plan_dir in plan_dirs:
        issues.extend(_validate_plan(plan_dir, strict=strict, dry_run=dry_run, task_ref=task_ref))
    return issues


def _iter_plan_dirs(plans_dir: Path, plan_filter: str | None) -> list[Path]:
    if plan_filter:
        candidate = plans_dir / plan_filter
        return [candidate] if candidate.is_dir() else []
    return sorted(
        item
        for item in plans_dir.iterdir()
        if item.is_dir() and not item.name.startswith(".") and item.name != "__pycache__"
    )


def _validate_plan(plan_dir: Path, *, strict: bool, dry_run: bool, task_ref: str | None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    plan_name = plan_dir.name
    manifest_path = plan_dir / "manifest.yaml"
    manifest = None

    if not manifest_path.is_file():
        return [
            ValidationIssue(
                plan_name=plan_name,
                file_path=str(manifest_path),
                task_ref=task_ref,
                task_key=None,
                step_id=None,
                field_path="manifest.yaml",
                error_code="manifest_missing",
                message=f"Plan '{plan_name}' is missing manifest.yaml.",
            )
        ]

    try:
        manifest = ManifestParser.parse(manifest_path)
        for message in ManifestParser.validate(manifest):
            issues.append(
                ValidationIssue(
                    plan_name=plan_name,
                    file_path=str(manifest_path),
                    task_ref=task_ref,
                    task_key=None,
                    step_id=None,
                    field_path="manifest.yaml",
                    error_code="manifest_validation_failed",
                    message=message,
                )
            )
    except Exception as exc:  # noqa: BLE001
        return [
            ValidationIssue(
                plan_name=plan_name,
                file_path=str(manifest_path),
                task_ref=task_ref,
                task_key=None,
                step_id=None,
                field_path="manifest.yaml",
                error_code="manifest_parse_failed",
                message=str(exc),
            )
        ]

    loader = TaskLoader(plan_name, plan_dir, manifest)
    if dry_run:
        if not task_ref:
            issues.append(
                ValidationIssue(
                    plan_name=plan_name,
                    file_path=str(plan_dir),
                    task_ref=None,
                    task_key=None,
                    step_id=None,
                    field_path="task_ref",
                    error_code="task_ref_required",
                    message="--dry-run requires --task-ref.",
                )
            )
            return issues
        issues.extend(_validate_dry_run_task(plan_dir, plan_name, manifest, loader, task_ref, strict=strict))
        return issues

    definitions = loader.get_all_task_definitions()
    issues.extend(_convert_loader_errors(plan_dir, loader.get_task_load_errors()))

    for task_key, task_def in sorted(definitions.items()):
        if not isinstance(task_def, dict):
            continue
        issues.extend(_validate_task_definition(plan_dir, plan_name, manifest, task_key, task_def, strict=strict))
    return issues


def _convert_loader_errors(plan_dir: Path, rows: Iterable[dict[str, Any]]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for row in rows:
        source_file = str(row.get("source_file") or "")
        refs = row.get("task_refs") or []
        issues.append(
            ValidationIssue(
                plan_name=row.get("plan_name"),
                file_path=str(plan_dir / "tasks" / source_file) if source_file else str(plan_dir),
                task_ref=refs[0] if refs else None,
                task_key=None,
                step_id=None,
                field_path=None,
                error_code=str(row.get("error_code") or "task_load_failed"),
                message=str(row.get("message") or "Task file failed to load."),
            )
        )
    return issues


def _validate_dry_run_task(
    plan_dir: Path,
    plan_name: str,
    manifest: Any,
    loader: TaskLoader,
    task_ref: str,
    *,
    strict: bool,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    try:
        resolved = TaskRefResolver.resolve(task_ref, default_package=plan_name, enforce_package=plan_name)
    except Exception as exc:
        return [
            ValidationIssue(
                plan_name=plan_name,
                file_path=str(plan_dir),
                task_ref=task_ref,
                task_key=None,
                step_id=None,
                field_path="task_ref",
                error_code="invalid_task_ref",
                message=str(exc),
            )
        ]

    task_def = loader.get_task_data(resolved.loader_path)
    if not isinstance(task_def, dict) or not task_def:
        return [
            ValidationIssue(
                plan_name=plan_name,
                file_path=str(plan_dir),
                task_ref=task_ref,
                task_key=resolved.task_key,
                step_id=None,
                field_path="task_ref",
                error_code="task_not_found",
                message=f"Task '{task_ref}' not found in plan '{plan_name}'.",
            )
        ]

    issues.extend(_validate_task_definition(plan_dir, plan_name, manifest, resolved.loader_path, task_def, strict=strict))
    inputs_meta = (task_def.get("meta") or {}).get("inputs", [])
    validator = InputValidator(None)  # type: ignore[arg-type]
    ok, error_or_inputs = validator.validate_inputs_against_meta(inputs_meta, {})
    if not ok:
        issues.append(
            ValidationIssue(
                plan_name=plan_name,
                file_path=str(plan_dir),
                task_ref=task_ref,
                task_key=resolved.task_key,
                step_id=None,
                field_path="meta.inputs",
                error_code="input_validation_failed",
                message=str(error_or_inputs),
            )
        )
    return issues


def _validate_task_definition(
    plan_dir: Path,
    plan_name: str,
    manifest: Any,
    task_key: str,
    task_def: dict[str, Any],
    *,
    strict: bool,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    task_ref = str(task_def.get("__task_ref__") or "")
    source_file = str(task_def.get("__task_source_file__") or "")
    file_path = str(plan_dir / "tasks" / source_file) if source_file else str(plan_dir)

    issues.extend(_validate_inputs(plan_name, file_path, task_ref, task_key, task_def))

    steps = task_def.get("steps") or {}
    if not isinstance(steps, dict):
        return issues

    for step_id, step_def in steps.items():
        if not isinstance(step_def, dict):
            continue
        action = step_def.get("action")
        if not isinstance(action, str) or not action.strip():
            issues.append(
                ValidationIssue(
                    plan_name=plan_name,
                    file_path=file_path,
                    task_ref=task_ref or None,
                    task_key=task_key,
                    step_id=str(step_id),
                    field_path=f"steps.{step_id}.action",
                    error_code="action_missing",
                    message="Step action must be a non-empty string.",
                )
            )
            continue
        issues.extend(
            _validate_action_reference(
                manifest=manifest,
                plan_name=plan_name,
                file_path=file_path,
                task_ref=task_ref,
                task_key=task_key,
                step_id=str(step_id),
                action=action.strip(),
                strict=strict,
            )
        )
        issues.extend(
            _validate_desktop_backend_selection(
                plan_name=plan_name,
                file_path=file_path,
                task_ref=task_ref,
                task_key=task_key,
                step_id=str(step_id),
                action=action.strip(),
                step_def=step_def,
            )
        )
    return issues


def _validate_desktop_backend_selection(
    *,
    plan_name: str,
    file_path: str,
    task_ref: str,
    task_key: str,
    step_id: str,
    action: str,
    step_def: dict[str, Any],
) -> list[ValidationIssue]:
    backend_spec = (step_def.get("with") or {}).get("backend") if isinstance(step_def.get("with"), dict) else None
    if backend_spec is None:
        backend_spec = (step_def.get("params") or {}).get("backend") if isinstance(step_def.get("params"), dict) else None
    if backend_spec is None:
        return []

    domain = _infer_desktop_domain(action)
    if domain is None:
        return []

    try:
        from plans.aura_base.src.desktop_runtime import get_desktop_registry

        selection = get_desktop_registry().select(domain, requested=backend_spec)
    except Exception as exc:  # noqa: BLE001
        return [
            ValidationIssue(
                plan_name=plan_name,
                file_path=file_path,
                task_ref=task_ref or None,
                task_key=task_key,
                step_id=step_id,
                field_path=f"steps.{step_id}.with.backend",
                error_code="desktop_registry_unavailable",
                message=f"Desktop capability registry is unavailable: {exc}",
            )
        ]
    if selection.selected_backend:
        return []
    return [
        ValidationIssue(
            plan_name=plan_name,
            file_path=file_path,
            task_ref=task_ref or None,
            task_key=task_key,
            step_id=step_id,
            field_path=f"steps.{step_id}.with.backend",
            error_code="desktop_backend_unavailable",
            message=f"No available {domain} backend for specification {backend_spec!r}.",
        )
    ]


def _infer_desktop_domain(action: str) -> str | None:
    lowered = action.lower()
    if any(token in lowered for token in ("click", "drag", "mouse", "scroll")):
        return "mouse"
    if any(token in lowered for token in ("key", "hotkey", "type_text")):
        return "keyboard"
    if any(token in lowered for token in ("image", "template", "pixel", "capture", "yolo")):
        return "capture"
    if "text" in lowered or "ocr" in lowered:
        return "ocr"
    if "window" in lowered:
        return "window"
    return None


def _validate_inputs(
    plan_name: str,
    file_path: str,
    task_ref: str,
    task_key: str,
    task_def: dict[str, Any],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    inputs = (task_def.get("meta") or {}).get("inputs", [])
    if inputs is None:
        return issues
    if not isinstance(inputs, list):
        return [
            ValidationIssue(
                plan_name=plan_name,
                file_path=file_path,
                task_ref=task_ref or None,
                task_key=task_key,
                step_id=None,
                field_path="meta.inputs",
                error_code="input_schema_invalid",
                message="Task meta.inputs must be a list.",
            )
        ]

    validator = InputValidator(None)  # type: ignore[arg-type]
    for index, item in enumerate(inputs):
        if not isinstance(item, dict):
            issues.append(
                ValidationIssue(
                    plan_name=plan_name,
                    file_path=file_path,
                    task_ref=task_ref or None,
                    task_key=task_key,
                    step_id=None,
                    field_path=f"meta.inputs[{index}]",
                    error_code="input_schema_invalid",
                    message="Input schema item must be an object.",
                )
            )
            continue
        field_path = f"meta.inputs[{index}]"
        try:
            normalized = validator.normalize_input_schema(item)
            if "default" in item:
                ok, _value, error = validator.validate_input_value(normalized, item.get("default"), item.get("name", field_path))
                if not ok:
                    raise ValueError(error)
        except Exception as exc:  # noqa: BLE001
            issues.append(
                ValidationIssue(
                    plan_name=plan_name,
                    file_path=file_path,
                    task_ref=task_ref or None,
                    task_key=task_key,
                    step_id=None,
                    field_path=field_path,
                    error_code="input_schema_invalid",
                    message=str(exc),
                )
            )
    return issues


def _validate_action_reference(
    *,
    manifest: Any,
    plan_name: str,
    file_path: str,
    task_ref: str,
    task_key: str,
    step_id: str,
    action: str,
    strict: bool,
) -> list[ValidationIssue]:
    if action == "aura.run_task":
        return []

    if "/" in action:
        parts = action.split("/")
        if len(parts) != 3:
            return [
                ValidationIssue(
                    plan_name=plan_name,
                    file_path=file_path,
                    task_ref=task_ref or None,
                    task_key=task_key,
                    step_id=step_id,
                    field_path=f"steps.{step_id}.action",
                    error_code="invalid_action_ref",
                    message="External action must use 'author/package/action' format.",
                )
            ]
        package_id = f"{parts[0]}/{parts[1]}"
        declared = any(dep_name.lstrip("@") == package_id for dep_name in getattr(manifest, "dependencies", {}).keys())
        if package_id != getattr(getattr(manifest, "package", None), "canonical_id", "").lstrip("@") and not declared:
            return [
                ValidationIssue(
                    plan_name=plan_name,
                    file_path=file_path,
                    task_ref=task_ref or None,
                    task_key=task_key,
                    step_id=step_id,
                    field_path=f"steps.{step_id}.action",
                    error_code="undeclared_action_dependency",
                    message=f"Action '{action}' references undeclared package '{package_id}'.",
                )
            ]
        return []

    if strict:
        exported = {item.name for item in getattr(getattr(manifest, "exports", None), "actions", [])}
        if action not in exported:
            return [
                ValidationIssue(
                    plan_name=plan_name,
                    file_path=file_path,
                    task_ref=task_ref or None,
                    task_key=task_key,
                    step_id=step_id,
                    field_path=f"steps.{step_id}.action",
                    error_code="action_not_exported",
                    message=f"Action '{action}' is not exported by plan '{plan_name}'.",
                )
            ]
    return []


def _format_text(issues: list[ValidationIssue]) -> str:
    if not issues:
        return "Aura validation passed."

    lines = [f"Aura validation failed with {len(issues)} error(s):"]
    for issue in issues:
        location = " / ".join(
            item
            for item in [
                issue.plan_name,
                issue.task_ref,
                issue.task_key,
                f"step:{issue.step_id}" if issue.step_id else None,
                issue.field_path,
            ]
            if item
        )
        lines.append(f"- [{issue.error_code}] {location or issue.file_path or 'workspace'}: {issue.message}")
        if issue.file_path:
            lines.append(f"  file: {issue.file_path}")
    return "\n".join(lines)

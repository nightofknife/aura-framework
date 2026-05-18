# -*- coding: utf-8 -*-
"""Compatibility matrix and local upgrade risk checks."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import yaml

from packages.aura_core.packaging.core.workspace_lifecycle import (
    LOCK_SCHEMA_VERSION,
    WORKSPACE_SCHEMA_VERSION,
    WorkspaceLifecycleService,
    normalize_package_id,
)


COMPAT_SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = {
    "manifest": [1],
    "task_dsl": [1],
    "workspace": [WORKSPACE_SCHEMA_VERSION],
    "lock": [LOCK_SCHEMA_VERSION],
    "capability": [1],
    "diagnostics": [1],
    "policy": [1],
    "evidence": [1],
    "desktop_result": [1],
    "run_store": [1],
}


class CompatibilityService:
    """Validates local contracts against ``compat/aura-compat.yaml``."""

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path).resolve()
        self.compat_path = self.base_path / "compat" / "aura-compat.yaml"
        self.workspace = WorkspaceLifecycleService(self.base_path)

    def matrix(self) -> dict[str, Any]:
        if self.compat_path.is_file():
            data = yaml.safe_load(self.compat_path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                return data
        return self._default_matrix()

    def check(self) -> dict[str, Any]:
        from packages.aura_core.observability.logging.core_logger import logger

        console_handler = logger._get_handler("console")
        if console_handler:
            logger.logger.removeHandler(console_handler)
        try:
            return self._check()
        finally:
            if console_handler and console_handler not in logger.logger.handlers:
                logger.logger.addHandler(console_handler)

    def _check(self) -> dict[str, Any]:
        matrix = self.matrix()
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        if matrix.get("compat_schema_version") != COMPAT_SCHEMA_VERSION:
            errors.append(
                {
                    "code": "compat_schema_unsupported",
                    "field": "compat_schema_version",
                    "message": f"Expected compat_schema_version={COMPAT_SCHEMA_VERSION}.",
                }
            )

        self._check_schema_version(
            errors,
            "workspace",
            self.workspace.load_workspace().get("workspace_schema_version", WORKSPACE_SCHEMA_VERSION),
            matrix,
        )
        if self.workspace.lock_path.is_file():
            self._check_schema_version(
                errors,
                "lock",
                self.workspace.load_lock().get("lock_schema_version", LOCK_SCHEMA_VERSION),
                matrix,
            )

        for ref in self.workspace.package_refs():
            package_dir = (self.base_path / ref.source).resolve()
            manifest_path = package_dir / "manifest.yaml"
            if not manifest_path.is_file():
                errors.append(
                    {
                        "code": "manifest_missing",
                        "package_id": ref.id,
                        "path": str(manifest_path),
                        "message": "Package manifest is missing.",
                    }
                )
                continue
            manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            manifest_version = int(manifest_data.get("manifest_version") or 1)
            self._check_schema_version(errors, "manifest", manifest_version, matrix, package_id=ref.id)
            errors.extend(self._check_task_dsl_versions(package_dir, ref.id, matrix))

        snapshot_result = self._check_stable_api_snapshot(matrix)
        errors.extend(snapshot_result["errors"])
        warnings.extend(snapshot_result["warnings"])
        contract_snapshot = self._check_contract_snapshot(matrix)
        errors.extend(contract_snapshot["errors"])
        warnings.extend(contract_snapshot["warnings"])
        deprecations = self.deprecations()
        errors.extend(deprecations.get("errors", []))
        warnings.extend(deprecations.get("warnings", []))

        package_doctor = self.workspace.doctor()
        for error in package_doctor.get("errors", []):
            errors.append({"code": "package_doctor_failed", "message": str(error), "detail": error})
        for warning in package_doctor.get("warnings", []):
            warnings.append({"code": "package_doctor_warning", "message": str(warning), "detail": warning})

        return {
            "status": "error" if errors else "success",
            "matrix_path": str(self.compat_path),
            "errors": errors,
            "warnings": warnings,
        }

    def diff_locks(self, from_lock: str | Path, to_lock: str | Path) -> dict[str, Any]:
        before = self._load_lock_file(Path(from_lock))
        after = self._load_lock_file(Path(to_lock))
        before_map = {normalize_package_id(item.get("id")): item for item in before.get("packages", []) or []}
        after_map = {normalize_package_id(item.get("id")): item for item in after.get("packages", []) or []}
        added = [after_map[key] for key in sorted(after_map.keys() - before_map.keys())]
        removed = [before_map[key] for key in sorted(before_map.keys() - after_map.keys())]
        changed = []
        for key in sorted(before_map.keys() & after_map.keys()):
            old = before_map[key]
            new = after_map[key]
            changes = {}
            for field in ("version", "content_hash", "enabled", "source_path"):
                if old.get(field) != new.get(field):
                    changes[field] = {"from": old.get(field), "to": new.get(field)}
            if changes:
                changed.append({"id": key, "changes": changes, "risk": self._risk_for_changes(changes)})
        status = "error" if any(item.get("risk") == "breaking" for item in changed) else "success"
        return {"status": status, "added": added, "removed": removed, "changed": changed}

    def snapshot(self, *, update: bool = False) -> dict[str, Any]:
        payload = self._build_contract_snapshot()
        target = self.base_path / "tests" / "snapshots" / "contracts-v1-stable.json"
        if update:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"status": "success", "path": str(target), "updated": update, "snapshot": payload}

    def deprecations(self) -> dict[str, Any]:
        matrix = self.matrix()
        deprecated = matrix.get("deprecated") or {}
        aura_version = str(matrix.get("aura_version") or "0.0.0")
        rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for kind, values in deprecated.items():
            for item in values or []:
                row = _normalize_deprecation(kind, item)
                row["aura_version"] = aura_version
                row["expired"] = bool(row.get("remove_after") and _version_lte(str(row["remove_after"]), aura_version))
                rows.append(row)
                if row["expired"] and not row.get("migration_note"):
                    errors.append(
                        {
                            "code": "deprecation_missing_migration_note",
                            "kind": kind,
                            "name": row.get("name"),
                            "remove_after": row.get("remove_after"),
                            "message": "Deprecated stable contract reached its removal window without migration_note.",
                        }
                    )
                elif row["expired"]:
                    warnings.append(
                        {
                            "code": "deprecation_removal_window_reached",
                            "kind": kind,
                            "name": row.get("name"),
                            "remove_after": row.get("remove_after"),
                        }
                    )
        return {
            "status": "error" if errors else "success",
            "aura_version": aura_version,
            "deprecations": rows,
            "errors": errors,
            "warnings": warnings,
        }

    def upgrade_plan(self, package_id: str) -> dict[str, Any]:
        target_id = normalize_package_id(package_id)
        packages = {row["id"]: row for row in self.workspace.list_packages()}
        row = packages.get(target_id)
        if row is None:
            return {
                "status": "error",
                "package_id": target_id,
                "risks": [{"code": "package_not_found", "message": f"Package '{target_id}' is not in workspace."}],
            }
        risks = []
        if row.get("validation_status") != "ok":
            risks.append({"code": "package_validation_failed", "errors": row.get("validation_errors") or []})
        if row.get("lock_drift"):
            risks.append({"code": "lock_drift", "message": "Package content differs from packages.lock.yaml."})
        compat = self.check()
        for error in compat.get("errors", []):
            if error.get("package_id") == target_id:
                risks.append({"code": "compat_error", "detail": error})
        return {
            "status": "error" if risks else "success",
            "package_id": target_id,
            "package": row,
            "will_modify_workspace": False,
            "risks": risks,
            "recommendations": _upgrade_recommendations(risks),
        }

    def _check_schema_version(
        self,
        errors: list[dict[str, Any]],
        contract: str,
        version: Any,
        matrix: dict[str, Any],
        *,
        package_id: str | None = None,
    ) -> None:
        supported = (
            matrix.get("contracts", {})
            .get(contract, {})
            .get("supported_versions", SUPPORTED_SCHEMA_VERSIONS.get(contract, [1]))
        )
        try:
            normalized = int(version)
        except Exception:
            normalized = version
        if normalized not in supported:
            errors.append(
                {
                    "code": f"{contract}_schema_unsupported",
                    "contract": contract,
                    "version": version,
                    "supported_versions": supported,
                    "package_id": package_id,
                    "message": f"{contract} schema version {version!r} is not supported.",
                }
            )

    def _check_task_dsl_versions(
        self,
        package_dir: Path,
        package_id: str,
        matrix: dict[str, Any],
    ) -> list[dict[str, Any]]:
        errors = []
        for task_file in sorted((package_dir / "tasks").rglob("*.yaml")):
            data = yaml.safe_load(task_file.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                errors.append(
                    {
                        "code": "task_dsl_invalid",
                        "package_id": package_id,
                        "path": str(task_file),
                        "message": "Task YAML root must be a mapping.",
                    }
                )
                continue
            version = int(data.get("task_dsl_version") or data.get("dsl_version") or 1)
            local_errors: list[dict[str, Any]] = []
            self._check_schema_version(local_errors, "task_dsl", version, matrix, package_id=package_id)
            for error in local_errors:
                error["path"] = str(task_file)
            errors.extend(local_errors)
        return errors

    def _check_stable_api_snapshot(self, matrix: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        snapshot_rel = matrix.get("contracts", {}).get("api", {}).get("stable_snapshot")
        if not snapshot_rel:
            warnings.append({"code": "api_snapshot_not_configured", "message": "No stable API snapshot configured."})
            return {"errors": errors, "warnings": warnings}
        snapshot_path = self.base_path / str(snapshot_rel)
        if not snapshot_path.is_file():
            errors.append({"code": "api_snapshot_missing", "path": str(snapshot_path)})
            return {"errors": errors, "warnings": warnings}
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        expected = snapshot.get("paths", {}) if isinstance(snapshot, dict) else {}
        actual = self._current_openapi_paths()
        for path, methods in expected.items():
            if path not in actual:
                errors.append({"code": "stable_api_path_missing", "path": path})
                continue
            for method in methods:
                if method.lower() not in actual[path]:
                    errors.append({"code": "stable_api_method_missing", "path": path, "method": method.lower()})
        return {"errors": errors, "warnings": warnings}

    def _check_contract_snapshot(self, matrix: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        snapshot_rel = matrix.get("contracts", {}).get("contracts_snapshot")
        if not snapshot_rel:
            warnings.append({"code": "contract_snapshot_not_configured", "message": "No stable contract snapshot configured."})
            return {"errors": errors, "warnings": warnings}
        snapshot_path = self.base_path / str(snapshot_rel)
        if not snapshot_path.is_file():
            errors.append({"code": "contract_snapshot_missing", "path": str(snapshot_path)})
            return {"errors": errors, "warnings": warnings}
        expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
        actual = self._build_contract_snapshot()
        enabled_package_ids = self.workspace.enabled_package_ids()
        for section in ("actions", "services"):
            expected_rows = expected.get(section, {}) if isinstance(expected, dict) else {}
            actual_rows = actual.get(section, {})
            for fqid, expected_row in expected_rows.items():
                package_id = _package_id_from_fqid(fqid)
                if package_id and package_id not in enabled_package_ids:
                    continue
                if fqid not in actual_rows:
                    errors.append({"code": f"stable_{section[:-1]}_missing", "fqid": fqid})
                    continue
                removed = sorted(set(expected_row.get("parameters") or []) - set(actual_rows[fqid].get("parameters") or []))
                if removed:
                    errors.append({"code": f"stable_{section[:-1]}_parameter_removed", "fqid": fqid, "parameters": removed})
        return {"errors": errors, "warnings": warnings}

    def _build_contract_snapshot(self) -> dict[str, Any]:
        from packages.aura_core.observability.logging.core_logger import logger

        console_handler = logger._get_handler("console")
        if console_handler:
            logger.logger.removeHandler(console_handler)
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                from packages.aura_core.runtime.bootstrap import create_runtime, reset_runtime
                from packages.aura_core.api import ACTION_REGISTRY, service_registry

                create_runtime(profile="api_full")
                actions = {
                    action.fqid: {
                        "name": action.name,
                        "parameters": [
                            name
                            for name in action.signature.parameters
                            if name not in (action.service_deps or {}) and name not in {"context", "engine"}
                        ],
                        "capabilities": list(getattr(action, "capabilities", []) or []),
                        "stability": getattr(action, "stability", "stable"),
                    }
                    for action in ACTION_REGISTRY.get_all_action_definitions()
                    if getattr(action, "stability", "stable") == "stable"
                }
                services = {
                    service.fqid: {
                        "alias": service.alias,
                        "capabilities": list(getattr(service, "capabilities", []) or []),
                        "stability": getattr(service, "stability", "stable"),
                    }
                    for service in service_registry.get_all_service_definitions()
                    if getattr(service, "stability", "stable") == "stable"
                }
                reset_runtime()
        finally:
            if console_handler and console_handler not in logger.logger.handlers:
                logger.logger.addHandler(console_handler)
        return {
            "snapshot_schema_version": 1,
            "actions": actions,
            "services": services,
            "schemas": {
                "task_dsl_schema": "docs/schemas/task-schema.json",
                "manifest_schema": "packages/aura_core/packaging/manifest/schema.py",
                "desktop_result_schema": "plans/aura_base/src/desktop_runtime/models.py",
                "evidence_schema": "logs/evidence/{cid}/manifest.json",
            },
        }

    @staticmethod
    def _current_openapi_paths() -> dict[str, set[str]]:
        from packages.aura_core.observability.logging.core_logger import logger

        console_handler = logger._get_handler("console")
        if console_handler:
            logger.logger.removeHandler(console_handler)
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                from backend.api.app import create_app

                openapi = create_app().openapi()
        finally:
            if console_handler and console_handler not in logger.logger.handlers:
                logger.logger.addHandler(console_handler)
        return {path: {method.lower() for method in methods.keys()} for path, methods in openapi.get("paths", {}).items()}

    @staticmethod
    def _load_lock_file(path: Path) -> dict[str, Any]:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Lock file must contain a mapping: {path}")
        return data

    @staticmethod
    def _risk_for_changes(changes: dict[str, Any]) -> str:
        if "content_hash" in changes and "version" not in changes:
            return "review"
        if "enabled" in changes:
            return "review"
        return "compatible"

    def _default_matrix(self) -> dict[str, Any]:
        return {
            "compat_schema_version": COMPAT_SCHEMA_VERSION,
            "aura_version": "0.1.0",
            "contracts": {
                "api": {"version": "v1", "stable_snapshot": "tests/snapshots/api-v1-stable.json"},
                "contracts_snapshot": "tests/snapshots/contracts-v1-stable.json",
                "manifest": {"supported_versions": [1]},
                "task_dsl": {"supported_versions": [1]},
                "workspace": {"supported_versions": [WORKSPACE_SCHEMA_VERSION]},
                "lock": {"supported_versions": [LOCK_SCHEMA_VERSION]},
                "capability": {"supported_versions": [1]},
                "diagnostics": {"supported_versions": [1]},
                "policy": {"supported_versions": [1]},
                "evidence": {"supported_versions": [1]},
                "desktop_result": {"supported_versions": [1]},
                "run_store": {"supported_versions": [1]},
            },
            "deprecated": {"actions": [], "services": [], "api_fields": []},
            "breaking_changes": [],
        }


def _upgrade_recommendations(risks: list[dict[str, Any]]) -> list[str]:
    if not risks:
        return ["Package can be upgraded with the current local compatibility policy."]
    recommendations = []
    codes = {risk.get("code") for risk in risks}
    if "lock_drift" in codes:
        recommendations.append("Run `python cli.py package lock` after reviewing package content changes.")
    if "package_validation_failed" in codes:
        recommendations.append("Fix manifest, exports and task YAML validation errors before upgrading.")
    if "compat_error" in codes:
        recommendations.append("Review schema/API compatibility errors and update the compat matrix only after migration.")
    return recommendations or ["Review listed risks before enabling the package."]


def _normalize_deprecation(kind: str, item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return {"kind": kind, **item}
    return {"kind": kind, "name": str(item)}


def _package_id_from_fqid(fqid: str) -> str | None:
    parts = str(fqid or "").split("/")
    if len(parts) >= 3 and parts[0] in {"plans", "packages"}:
        return f"{parts[0]}/{parts[1]}"
    return None


def _version_lte(left: str, right: str) -> bool:
    return _version_tuple(left) <= _version_tuple(right)


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for token in str(value or "0").replace("-", ".").split("."):
        if token.isdigit():
            parts.append(int(token))
        else:
            digits = "".join(ch for ch in token if ch.isdigit())
            parts.append(int(digits or 0))
    return tuple(parts or [0])

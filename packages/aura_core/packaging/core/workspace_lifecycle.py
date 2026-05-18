# -*- coding: utf-8 -*-
"""Workspace package lifecycle and lockfile management."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from packages.aura_core.packaging.core.task_loader import TaskLoader
from packages.aura_core.packaging.manifest.parser import ManifestParser
from packages.aura_core.utils.safe_paths import (
    UnsafePathError,
    ensure_path_under,
    iter_package_files,
    safe_extract_zip,
    safe_package_leaf,
    safe_remove_tree,
    safe_resolve_under,
    scan_symlinks,
    validate_package_id,
    validate_safe_relative_path,
)


WORKSPACE_SCHEMA_VERSION = 1
LOCK_SCHEMA_VERSION = 1


@dataclass(slots=True)
class WorkspacePackageRef:
    id: str
    enabled: bool
    source: str


class WorkspaceLifecycleService:
    """Manages local workspace profile, package state and package lock."""

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path).resolve()
        self.workspace_path = self.base_path / "workspace.yaml"
        self.lock_path = self.base_path / "packages.lock.yaml"
        self.packages_dir = self.base_path / "packages"
        self.plans_dir = self.base_path / "plans"

    def workspace_exists(self) -> bool:
        return self.workspace_path.is_file()

    def load_workspace(self) -> dict[str, Any]:
        if self.workspace_path.is_file():
            data = yaml.safe_load(self.workspace_path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                raise ValueError("workspace.yaml must contain a mapping.")
            return data
        return self._default_workspace_from_disk()

    def save_workspace(self, data: dict[str, Any]) -> None:
        self.workspace_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def load_lock(self) -> dict[str, Any]:
        if not self.lock_path.is_file():
            return {"lock_schema_version": LOCK_SCHEMA_VERSION, "packages": []}
        data = yaml.safe_load(self.lock_path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {"lock_schema_version": LOCK_SCHEMA_VERSION, "packages": []}

    def package_refs(self) -> list[WorkspacePackageRef]:
        refs = []
        for item in self.load_workspace().get("packages", []) or []:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "")
            package_id = normalize_package_id(item.get("id") or _id_from_source(source))
            refs.append(WorkspacePackageRef(id=package_id, enabled=bool(item.get("enabled", True)), source=source))
        return refs

    def enabled_package_ids(self) -> set[str]:
        return {ref.id for ref in self.package_refs() if ref.enabled}

    def enabled_source_paths(self) -> set[Path]:
        paths = set()
        for ref in self.package_refs():
            if ref.enabled and ref.source:
                paths.add((self.base_path / ref.source).resolve())
        return paths

    def list_packages(self) -> list[dict[str, Any]]:
        lock_entries = {normalize_package_id(item.get("id")): item for item in self.load_lock().get("packages", []) or []}
        rows = []
        for ref in self.package_refs():
            source_path = (self.base_path / ref.source).resolve()
            manifest_path = source_path / "manifest.yaml"
            manifest = None
            validation = []
            if manifest_path.is_file():
                try:
                    manifest = ManifestParser.parse(manifest_path)
                    validation = self.validate_package(str(source_path))["errors"]
                except Exception as exc:  # noqa: BLE001
                    validation = [str(exc)]
            else:
                validation = [f"manifest.yaml not found: {manifest_path}"]
            try:
                current_hash = _content_hash(source_path) if source_path.exists() else None
            except UnsafePathError as exc:
                current_hash = None
                validation.append({"code": "package_symlink_disallowed", "path": str(source_path), "message": str(exc)})
            locked = lock_entries.get(ref.id)
            rows.append(
                {
                    "id": ref.id,
                    "name": getattr(getattr(manifest, "package", None), "name", ref.id),
                    "version": getattr(getattr(manifest, "package", None), "version", "0.0.0"),
                    "enabled": ref.enabled,
                    "source": ref.source,
                    "source_path": str(source_path),
                    "validation_status": "ok" if not validation else "error",
                    "validation_errors": validation,
                    "lock_drift": bool(locked and current_hash and locked.get("content_hash") != current_hash),
                }
            )
        return rows

    def validate_package(self, package_or_path: str | None = None) -> dict[str, Any]:
        targets = self._resolve_validate_targets(package_or_path)
        errors: list[dict[str, Any]] = []
        for target in targets:
            errors.extend(self._validate_package_dir(target))
        return {"status": "error" if errors else "success", "errors": errors}

    def install_package(self, source: str | Path, *, link: bool = False) -> dict[str, Any]:
        source_path = Path(source).resolve()
        if not source_path.exists():
            return {"status": "error", "message": f"Package source not found: {source_path}"}
        package_dir = self._normalize_install_source(source_path)
        manifest = ManifestParser.parse(package_dir / "manifest.yaml")
        package_id = normalize_package_id(manifest.package.canonical_id)
        if safe_package_leaf(package_id) == "aura_core":
            return {
                "status": "error",
                "error_code": "reserved_package_target",
                "message": "packages/aura_core is reserved for the Aura core runtime.",
            }
        target_dir = ensure_path_under(
            self.packages_dir,
            self.packages_dir / safe_package_leaf(package_id),
            label="package install target",
        )
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        if target_dir.exists() or target_dir.is_symlink():
            if target_dir.resolve() != package_dir.resolve():
                safe_remove_tree(self.packages_dir, target_dir, label="package install target")
        if not target_dir.exists():
            if link:
                target_dir.symlink_to(package_dir, target_is_directory=True)
            else:
                shutil.copytree(package_dir, target_dir)
        self._upsert_package_ref(package_id, source=_relative_path(target_dir, self.base_path), enabled=True)
        lock = self.write_lock()
        return {"status": "success", "package_id": package_id, "target": str(target_dir), "lock": lock}

    def enable_package(self, package_id: str) -> dict[str, Any]:
        return self._set_enabled(package_id, True)

    def disable_package(self, package_id: str) -> dict[str, Any]:
        return self._set_enabled(package_id, False)

    def remove_package(self, package_id: str, *, keep_files: bool = False) -> dict[str, Any]:
        target_id = normalize_package_id(package_id)
        workspace = self._ensure_workspace_file()
        removed = None
        remaining = []
        for item in workspace.get("packages", []) or []:
            if normalize_package_id(item.get("id")) == target_id:
                removed = item
            else:
                remaining.append(item)
        if removed is None:
            return {"status": "error", "message": f"Package '{target_id}' not found in workspace."}
        workspace["packages"] = remaining
        self.save_workspace(workspace)
        deleted_path = None
        source = str(removed.get("source") or "")
        if not keep_files and source:
            try:
                source_path = self._safe_package_source_path(source, roots=[self.packages_dir], label="package remove source")
            except UnsafePathError:
                source_path = None
            if source_path and source_path.exists():
                safe_remove_tree(self.packages_dir, source_path, label="package remove source")
                deleted_path = str(source_path)
        self.write_lock()
        return {"status": "success", "package_id": target_id, "deleted_path": deleted_path}

    def write_lock(self) -> dict[str, Any]:
        packages = []
        for ref in self.package_refs():
            source_path = (self.base_path / ref.source).resolve()
            manifest_path = source_path / "manifest.yaml"
            if not manifest_path.is_file():
                packages.append(
                    {
                        "id": ref.id,
                        "name": ref.id,
                        "version": "0.0.0",
                        "enabled": ref.enabled,
                        "source_type": "missing",
                        "source_path": ref.source,
                        "manifest_path": _relative_path(manifest_path, self.base_path),
                        "content_hash": None,
                        "dependencies": [],
                    }
                )
                continue
            manifest = ManifestParser.parse(manifest_path)
            packages.append(
                {
                    "id": normalize_package_id(manifest.package.canonical_id),
                    "name": manifest.package.name,
                    "version": manifest.package.version,
                    "enabled": ref.enabled,
                    "source_type": "workspace" if source_path.is_relative_to(self.base_path) else "external",
                    "source_path": _relative_path(source_path, self.base_path),
                    "manifest_path": _relative_path(manifest_path, self.base_path),
                    "content_hash": _content_hash(source_path),
                    "dependencies": [normalize_package_id(dep.name) for dep in manifest.dependencies.values()],
                }
            )
        lock = {
            "lock_schema_version": LOCK_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "packages": packages,
        }
        self.lock_path.write_text(yaml.safe_dump(lock, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return lock

    def doctor(self) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        workspace = self.load_workspace()
        if workspace.get("workspace_schema_version", WORKSPACE_SCHEMA_VERSION) != WORKSPACE_SCHEMA_VERSION:
            errors.append({"code": "workspace_schema_unsupported", "message": "workspace.yaml schema version is unsupported."})
        seen: set[str] = set()
        enabled = {ref.id for ref in self.package_refs() if ref.enabled}
        for row in self.list_packages():
            if row["id"] in seen:
                errors.append({"code": "duplicate_package_id", "package_id": row["id"]})
            seen.add(row["id"])
            for item in row["validation_errors"]:
                errors.append({"code": "package_validation_failed", "package_id": row["id"], "message": str(item)})
            manifest_path = Path(row["source_path"]) / "manifest.yaml"
            if manifest_path.is_file():
                manifest = ManifestParser.parse(manifest_path)
                for dep in manifest.dependencies.values():
                    dep_id = normalize_package_id(dep.name)
                    if not dep.optional and dep_id not in enabled:
                        errors.append({"code": "missing_enabled_dependency", "package_id": row["id"], "dependency": dep_id})
            if row["lock_drift"]:
                warnings.append({"code": "lock_drift", "package_id": row["id"]})
        status = "error" if errors else "success"
        return {"status": status, "errors": errors, "warnings": warnings}

    def pack_package(self, package_id: str, *, output: str | Path | None = None) -> dict[str, Any]:
        target_id = normalize_package_id(package_id)
        ref = next((item for item in self.package_refs() if item.id == target_id), None)
        if ref is None:
            return {"status": "error", "message": f"Package '{target_id}' not found in workspace."}
        package_dir = (self.base_path / ref.source).resolve()
        manifest_path = package_dir / "manifest.yaml"
        if not manifest_path.is_file():
            return {"status": "error", "message": f"manifest.yaml not found: {manifest_path}"}
        manifest = ManifestParser.parse(manifest_path)
        target = Path(output).resolve() if output else self.base_path / "dist" / "packages" / f"{safe_package_leaf(target_id)}-{manifest.package.version}.aura"
        target.parent.mkdir(parents=True, exist_ok=True)
        symlinks = scan_symlinks(package_dir)
        if symlinks:
            return {
                "status": "error",
                "package_id": target_id,
                "error_code": "package_symlink_disallowed",
                "errors": symlinks,
            }
        rebase_prefix = _derive_package_import_prefix(package_dir)
        checksums = _file_checksums(package_dir, rebase_prefix=rebase_prefix)
        lock_snapshot = {
            "lock_schema_version": LOCK_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "packages": [
                {
                    "id": target_id,
                    "name": manifest.package.name,
                    "version": manifest.package.version,
                    "content_hash": _content_hash(package_dir, rebase_prefix=rebase_prefix),
                    "source_path": _relative_path(package_dir, self.base_path),
                }
            ],
        }
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in iter_package_files(package_dir, skip_parts={".git", "__pycache__", ".pytest_cache", "node_modules"}):
                rel = file_path.relative_to(package_dir).as_posix()
                payload = _stable_package_file_bytes(file_path, package_dir, rebase_prefix=rebase_prefix)
                archive.writestr(f"package/{rel}", payload)
                if rel == "manifest.yaml":
                    archive.writestr("manifest.yaml", payload)
            archive.writestr("checksums.sha256", "\n".join(f"{digest}  {path}" for path, digest in checksums.items()) + "\n")
            archive.writestr("package-lock.snapshot.yaml", yaml.safe_dump(lock_snapshot, sort_keys=False, allow_unicode=True))
            archive.writestr("compat-report.json", json.dumps(self.compat_package(target_id), ensure_ascii=False, indent=2))
            fixtures_dir = package_dir / "fixtures"
            if fixtures_dir.is_dir():
                for file_path in iter_package_files(fixtures_dir, skip_parts={".git", "__pycache__", ".pytest_cache", "node_modules"}):
                    archive.write(file_path, f"fixtures/{file_path.relative_to(fixtures_dir).as_posix()}")
            migrations_dir = package_dir / "migrations"
            if migrations_dir.is_dir():
                for file_path in iter_package_files(migrations_dir, skip_parts={".git", "__pycache__", ".pytest_cache", "node_modules"}):
                    archive.write(file_path, f"migrations/{file_path.relative_to(migrations_dir).as_posix()}")
        return {"status": "success", "package_id": target_id, "path": str(target), "content_hash": _content_hash(package_dir, rebase_prefix=rebase_prefix)}

    def diff_packages(self, old_package: str | Path, new_package: str | Path) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="aura-package-diff-") as tmp:
            old_dir = self._normalize_package_for_read(Path(old_package).resolve(), Path(tmp) / "old")
            new_dir = self._normalize_package_for_read(Path(new_package).resolve(), Path(tmp) / "new")
            old_summary = _package_summary(old_dir)
            new_summary = _package_summary(new_dir)
            changes: list[dict[str, Any]] = []
            for field in ("id", "name", "version", "content_hash"):
                if old_summary.get(field) != new_summary.get(field):
                    changes.append({"field": field, "from": old_summary.get(field), "to": new_summary.get(field)})
            for field in ("actions", "services"):
                before = set(old_summary.get(field) or [])
                after = set(new_summary.get(field) or [])
                if before != after:
                    changes.append({"field": field, "added": sorted(after - before), "removed": sorted(before - after)})
            return {
                "status": "success",
                "old": old_summary,
                "new": new_summary,
                "changes": changes,
                "risk": "review" if changes else "none",
            }

    def compat_package(self, package_id: str) -> dict[str, Any]:
        target_id = normalize_package_id(package_id)
        validation = self.validate_package(target_id)
        row = next((item for item in self.list_packages() if item["id"] == target_id), None)
        risks = []
        if validation.get("status") != "success":
            risks.extend(validation.get("errors") or [])
        if row and row.get("lock_drift"):
            risks.append({"code": "lock_drift", "message": "Package content differs from packages.lock.yaml."})
        if row is None:
            risks.append({"code": "package_not_found", "message": f"Package '{target_id}' not found."})
        return {"status": "error" if risks else "success", "package_id": target_id, "package": row, "risks": risks}

    def upgrade_plan(self, package_id: str) -> dict[str, Any]:
        target_id = normalize_package_id(package_id)
        compat = self.compat_package(target_id)
        return {
            "status": compat["status"],
            "package_id": target_id,
            "current": compat.get("package"),
            "risks": compat.get("risks") or [],
            "will_modify_workspace": False,
            "recommendations": _package_upgrade_recommendations(compat.get("risks") or []),
        }

    def upgrade_package(
        self,
        package_id: str,
        source: str | Path,
        *,
        dry_run: bool = True,
        apply: bool = False,
    ) -> dict[str, Any]:
        target_id = normalize_package_id(package_id)
        source_dir = self._normalize_package_for_read(Path(source).resolve(), self.base_path / ".aura_tmp" / "upgrade-source")
        source_validation = self._validate_package_dir(source_dir)
        current_ref = next((ref for ref in self.package_refs() if ref.id == target_id), None)
        if current_ref is None:
            return {
                "status": "error",
                "package_id": target_id,
                "will_modify_workspace": False,
                "risks": [{"code": "package_not_found", "message": f"Package '{target_id}' not found in workspace."}],
            }
        current_dir = self._safe_package_source_path(current_ref.source, roots=[self.plans_dir, self.packages_dir], label="package upgrade target")
        diff = self.diff_packages(current_dir, source_dir) if current_dir.exists() else {"status": "success", "changes": []}
        risks = list(source_validation)
        if source_validation:
            risks.append({"code": "source_validation_failed", "message": "Upgrade source failed package validation."})
        plan = {
            "status": "error" if risks else "success",
            "package_id": target_id,
            "source": str(source_dir),
            "target": str(current_dir),
            "will_modify_workspace": bool(apply and not dry_run),
            "dry_run": bool(dry_run or not apply),
            "diff": diff,
            "risks": risks,
            "steps": [
                "validate source package",
                "compare package contracts",
                "verify fake fixtures",
                "backup current package",
                "replace package files",
                "write packages.lock.yaml",
                "run runtime reload plan/apply",
            ],
        }
        if dry_run or not apply or risks:
            return plan

        fixture_gate = self._fixture_gate()
        if fixture_gate.get("status") != "success":
            return {"status": "error", **plan, "message": "Fixture gate failed.", "fixture_gate": fixture_gate}

        backup_root = self.base_path / ".aura_tmp" / "package-backups" / target_id.replace("/", "__") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_dir = backup_root / "package"
        operation = {
            "package_id": target_id,
            "source": str(source_dir),
            "target": str(current_dir),
            "backup": str(backup_dir),
            "backup_root": str(backup_root),
        }
        try:
            backup_dir.parent.mkdir(parents=True, exist_ok=True)
            if current_dir.exists():
                shutil.copytree(current_dir, backup_dir, symlinks=True)
                self._safe_remove_workspace_package_path(current_dir, label="package upgrade target")
            if self.workspace_path.is_file():
                shutil.copy2(self.workspace_path, backup_root / "workspace.yaml")
            if self.lock_path.is_file():
                shutil.copy2(self.lock_path, backup_root / "packages.lock.yaml")
            current_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_dir, current_dir)
            lock = self.write_lock()
            reload_gate = self._run_reload_gate(target_id)
            if reload_gate.get("status") != "success":
                raise RuntimeError(f"Runtime reload gate failed: {reload_gate}")
            operation.update({"status": "success", "lock": lock, "reload_gate": reload_gate, "fixture_gate": fixture_gate})
            self._record_upgrade_operation(operation)
            return {"status": "success", **plan, "backup": str(backup_dir), "lock": lock, "reload_gate": reload_gate, "fixture_gate": fixture_gate}
        except Exception as exc:  # noqa: BLE001
            rollback_status = "not_needed"
            try:
                if current_dir.exists() or current_dir.is_symlink():
                    self._safe_remove_workspace_package_path(current_dir, label="package upgrade rollback target")
                if backup_dir.exists():
                    shutil.copytree(backup_dir, current_dir)
                    rollback_status = "restored_backup"
                workspace_backup = backup_root / "workspace.yaml"
                lock_backup = backup_root / "packages.lock.yaml"
                if workspace_backup.is_file():
                    shutil.copy2(workspace_backup, self.workspace_path)
                if lock_backup.is_file():
                    shutil.copy2(lock_backup, self.lock_path)
            except Exception as rollback_exc:  # noqa: BLE001
                rollback_status = f"rollback_failed: {rollback_exc}"
            operation.update({"status": "error", "message": str(exc), "rollback": rollback_status})
            self._record_upgrade_operation(operation)
            return {"status": "error", **plan, "message": str(exc), "rollback": rollback_status}

    def rollback_package(self, package_id: str, *, to_lock: str | Path | None = None) -> dict[str, Any]:
        target_id = normalize_package_id(package_id)
        last = self._last_upgrade_operation(target_id)
        if not last or not last.get("backup"):
            return {"status": "error", "package_id": target_id, "message": "No upgrade backup is available."}
        ref = next((item for item in self.package_refs() if item.id == target_id), None)
        if ref is None:
            return {"status": "error", "package_id": target_id, "message": "Package is not declared in workspace."}
        target = self._safe_package_source_path(ref.source, roots=[self.plans_dir, self.packages_dir], label="package rollback target")
        backup = Path(last.get("backup") or last.get("backup_package")).resolve()
        backup_root = Path(last.get("backup_root") or backup.parent).resolve()
        if not backup.exists():
            return {"status": "error", "package_id": target_id, "message": f"Backup not found: {backup}"}
        if target.exists():
            self._safe_remove_workspace_package_path(target, label="package rollback target")
        shutil.copytree(backup, target)
        workspace_backup = backup_root / "workspace.yaml"
        if workspace_backup.is_file():
            shutil.copy2(workspace_backup, self.workspace_path)
        if to_lock:
            lock_src = Path(to_lock).resolve()
            if lock_src.is_file():
                shutil.copy2(lock_src, self.lock_path)
        elif (backup_root / "packages.lock.yaml").is_file():
            shutil.copy2(backup_root / "packages.lock.yaml", self.lock_path)
        else:
            self.write_lock()
        operation = {"status": "success", "operation": "rollback", "package_id": target_id, "restored_from": str(backup), "target": str(target)}
        self._record_upgrade_operation(operation)
        return operation

    def package_migrations(self, package_id: str, *, execute: bool = False, trusted: bool = False) -> dict[str, Any]:
        target_id = normalize_package_id(package_id)
        ref = next((item for item in self.package_refs() if item.id == target_id), None)
        if ref is None:
            return {"status": "error", "package_id": target_id, "migrations": []}
        package_dir = self._safe_package_source_path(ref.source, roots=[self.plans_dir, self.packages_dir], label="package migration source")
        manifest_path = package_dir / "manifest.yaml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        compat = data.get("compat") if isinstance(data, dict) else {}
        hooks = compat.get("migration_hooks") if isinstance(compat, dict) else []
        migrations_dir = package_dir / "migrations"
        files = [path.relative_to(package_dir).as_posix() for path in sorted(migrations_dir.rglob("*.py"))] if migrations_dir.is_dir() else []
        declared = [str(item) for item in hooks or []]
        candidates = list(dict.fromkeys([*declared, *files]))
        reports = [
            self._run_migration_hook(package_dir, hook, execute=execute, trusted=trusted)
            for hook in candidates
        ]
        errors = [item for item in reports if item.get("status") == "error"]
        return {
            "status": "error" if errors else "success",
            "package_id": target_id,
            "hooks": declared,
            "files": files,
            "dry_run": not execute,
            "execute": bool(execute),
            "reports": reports,
            "errors": errors,
        }

    def _default_workspace_from_disk(self) -> dict[str, Any]:
        packages = []
        for manifest_path in sorted([*self.plans_dir.rglob("manifest.yaml"), *self.packages_dir.rglob("manifest.yaml")]):
            if any(part in {"__pycache__", ".git"} for part in manifest_path.parts):
                continue
            try:
                manifest = ManifestParser.parse(manifest_path)
            except Exception:
                continue
            source = _relative_path(manifest_path.parent, self.base_path)
            packages.append({"id": normalize_package_id(manifest.package.canonical_id), "enabled": True, "source": source})
        return {
            "workspace_schema_version": WORKSPACE_SCHEMA_VERSION,
            "workspace": {"name": "default", "profile": "workspace-default"},
            "runtime": {"api_profile": "local_only", "desktop_profile": "default", "persistence": "sqlite"},
            "packages": packages,
        }

    def _ensure_workspace_file(self) -> dict[str, Any]:
        workspace = self.load_workspace()
        if not self.workspace_path.is_file():
            self.save_workspace(workspace)
        return workspace

    def _upsert_package_ref(self, package_id: str, *, source: str, enabled: bool) -> None:
        workspace = self._ensure_workspace_file()
        target_id = normalize_package_id(package_id)
        packages = list(workspace.get("packages", []) or [])
        for item in packages:
            if normalize_package_id(item.get("id")) == target_id:
                item.update({"id": target_id, "enabled": enabled, "source": source})
                self.save_workspace(workspace)
                return
        packages.append({"id": target_id, "enabled": enabled, "source": source})
        workspace["packages"] = packages
        self.save_workspace(workspace)

    def _set_enabled(self, package_id: str, enabled: bool) -> dict[str, Any]:
        target_id = normalize_package_id(package_id)
        workspace = self._ensure_workspace_file()
        for item in workspace.get("packages", []) or []:
            if normalize_package_id(item.get("id")) == target_id:
                item["enabled"] = enabled
                self.save_workspace(workspace)
                self.write_lock()
                return {
                    "status": "success",
                    "package_id": target_id,
                    "enabled": enabled,
                    "message": "Package state updated. Reload or restart the API to apply runtime changes.",
                }
        return {"status": "error", "message": f"Package '{target_id}' not found in workspace."}

    def _resolve_validate_targets(self, package_or_path: str | None) -> list[Path]:
        if not package_or_path:
            return [(self.base_path / ref.source).resolve() for ref in self.package_refs()]
        candidate = Path(package_or_path)
        if candidate.exists():
            return [candidate.resolve()]
        target_id = normalize_package_id(package_or_path)
        for ref in self.package_refs():
            if ref.id == target_id:
                return [(self.base_path / ref.source).resolve()]
        return [(self.base_path / str(package_or_path)).resolve()]

    def _validate_package_dir(self, package_dir: Path) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        errors.extend(scan_symlinks(package_dir))
        manifest_path = package_dir / "manifest.yaml"
        if not manifest_path.is_file():
            return [{"code": "manifest_missing", "path": str(manifest_path), "message": "manifest.yaml not found."}]
        try:
            manifest = ManifestParser.parse(manifest_path)
            for message in ManifestParser.validate(manifest):
                errors.append({"code": "manifest_validation_failed", "path": str(manifest_path), "message": message})
        except Exception as exc:  # noqa: BLE001
            return [{"code": "manifest_parse_failed", "path": str(manifest_path), "message": str(exc)}]
        for service in manifest.exports.services:
            errors.extend(_check_export_import(service.module, service.class_name, package_dir))
        for action in manifest.exports.actions:
            errors.extend(_check_export_import(action.module, action.function_name, package_dir))
        try:
            loader = TaskLoader(package_dir.name, package_dir, manifest)
            loader.get_all_task_definitions()
            for row in loader.get_task_load_errors():
                errors.append({"code": row.get("error_code") or "task_load_failed", "path": str(row.get("source_file") or ""), "message": str(row.get("message") or "")})
        except Exception as exc:  # noqa: BLE001
            errors.append({"code": "task_validation_failed", "path": str(package_dir), "message": str(exc)})
        return errors

    def _normalize_install_source(self, source: Path) -> Path:
        if source.is_dir():
            return source
        if source.suffix.lower() not in {".zip", ".aura"}:
            raise ValueError(f"Unsupported package archive format: {source}")
        temp_root = self.base_path / ".aura_tmp" / "install"
        if temp_root.exists():
            safe_remove_tree(self.base_path, temp_root, label="package install temp")
        temp_root.mkdir(parents=True, exist_ok=True)
        safe_extract_zip(source, temp_root)
        package_manifest = temp_root / "package" / "manifest.yaml"
        if package_manifest.is_file():
            return package_manifest.parent
        manifests = list(temp_root.rglob("manifest.yaml"))
        if not manifests:
            raise ValueError("Archive does not contain manifest.yaml.")
        return manifests[0].parent

    def _normalize_package_for_read(self, source: Path, extract_dir: Path) -> Path:
        if source.is_dir():
            return source
        if source.suffix.lower() not in {".zip", ".aura"}:
            raise ValueError(f"Unsupported package archive format: {source}")
        if extract_dir.exists():
            safe_remove_tree(self.base_path, extract_dir, label="package read temp")
        extract_dir.mkdir(parents=True, exist_ok=True)
        safe_extract_zip(source, extract_dir)
        manifest_candidates = [extract_dir / "package" / "manifest.yaml", extract_dir / "manifest.yaml", *extract_dir.rglob("manifest.yaml")]
        for candidate in manifest_candidates:
            if candidate.is_file():
                return candidate.parent
        raise ValueError(f"Archive does not contain manifest.yaml: {source}")

    def _record_upgrade_operation(self, payload: dict[str, Any]) -> None:
        log_dir = self.base_path / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        row = {"created_at": datetime.now(timezone.utc).isoformat(), **payload}
        with (log_dir / "package-upgrades.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _fixture_gate(self) -> dict[str, Any]:
        try:
            from packages.aura_core.fixtures import FixtureService

            return FixtureService(self.base_path).verify_all()
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    def _run_reload_gate(self, package_id: str) -> dict[str, Any]:
        old_base = os.environ.get("AURA_BASE_PATH")
        os.environ["AURA_BASE_PATH"] = str(self.base_path)
        try:
            from packages.aura_core.runtime.bootstrap import create_runtime, reset_runtime

            scheduler = create_runtime(profile="api_full")
            plan = scheduler.plan_runtime_reload(package_id=package_id, mode="package")
            if plan.get("status") not in {"success", "idle"}:
                return {"status": "error", "phase": "plan", "plan": plan}
            import asyncio

            if scheduler._loop and scheduler._loop.is_running():
                apply_result = scheduler.run_on_control_loop(
                    scheduler.apply_runtime_reload(package_id=package_id, mode="package", drain=False),
                    timeout=35.0,
                )
            else:
                apply_result = asyncio.run(
                    scheduler.apply_runtime_reload(package_id=package_id, mode="package", drain=False)
                )
            if apply_result.get("status") != "success":
                return {"status": "error", "phase": "apply", "plan": plan, "apply": apply_result}
            return {"status": "success", "plan": plan, "apply": apply_result}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "phase": "runtime", "message": str(exc)}
        finally:
            try:
                from packages.aura_core.runtime.bootstrap import reset_runtime

                reset_runtime()
            except Exception:
                pass
            if old_base is None:
                os.environ.pop("AURA_BASE_PATH", None)
            else:
                os.environ["AURA_BASE_PATH"] = old_base

    def _run_migration_hook(self, package_dir: Path, hook: str, *, execute: bool, trusted: bool) -> dict[str, Any]:
        try:
            hook_path = safe_resolve_under(package_dir, hook, label="migration hook")
            if not hook_path.is_file():
                return {"status": "error", "hook": hook, "message": f"Migration hook not found: {hook_path}"}
            if not execute:
                return {"status": "success", "hook": hook, "mode": "dry-run", "path": str(hook_path)}
            if not trusted:
                return {"status": "error", "hook": hook, "message": "Executing package migrations requires --trusted."}
            if not self._policy_allows_migration():
                return {"status": "error", "hook": hook, "message": "Active policy does not allow filesystem.write migrations."}
            spec = importlib.util.spec_from_file_location(f"aura_package_migration_{hashlib.sha1(str(hook_path).encode()).hexdigest()}", hook_path)
            if spec is None or spec.loader is None:
                return {"status": "error", "hook": hook, "message": "Unable to load migration hook."}
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            runner = getattr(module, "migrate", None) or getattr(module, "run", None)
            if runner is None:
                return {"status": "success", "hook": hook, "mode": "execute", "path": str(hook_path), "result": "no migrate/run function"}
            result = runner({"base_path": str(self.base_path), "package_dir": str(package_dir), "dry_run": False})
            return {"status": "success", "hook": hook, "mode": "execute", "path": str(hook_path), "result": result}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "hook": hook, "message": str(exc)}

    def _safe_package_source_path(self, source: str, *, roots: list[Path], label: str) -> Path:
        relative = validate_safe_relative_path(str(source or ""), label=label)
        candidate = (self.base_path / relative).resolve()
        for root in roots:
            try:
                return ensure_path_under(root, candidate, label=label, allow_root=False)
            except UnsafePathError:
                continue
        allowed = ", ".join(str(root.resolve()) for root in roots)
        raise UnsafePathError(f"{label} must stay under one of: {allowed}")

    def _safe_remove_workspace_package_path(self, target: Path, *, label: str) -> None:
        for root in (self.plans_dir, self.packages_dir):
            try:
                safe_remove_tree(root, target, label=label)
                return
            except UnsafePathError:
                continue
        raise UnsafePathError(f"{label} is outside mutable workspace package roots: {target}")

    @staticmethod
    def _policy_allows_migration() -> bool:
        try:
            from packages.aura_core.policy import POLICY_PROFILES, get_active_policy_profile

            profile = get_active_policy_profile()
            rules = POLICY_PROFILES.get(profile, POLICY_PROFILES["default"])
            return "filesystem.write" in rules.get("allow", set()) and "filesystem.write" not in rules.get("deny", set())
        except Exception:
            return False

    def _last_upgrade_operation(self, package_id: str) -> dict[str, Any] | None:
        path = self.base_path / "logs" / "package-upgrades.jsonl"
        if not path.is_file():
            return None
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if normalize_package_id(row.get("package_id")) == package_id:
                rows.append(row)
        return rows[-1] if rows else None


def normalize_package_id(raw: Any) -> str:
    return validate_package_id(raw)


def _id_from_source(source: str) -> str:
    try:
        value = validate_safe_relative_path(str(source or ""), label="package source")
    except UnsafePathError:
        return ""
    if value.startswith("plans/") or value.startswith("packages/"):
        parts = value.split("/")
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
    return value


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _content_hash(package_dir: Path, *, rebase_prefix: str | None = None) -> str | None:
    if not package_dir.exists():
        return None
    digest = hashlib.sha256()
    for path in iter_package_files(package_dir, skip_parts={".git", "__pycache__", ".pytest_cache", "node_modules"}):
        if path.suffix in {".pyc", ".pyo"}:
            continue
        rel = path.relative_to(package_dir).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_stable_package_file_bytes(path, package_dir, rebase_prefix=rebase_prefix))
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _check_export_import(module_name: str, attr_name: str, package_dir: Path) -> list[dict[str, Any]]:
    candidates = [module_name]
    prefix = _derive_package_import_prefix(package_dir)
    if prefix and not module_name.startswith(f"{prefix}."):
        candidates.append(f"{prefix}.{module_name}")
        if not module_name.startswith("src."):
            candidates.append(f"{prefix}.src.{module_name}")

    previous_path = list(sys.path)
    sys.path.insert(0, str(package_dir))
    errors = []
    try:
        for candidate in dict.fromkeys(candidates):
            try:
                module = importlib.import_module(candidate)
                getattr(module, attr_name)
                return []
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{candidate}: {exc}")
    finally:
        sys.path[:] = previous_path

    return [
        {
            "code": "export_import_failed",
            "path": str(package_dir),
            "message": f"{module_name}:{attr_name} failed to import. Tried {errors}",
        }
    ]


def _file_checksums(package_dir: Path, *, rebase_prefix: str | None = None) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for path in iter_package_files(package_dir, skip_parts={".git", "__pycache__", ".pytest_cache", "node_modules"}):
        if path.suffix in {".pyc", ".pyo"}:
            continue
        digest = hashlib.sha256(_stable_package_file_bytes(path, package_dir, rebase_prefix=rebase_prefix)).hexdigest()
        checksums[path.relative_to(package_dir).as_posix()] = digest
    return checksums


def _stable_package_file_bytes(path: Path, package_dir: Path, *, rebase_prefix: str | None = None) -> bytes:
    rel = path.relative_to(package_dir).as_posix()
    if rel == "manifest.yaml":
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if rebase_prefix:
                data = _rebase_manifest_modules(data, rebase_prefix)
            metadata = data.get("metadata")
            if isinstance(metadata, dict):
                metadata = dict(metadata)
                metadata.pop("generated_at", None)
                data["metadata"] = metadata
            return yaml.safe_dump(data, allow_unicode=True, sort_keys=True).encode("utf-8")
        except Exception:
            return path.read_bytes()
    return path.read_bytes()


def _derive_package_import_prefix(package_dir: Path) -> str:
    parts = [package_dir.name]
    cursor = package_dir.parent
    while (cursor / "__init__.py").exists():
        parts.append(cursor.name)
        cursor = cursor.parent
    return ".".join(reversed(parts))


def _rebase_manifest_modules(data: dict[str, Any], rebase_prefix: str) -> dict[str, Any]:
    payload = json.loads(json.dumps(data))
    exports = payload.get("exports")
    if isinstance(exports, dict):
        for service in exports.get("services") or []:
            if isinstance(service, dict) and "module" in service:
                service["module"] = _strip_module_prefix(service["module"], rebase_prefix)
        for action in exports.get("actions") or []:
            if isinstance(action, dict) and "module" in action:
                action["module"] = _strip_module_prefix(action["module"], rebase_prefix)
    lifecycle = payload.get("lifecycle")
    if isinstance(lifecycle, dict):
        for key in ("on_load", "on_unload", "on_enable", "on_disable"):
            if key in lifecycle:
                lifecycle[key] = _strip_hook_prefix(lifecycle[key], rebase_prefix)
    return payload


def _strip_hook_prefix(value: Any, rebase_prefix: str) -> Any:
    token = str(value or "")
    if ":" not in token:
        return _strip_module_prefix(token, rebase_prefix)
    module, attr = token.split(":", 1)
    return f"{_strip_module_prefix(module, rebase_prefix)}:{attr}"


def _strip_module_prefix(value: Any, rebase_prefix: str) -> str:
    token = str(value or "").strip()
    package_leaf = rebase_prefix.split(".")[-1]
    for prefix in (rebase_prefix, f"packages.{package_leaf}"):
        if token == prefix:
            return ""
        if token.startswith(f"{prefix}."):
            return token[len(prefix) + 1 :]
    return token


def _package_summary(package_dir: Path) -> dict[str, Any]:
    manifest_path = package_dir / "manifest.yaml"
    manifest = ManifestParser.parse(manifest_path)
    return {
        "id": normalize_package_id(manifest.package.canonical_id),
        "name": manifest.package.name,
        "version": manifest.package.version,
        "content_hash": _content_hash(package_dir),
        "actions": sorted(action.name for action in manifest.exports.actions),
        "services": sorted(service.alias or service.class_name for service in manifest.exports.services),
    }


def _package_upgrade_recommendations(risks: list[dict[str, Any]]) -> list[str]:
    if not risks:
        return ["Package is compatible with the current workspace checks."]
    codes = {risk.get("code") for risk in risks}
    recommendations = []
    if "lock_drift" in codes:
        recommendations.append("Regenerate packages.lock.yaml after reviewing package changes.")
    if "package_not_found" in codes:
        recommendations.append("Install or enable the package before planning an upgrade.")
    if any(code and "validation" in str(code) for code in codes):
        recommendations.append("Fix package validation errors before packaging or enabling.")
    return recommendations or ["Review listed risks before upgrading."]

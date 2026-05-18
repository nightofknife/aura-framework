# -*- coding: utf-8 -*-
"""Diagnostics bundle collector."""

from __future__ import annotations

import json
import platform
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import yaml

from packages.aura_core.observability.run_store import RunStore
from packages.aura_core.packaging.core.workspace_lifecycle import WorkspaceLifecycleService
from packages.aura_core.security import redact_file_payload, redact_json
from packages.aura_core.utils.safe_paths import UnsafePathError, ensure_path_under


class DiagnosticsCollector:
    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path).resolve()
        self.store = RunStore(self.base_path / "logs" / "aura.sqlite3")
        self.workspace = WorkspaceLifecycleService(self.base_path)

    def collect(self, *, output: str | Path | None = None, include_evidence: bool = False, recent_runs: int = 20) -> dict[str, Any]:
        bundle_id = f"diag-{time.strftime('%Y%m%d-%H%M%S')}"
        default_dir = self.base_path / "diagnostics" / bundle_id
        output_path = Path(output).resolve() if output else default_dir
        is_zip = output_path.suffix.lower() == ".zip"
        work_dir = output_path.with_suffix("") if is_zip else output_path
        if is_zip and output_path.exists():
            raise FileExistsError(f"Diagnostics output already exists: {output_path}")
        if work_dir.exists():
            if not _is_diagnostics_bundle_dir(work_dir):
                raise FileExistsError(f"Diagnostics output already exists and is not an Aura diagnostics bundle: {work_dir}")
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

        runs = self.store.list_runs(limit=recent_runs)
        failed_runs = [row for row in runs if str(row.get("status") or "").lower() in {"error", "failed", "timeout", "cancelled"}]
        files = {
            "manifest.json": self._manifest(bundle_id, include_evidence),
            "system.json": self._system(),
            "workspace.json": self._workspace_payload(),
            "packages.json": self._packages_payload(),
            "capabilities.json": self._capabilities_payload(),
            "runs.json": {"runs": runs},
            "config.redacted.json": self._config_payload(),
        }
        for name, payload in files.items():
            _write_json(work_dir / name, payload)
        self._write_run_details(work_dir / "run-details", failed_runs)
        self._copy_evidence_manifests(work_dir / "evidence", failed_runs, include_files=include_evidence)
        self._copy_recent_logs(work_dir / "logs")

        final_path = work_dir
        if is_zip:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for file_path in sorted(work_dir.rglob("*")):
                    if file_path.is_file():
                        archive.write(file_path, file_path.relative_to(work_dir))
            shutil.rmtree(work_dir)
            final_path = output_path

        summary = {
            "bundle_id": bundle_id,
            "path": str(final_path),
            "run_count": len(runs),
            "failed_run_count": len(failed_runs),
            "include_evidence": include_evidence,
        }
        self.store.record_diagnostic_bundle(bundle_id, str(final_path), "success", summary)
        return {"status": "success", **summary}

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.store.list_diagnostic_bundles(limit=limit)

    def get(self, bundle_id: str) -> dict[str, Any]:
        return self.store.get_diagnostic_bundle(bundle_id)

    def _manifest(self, bundle_id: str, include_evidence: bool) -> dict[str, Any]:
        return {
            "id": bundle_id,
            "created_at_ms": int(time.time() * 1000),
            "schema_versions": {
                "api_version": "v1",
                "manifest_version": 1,
                "task_dsl_version": 1,
                "workspace_schema_version": 1,
                "lock_schema_version": 1,
                "capability_schema_version": 1,
                "diagnostics_schema_version": 1,
                "run_store_schema_version": 1,
            },
            "include_evidence": include_evidence,
        }

    def _system(self) -> dict[str, Any]:
        return {
            "python": sys.version,
            "platform": platform.platform(),
            "cwd": str(Path.cwd()),
            "base_path": str(self.base_path),
            "runtime_profile": "workspace-default",
        }

    def _workspace_payload(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace.load_workspace(),
            "lock": self.workspace.load_lock(),
        }

    def _packages_payload(self) -> dict[str, Any]:
        return {
            "packages": self.workspace.list_packages(),
            "doctor": self.workspace.doctor(),
        }

    def _capabilities_payload(self) -> dict[str, Any]:
        try:
            from plans.aura_base.src.desktop_runtime import get_desktop_registry

            registry = get_desktop_registry()
            payload = {"capabilities": registry.list(), "self_check": registry.self_check()}
            self.store.record_capability_snapshot(f"cap-{int(time.time() * 1000)}", payload)
            return payload
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    def _config_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for name in ("config.yaml", "config.example.yaml", ".env.example", "workspace.yaml"):
            path = self.base_path / name
            if not path.is_file():
                continue
            if path.suffix in {".yaml", ".yml"}:
                try:
                    payload[name] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                except Exception:
                    payload[name] = path.read_text(encoding="utf-8", errors="replace")
            else:
                payload[name] = path.read_text(encoding="utf-8", errors="replace")
        return redact_json(payload)

    def _write_run_details(self, target_dir: Path, failed_runs: list[dict[str, Any]]) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        for run in failed_runs:
            cid = str(run.get("cid") or "")
            if not cid:
                continue
            detail = self.store.get_run(cid)
            _write_json(target_dir / f"{cid}.json", detail or run)

    def _copy_recent_logs(self, target_dir: Path) -> None:
        logs_dir = self.base_path / "logs"
        target_dir.mkdir(parents=True, exist_ok=True)
        if not logs_dir.is_dir():
            return
        candidates = []
        for path in logs_dir.rglob("*.log"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                ensure_path_under(logs_dir, path, label="recent log", allow_root=False)
                candidates.append(path)
            except UnsafePathError:
                continue
        copied = 0
        for path in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True):
            if copied >= 5:
                break
            rel_name = path.name
            (target_dir / rel_name).write_text(redact_file_payload(path), encoding="utf-8")
            copied += 1

    def _copy_evidence_manifests(self, target_dir: Path, runs: list[dict[str, Any]], *, include_files: bool) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        evidence_root = self.base_path / "logs" / "evidence"
        if not evidence_root.is_dir():
            return
        for run in runs:
            cid = str(run.get("cid") or "")
            if not cid:
                continue
            source_dir = evidence_root / cid
            if not source_dir.is_dir():
                continue
            dest_dir = target_dir / cid
            dest_dir.mkdir(parents=True, exist_ok=True)
            for name in ("manifest.json", "action-results.jsonl"):
                src = source_dir / name
                if src.is_file():
                    try:
                        ensure_path_under(evidence_root, src, label="evidence manifest", allow_root=False)
                    except UnsafePathError:
                        continue
                    (dest_dir / name).write_text(redact_file_payload(src), encoding="utf-8")
            if include_files:
                for child in ("captures", "ocr", "backend"):
                    src_child = source_dir / child
                    if src_child.is_dir():
                        self._copy_registered_evidence_files(src_child, dest_dir / child, evidence_root)

    @staticmethod
    def _copy_registered_evidence_files(source_dir: Path, target_dir: Path, evidence_root: Path) -> None:
        for path in source_dir.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                ensure_path_under(evidence_root, path, label="evidence file", allow_root=False)
            except UnsafePathError:
                continue
            relative = path.relative_to(source_dir)
            target = target_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact_json(payload), ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _is_diagnostics_bundle_dir(path: Path) -> bool:
    manifest = path / "manifest.json"
    if not manifest.is_file():
        return False
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return False
    return str(payload.get("id") or "").startswith("diag-") and "diagnostics_schema_version" in (
        payload.get("schema_versions") or {}
    )

# -*- coding: utf-8 -*-
"""Persistence lifecycle utilities for the local SQLite runtime store."""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
import zipfile
from pathlib import Path
from typing import Any

from packages.aura_core.security import redact_json
from packages.aura_core.utils.safe_paths import UnsafePathError, ensure_path_under


class PersistenceLifecycleService:
    """Retention, archive and export operations for local runtime data."""

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path).resolve()
        self.db_path = self.base_path / "logs" / "aura.sqlite3"
        self.evidence_dir = self.base_path / "logs" / "evidence"
        self.diagnostics_dir = self.base_path / "diagnostics"

    def status(self) -> dict[str, Any]:
        tables = self._table_counts() if self.db_path.is_file() else {}
        return {
            "status": "success",
            "db_path": str(self.db_path),
            "db_exists": self.db_path.is_file(),
            "db_size_bytes": self.db_path.stat().st_size if self.db_path.is_file() else 0,
            "tables": tables,
            "evidence_dir": str(self.evidence_dir),
            "evidence_exists": self.evidence_dir.is_dir(),
            "diagnostics_dir": str(self.diagnostics_dir),
            "diagnostics_exists": self.diagnostics_dir.is_dir(),
        }

    def cleanup(self, *, older_than_days: int, dry_run: bool = True) -> dict[str, Any]:
        cutoff_ms = _cutoff_ms(older_than_days)
        targets = self._cleanup_targets(cutoff_ms)
        if not dry_run and self.db_path.is_file():
            with self._connect() as conn:
                conn.execute("DELETE FROM resource_samples WHERE created_at_ms < ?", (cutoff_ms,))
                conn.execute("DELETE FROM queue_snapshots WHERE created_at_ms < ?", (cutoff_ms,))
                conn.execute("DELETE FROM diagnostic_bundles WHERE created_at_ms < ?", (cutoff_ms,))
                conn.commit()
        return {
            "status": "success",
            "dry_run": dry_run,
            "older_than_days": int(older_than_days),
            "cutoff_ms": cutoff_ms,
            "deleted": [] if dry_run else targets,
            "would_delete": targets if dry_run else [],
            "protected": ["runs", "node_terminal_events", "action_results", "policy_audit", "evidence_refs", "logs/evidence/*"],
        }

    def archive(
        self,
        *,
        older_than_days: int,
        output: str | Path,
        include_evidence: bool = False,
    ) -> dict[str, Any]:
        cutoff_ms = _cutoff_ms(older_than_days)
        output_path = Path(output).resolve()
        payload = self._archive_payload(cutoff_ms)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(redact_json(_archive_manifest(cutoff_ms, include_evidence)), ensure_ascii=False, indent=2))
                archive.writestr("runs.json", json.dumps(redact_json(payload["runs"]), ensure_ascii=False, indent=2))
                archive.writestr("diagnostic_bundles.json", json.dumps(redact_json(payload["diagnostic_bundles"]), ensure_ascii=False, indent=2))
                archive.writestr("evidence_refs.json", json.dumps(redact_json(payload["evidence_refs"]), ensure_ascii=False, indent=2))
                if include_evidence:
                    self._write_evidence_files_to_zip(archive, payload["evidence_refs"])
        else:
            output_path.mkdir(parents=True, exist_ok=True)
            (output_path / "manifest.json").write_text(json.dumps(redact_json(_archive_manifest(cutoff_ms, include_evidence)), ensure_ascii=False, indent=2), encoding="utf-8")
            (output_path / "runs.json").write_text(json.dumps(redact_json(payload["runs"]), ensure_ascii=False, indent=2), encoding="utf-8")
            (output_path / "diagnostic_bundles.json").write_text(json.dumps(redact_json(payload["diagnostic_bundles"]), ensure_ascii=False, indent=2), encoding="utf-8")
            (output_path / "evidence_refs.json").write_text(json.dumps(redact_json(payload["evidence_refs"]), ensure_ascii=False, indent=2), encoding="utf-8")
            if include_evidence:
                self._copy_evidence_files(output_path / "evidence", payload["evidence_refs"])
        return {
            "status": "success",
            "path": str(output_path),
            "older_than_days": int(older_than_days),
            "include_evidence": include_evidence,
            "counts": {key: len(value) for key, value in payload.items()},
        }

    def export(self, *, output: str | Path, output_format: str = "jsonl") -> dict[str, Any]:
        output_path = Path(output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_format == "sqlite":
            if not self.db_path.is_file():
                return {"status": "error", "message": f"SQLite database not found: {self.db_path}"}
            shutil.copy2(self.db_path, output_path)
            return {"status": "success", "format": "sqlite", "path": str(output_path)}
        if output_format != "jsonl":
            return {"status": "error", "message": f"Unsupported export format: {output_format}"}
        rows = self._export_rows()
        with output_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(redact_json(row), ensure_ascii=False) + "\n")
        return {"status": "success", "format": "jsonl", "path": str(output_path), "rows": len(rows)}

    def _table_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self._connect() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall()
            for row in rows:
                name = row["name"]
                counts[name] = int(conn.execute(f"SELECT COUNT(*) AS c FROM {name}").fetchone()["c"])
        return counts

    def _cleanup_targets(self, cutoff_ms: int) -> list[dict[str, Any]]:
        if not self.db_path.is_file():
            return []
        targets = []
        with self._connect() as conn:
            for table in ("resource_samples", "queue_snapshots", "diagnostic_bundles"):
                if not _table_exists(conn, table):
                    continue
                column = "created_at_ms"
                count = conn.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE {column} < ?", (cutoff_ms,)).fetchone()["c"]
                targets.append({"kind": "sqlite_rows", "table": table, "count": int(count)})
        return targets

    def _archive_payload(self, cutoff_ms: int) -> dict[str, list[dict[str, Any]]]:
        payload = {"runs": [], "diagnostic_bundles": [], "evidence_refs": []}
        if not self.db_path.is_file():
            return payload
        with self._connect() as conn:
            if _table_exists(conn, "runs"):
                payload["runs"] = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM runs WHERE COALESCE(finished_at_ms, updated_at_ms, 0) < ? ORDER BY updated_at_ms",
                        (cutoff_ms,),
                    ).fetchall()
                ]
            if _table_exists(conn, "diagnostic_bundles"):
                payload["diagnostic_bundles"] = [
                    dict(row)
                    for row in conn.execute("SELECT * FROM diagnostic_bundles WHERE created_at_ms < ? ORDER BY created_at_ms", (cutoff_ms,)).fetchall()
                ]
            if _table_exists(conn, "evidence_refs"):
                archived_cids = {row.get("cid") for row in payload["runs"]}
                if archived_cids:
                    placeholders = ",".join("?" for _ in archived_cids)
                    payload["evidence_refs"] = [
                        dict(row)
                        for row in conn.execute(
                            f"SELECT * FROM evidence_refs WHERE cid IN ({placeholders}) ORDER BY updated_at_ms",
                            tuple(archived_cids),
                        ).fetchall()
                    ]
        return payload

    def _export_rows(self) -> list[dict[str, Any]]:
        if not self.db_path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        with self._connect() as conn:
            for table in ("runs", "node_terminal_events", "action_results", "policy_audit", "evidence_refs"):
                if not _table_exists(conn, table):
                    continue
                for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                    rows.append({"table": table, "row": dict(row)})
        return rows

    def _write_evidence_files_to_zip(self, archive: zipfile.ZipFile, refs: list[dict[str, Any]]) -> None:
        for ref in refs:
            source = self._evidence_source(ref)
            if source and source.is_file():
                archive.write(source, f"evidence/{source.name}")

    def _copy_evidence_files(self, target_dir: Path, refs: list[dict[str, Any]]) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        for ref in refs:
            source = self._evidence_source(ref)
            if source and source.is_file():
                shutil.copy2(source, target_dir / source.name)

    def _evidence_source(self, ref: dict[str, Any]) -> Path | None:
        path = ref.get("path")
        if not path:
            return None
        source = Path(path)
        if not source.is_absolute():
            source = self.base_path / path
        try:
            ensure_path_under(self.base_path, source, label="evidence file", allow_root=False)
        except (UnsafePathError, OSError):
            return None
        return source

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn


def _cutoff_ms(older_than_days: int) -> int:
    return int((time.time() - max(0, int(older_than_days)) * 86400) * 1000)


def _archive_manifest(cutoff_ms: int, include_evidence: bool) -> dict[str, Any]:
    return {
        "archive_schema_version": 1,
        "created_at_ms": int(time.time() * 1000),
        "cutoff_ms": cutoff_ms,
        "include_evidence": include_evidence,
        "binary_evidence_policy": "included" if include_evidence else "manifest_refs_only",
    }


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())

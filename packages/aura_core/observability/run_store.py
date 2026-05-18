# -*- coding: utf-8 -*-
"""Durable run state store backed by SQLite (WAL)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


_TERMINAL_STATUSES = {"success", "error", "failed", "timeout", "cancelled", "abandoned"}
_ALLOWED_TRANSITIONS = {
    None: {"queued", "running", *sorted(_TERMINAL_STATUSES)},
    "queued": {"running", *sorted(_TERMINAL_STATUSES)},
    "running": set(_TERMINAL_STATUSES),
}


class RunStore:
    """Authoritative run timeline store."""

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    cid TEXT PRIMARY KEY,
                    trace_id TEXT,
                    trace_label TEXT,
                    source TEXT,
                    parent_cid TEXT,
                    plan_name TEXT,
                    task_name TEXT,
                    status TEXT,
                    started_at_ms INTEGER,
                    finished_at_ms INTEGER,
                    queue_wait_ms REAL,
                    duration_ms INTEGER,
                    updated_at_ms INTEGER,
                    final_result_json TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS node_terminal_events (
                    cid TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    node_name TEXT,
                    status TEXT,
                    start_ms INTEGER,
                    end_ms INTEGER,
                    duration_ms REAL,
                    retry_count INTEGER,
                    exception_type TEXT,
                    exception_message TEXT,
                    loop_index INTEGER DEFAULT 0,
                    loop_item_json TEXT,
                    source_event TEXT NOT NULL,
                    updated_at_ms INTEGER,
                    PRIMARY KEY (cid, node_id, loop_index)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_runs_plan_task ON runs(plan_name, task_name)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_runs_updated ON runs(updated_at_ms DESC)")
            cur.execute(
                """
                CREATE VIEW IF NOT EXISTS run_nodes AS
                SELECT * FROM node_terminal_events
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_packages (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    version TEXT,
                    enabled INTEGER,
                    source TEXT,
                    content_hash TEXT,
                    validation_status TEXT,
                    updated_at_ms INTEGER
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_snapshots (
                    id TEXT PRIMARY KEY,
                    created_at_ms INTEGER,
                    payload_json TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS diagnostic_bundles (
                    id TEXT PRIMARY KEY,
                    created_at_ms INTEGER,
                    path TEXT NOT NULL,
                    status TEXT,
                    summary_json TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS action_results (
                    cid TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    loop_index INTEGER DEFAULT 0,
                    action TEXT,
                    backend TEXT,
                    ok INTEGER,
                    duration_ms INTEGER,
                    payload_json TEXT NOT NULL,
                    updated_at_ms INTEGER,
                    PRIMARY KEY (cid, node_id, loop_index)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS policy_audit (
                    cid TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    loop_index INTEGER DEFAULT 0,
                    action TEXT,
                    profile TEXT,
                    decision TEXT,
                    reason TEXT,
                    capabilities_json TEXT,
                    payload_json TEXT NOT NULL,
                    updated_at_ms INTEGER,
                    PRIMARY KEY (cid, node_id, loop_index)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_refs (
                    id TEXT PRIMARY KEY,
                    cid TEXT NOT NULL,
                    node_id TEXT,
                    kind TEXT,
                    path TEXT,
                    payload_json TEXT NOT NULL,
                    updated_at_ms INTEGER
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_index (
                    trace_id TEXT PRIMARY KEY,
                    cid TEXT NOT NULL,
                    status TEXT,
                    plan_name TEXT,
                    task_name TEXT,
                    updated_at_ms INTEGER
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS error_events (
                    id TEXT PRIMARY KEY,
                    cid TEXT NOT NULL,
                    node_id TEXT,
                    category TEXT,
                    message TEXT,
                    payload_json TEXT,
                    updated_at_ms INTEGER
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS action_metrics (
                    action TEXT PRIMARY KEY,
                    count INTEGER DEFAULT 0,
                    ok_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    duration_ms_total INTEGER DEFAULT 0,
                    updated_at_ms INTEGER
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS backend_metrics (
                    backend TEXT PRIMARY KEY,
                    count INTEGER DEFAULT 0,
                    ok_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    fallback_count INTEGER DEFAULT 0,
                    updated_at_ms INTEGER
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_snapshots (
                    id TEXT PRIMARY KEY,
                    created_at_ms INTEGER,
                    payload_json TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS resource_samples (
                    id TEXT PRIMARY KEY,
                    created_at_ms INTEGER,
                    payload_json TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    name TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    applied_at_ms INTEGER NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_items (
                    cid TEXT PRIMARY KEY,
                    queue_name TEXT NOT NULL DEFAULT 'main',
                    state TEXT NOT NULL,
                    plan_name TEXT,
                    task_name TEXT NOT NULL,
                    trace_id TEXT,
                    trace_label TEXT,
                    source TEXT,
                    priority INTEGER DEFAULT 0,
                    position INTEGER,
                    enqueued_at_ms INTEGER NOT NULL,
                    delay_until_ms INTEGER,
                    leased_by TEXT,
                    lease_token TEXT,
                    lease_expires_at_ms INTEGER,
                    attempts INTEGER DEFAULT 0,
                    max_attempts INTEGER DEFAULT 1,
                    payload_json TEXT NOT NULL,
                    initial_context_json TEXT,
                    tasklet_json TEXT NOT NULL,
                    last_error TEXT,
                    updated_at_ms INTEGER NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_queue_items_ready "
                "ON queue_items(queue_name, state, priority, position, enqueued_at_ms)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_queue_items_leases "
                "ON queue_items(state, lease_expires_at_ms)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_queue_items_trace ON queue_items(trace_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_queue_items_plan_task ON queue_items(plan_name, task_name)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_leases (
                    worker_id TEXT PRIMARY KEY,
                    queue_name TEXT NOT NULL,
                    heartbeat_at_ms INTEGER NOT NULL,
                    expires_at_ms INTEGER NOT NULL,
                    metadata_json TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_generations (
                    generation_id TEXT PRIMARY KEY,
                    created_at_ms INTEGER NOT NULL,
                    reason TEXT,
                    packages_json TEXT,
                    payload_json TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS reload_operations (
                    reload_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    mode TEXT,
                    package_id TEXT,
                    created_at_ms INTEGER NOT NULL,
                    finished_at_ms INTEGER,
                    payload_json TEXT
                )
                """
            )
            cur.execute(
                """
                INSERT INTO schema_migrations (name, version, applied_at_ms)
                VALUES ('run_store_schema', 1, ?)
                ON CONFLICT(name) DO UPDATE SET
                    version=MAX(version, excluded.version)
                """,
                (int(time.time() * 1000),),
            )
            cur.execute(
                """
                INSERT INTO schema_migrations (name, version, applied_at_ms)
                VALUES ('v6_recoverable_queue', 1, ?)
                ON CONFLICT(name) DO NOTHING
                """,
                (int(time.time() * 1000),),
            )
            self._conn.commit()

    def backfill_observability(self) -> Dict[str, Any]:
        """Populate additive V5 observability indexes from existing run data."""

        with self._lock:
            now_ms = int(time.time() * 1000)
            runs = self._conn.execute("SELECT * FROM runs").fetchall()
            for row in runs:
                trace_id = row["trace_id"] or row["cid"]
                self._conn.execute(
                    """
                    INSERT INTO trace_index (trace_id, cid, status, plan_name, task_name, updated_at_ms)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(trace_id) DO UPDATE SET
                        cid=excluded.cid,
                        status=excluded.status,
                        plan_name=excluded.plan_name,
                        task_name=excluded.task_name,
                        updated_at_ms=excluded.updated_at_ms
                    """,
                    (trace_id, row["cid"], row["status"], row["plan_name"], row["task_name"], row["updated_at_ms"]),
                )

            self._conn.execute("DELETE FROM action_metrics")
            for row in self._conn.execute(
                """
                SELECT action,
                       COUNT(*) AS count,
                       SUM(CASE WHEN ok = 1 THEN 1 ELSE 0 END) AS ok_count,
                       SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS failed_count,
                       COALESCE(SUM(duration_ms), 0) AS duration_ms_total
                FROM action_results
                GROUP BY action
                """
            ).fetchall():
                self._conn.execute(
                    """
                    INSERT INTO action_metrics (action, count, ok_count, failed_count, duration_ms_total, updated_at_ms)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["action"] or "unknown",
                        int(row["count"] or 0),
                        int(row["ok_count"] or 0),
                        int(row["failed_count"] or 0),
                        int(row["duration_ms_total"] or 0),
                        now_ms,
                    ),
                )

            self._conn.execute("DELETE FROM backend_metrics")
            for row in self._conn.execute(
                """
                SELECT backend,
                       COUNT(*) AS count,
                       SUM(CASE WHEN ok = 1 THEN 1 ELSE 0 END) AS ok_count,
                       SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS failed_count
                FROM action_results
                GROUP BY backend
                """
            ).fetchall():
                fallback_count = 0
                payload_rows = self._conn.execute(
                    "SELECT payload_json FROM action_results WHERE COALESCE(backend, 'none') = ?",
                    (row["backend"] or "none",),
                ).fetchall()
                for payload_row in payload_rows:
                    try:
                        fallback_count += len(json.loads(payload_row["payload_json"]).get("fallbacks") or [])
                    except Exception:
                        pass
                self._conn.execute(
                    """
                    INSERT INTO backend_metrics (backend, count, ok_count, failed_count, fallback_count, updated_at_ms)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["backend"] or "none",
                        int(row["count"] or 0),
                        int(row["ok_count"] or 0),
                        int(row["failed_count"] or 0),
                        fallback_count,
                        now_ms,
                    ),
                )
            self._conn.commit()
            return {"status": "success", "runs_indexed": len(runs)}

    def list_migrations(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, version, applied_at_ms FROM schema_migrations ORDER BY name"
            ).fetchall()
            return [dict(row) for row in rows]

    def migration_status(self, legacy_db_path: Path | None = None) -> Dict[str, Any]:
        applied = self.list_migrations()
        expected = ["run_store_schema", "v6_recoverable_queue"]
        applied_names = {row["name"] for row in applied}
        pending = [name for name in expected if name not in applied_names]
        payload = {
            "status": "pending" if pending else "success",
            "db_path": str(self._db_path),
            "run_store_schema_version": max(
                [int(row.get("version") or 0) for row in applied if row.get("name") == "run_store_schema"] or [0]
            ),
            "applied": applied,
            "pending": pending,
        }
        if legacy_db_path is not None:
            legacy = Path(legacy_db_path)
            payload["legacy_db_path"] = str(legacy)
            payload["legacy_db_exists"] = legacy.is_file()
        return payload

    def migration_plan(self, legacy_db_path: Path | None = None) -> Dict[str, Any]:
        status = self.migration_status(legacy_db_path=legacy_db_path)
        steps = []
        if status.get("pending"):
            steps.append({"name": "apply_schema_migrations", "status": "pending"})
        if status.get("legacy_db_exists"):
            steps.append({"name": "migrate_legacy_run_store", "status": "available"})
        steps.append({"name": "backfill_observability", "status": "available"})
        return {"status": "success", "db_path": str(self._db_path), "steps": steps, "current": status}

    def apply_migrations(self, legacy_db_path: Path | None = None) -> Dict[str, Any]:
        # _init_db is intentionally idempotent and additive.
        self._init_db()
        result: Dict[str, Any] = {
            "status": "success",
            "db_path": str(self._db_path),
            "schema": self.migration_status(legacy_db_path=legacy_db_path),
        }
        if legacy_db_path is not None:
            result["legacy"] = self.migrate_from_legacy(legacy_db_path)
        result["backfill"] = self.backfill_observability()
        return result

    def record_runtime_generation(
        self,
        *,
        generation_id: str,
        reason: str,
        packages: List[str] | None = None,
        payload: Dict[str, Any] | None = None,
    ) -> None:
        now_ms = int(time.time() * 1000)
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO runtime_generations (
                    generation_id, created_at_ms, reason, packages_json, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    generation_id,
                    now_ms,
                    reason,
                    json.dumps(packages or [], ensure_ascii=False),
                    json.dumps(payload or {}, ensure_ascii=False),
                ),
            )
            self._conn.commit()

    def record_reload_operation(self, payload: Dict[str, Any]) -> None:
        reload_id = str(payload.get("reload_id") or f"reload-{uuid.uuid4().hex[:12]}")
        now_ms = int(time.time() * 1000)
        finished = payload.get("finished_at_ms")
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO reload_operations (
                    reload_id, status, mode, package_id, created_at_ms, finished_at_ms, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reload_id,
                    payload.get("status") or "unknown",
                    payload.get("mode"),
                    payload.get("package_id"),
                    int(payload.get("created_at_ms") or now_ms),
                    int(finished) if finished else None,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            self._conn.commit()

    def list_reload_operations(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM reload_operations ORDER BY created_at_ms DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            return [_loads_json(row["payload_json"]) for row in rows]

    def queue_enqueue(self, record: Dict[str, Any], *, index: int | None = None) -> Dict[str, Any]:
        now_ms = int(time.time() * 1000)
        queue_name = str(record.get("queue_name") or "main")
        state = str(record.get("state") or "ready")
        delay_until_ms = record.get("delay_until_ms")
        if delay_until_ms and int(delay_until_ms) > now_ms:
            state = "delayed"
        with self._lock:
            if index is None:
                row = self._conn.execute(
                    "SELECT COALESCE(MAX(position), -1) AS pos FROM queue_items WHERE queue_name = ? AND state IN ('ready','delayed')",
                    (queue_name,),
                ).fetchone()
                position = int(row["pos"] or -1) + 1
            else:
                position = max(0, int(index))
                self._conn.execute(
                    """
                    UPDATE queue_items
                    SET position = COALESCE(position, 0) + 1
                    WHERE queue_name = ? AND state IN ('ready','delayed') AND COALESCE(position, 0) >= ?
                    """,
                    (queue_name, position),
                )

            payload_json = _safe_json(record.get("payload") or {})
            initial_context_json = _safe_json(record.get("initial_context") or {})
            tasklet_json = _safe_json(record.get("tasklet") or {})
            enqueued_at_ms = int(record.get("enqueued_at_ms") or now_ms)
            cid = str(record["cid"])
            self._conn.execute(
                """
                INSERT INTO queue_items (
                    cid, queue_name, state, plan_name, task_name, trace_id, trace_label, source,
                    priority, position, enqueued_at_ms, delay_until_ms, leased_by, lease_token,
                    lease_expires_at_ms, attempts, max_attempts, payload_json, initial_context_json,
                    tasklet_json, last_error, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(cid) DO UPDATE SET
                    queue_name=excluded.queue_name,
                    state=excluded.state,
                    plan_name=excluded.plan_name,
                    task_name=excluded.task_name,
                    trace_id=excluded.trace_id,
                    trace_label=excluded.trace_label,
                    source=excluded.source,
                    priority=excluded.priority,
                    position=excluded.position,
                    enqueued_at_ms=excluded.enqueued_at_ms,
                    delay_until_ms=excluded.delay_until_ms,
                    leased_by=NULL,
                    lease_token=NULL,
                    lease_expires_at_ms=NULL,
                    payload_json=excluded.payload_json,
                    initial_context_json=excluded.initial_context_json,
                    tasklet_json=excluded.tasklet_json,
                    last_error=NULL,
                    updated_at_ms=excluded.updated_at_ms
                """,
                (
                    cid,
                    queue_name,
                    state,
                    record.get("plan_name"),
                    record.get("task_name"),
                    record.get("trace_id"),
                    record.get("trace_label"),
                    record.get("source"),
                    int(record.get("priority") or 0),
                    position,
                    enqueued_at_ms,
                    int(delay_until_ms) if delay_until_ms else None,
                    int(record.get("max_attempts") or 1),
                    payload_json,
                    initial_context_json,
                    tasklet_json,
                    now_ms,
                ),
            )
            self._conn.commit()
            return {"status": "success", "cid": cid, "state": state, "position": position}

    def queue_promote_due(self, *, queue_name: str = "main", now_ms: int | None = None) -> int:
        now_ms = int(now_ms or time.time() * 1000)
        with self._lock:
            cur = self._conn.execute(
                """
                UPDATE queue_items
                SET state='ready', delay_until_ms=NULL, updated_at_ms=?
                WHERE queue_name=? AND state='delayed' AND delay_until_ms IS NOT NULL AND delay_until_ms <= ?
                """,
                (now_ms, queue_name, now_ms),
            )
            self._conn.commit()
            return int(cur.rowcount or 0)

    def queue_claim_ready(self, *, worker_id: str, queue_name: str = "main", lease_ttl_ms: int = 3600000) -> Dict[str, Any] | None:
        now_ms = int(time.time() * 1000)
        lease_token = uuid.uuid4().hex
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    """
                    UPDATE queue_items
                    SET state='ready', delay_until_ms=NULL, updated_at_ms=?
                    WHERE queue_name=? AND state='delayed' AND delay_until_ms IS NOT NULL AND delay_until_ms <= ?
                    """,
                    (now_ms, queue_name, now_ms),
                )
                row = self._conn.execute(
                    """
                    SELECT * FROM queue_items
                    WHERE queue_name = ? AND state = 'ready'
                    ORDER BY priority ASC, position ASC, enqueued_at_ms ASC
                    LIMIT 1
                    """,
                    (queue_name,),
                ).fetchone()
                if not row:
                    self._conn.commit()
                    return None
                expires_at = now_ms + int(lease_ttl_ms)
                attempts = int(row["attempts"] or 0) + 1
                cur = self._conn.execute(
                    """
                    UPDATE queue_items
                    SET state='leased', leased_by=?, lease_token=?, lease_expires_at_ms=?,
                        attempts=?, updated_at_ms=?
                    WHERE cid=? AND state='ready'
                    """,
                    (worker_id, lease_token, expires_at, attempts, now_ms, row["cid"]),
                )
                if int(cur.rowcount or 0) != 1:
                    self._conn.rollback()
                    return None
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO worker_leases (worker_id, queue_name, heartbeat_at_ms, expires_at_ms, metadata_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (worker_id, queue_name, now_ms, expires_at, json.dumps({"claimed": row["cid"]}, ensure_ascii=False)),
                )
                self._conn.commit()
                claimed = dict(row)
                claimed["state"] = "leased"
                claimed["leased_by"] = worker_id
                claimed["lease_token"] = lease_token
                claimed["lease_expires_at_ms"] = expires_at
                claimed["attempts"] = attempts
                return self._decode_queue_row(claimed)
            except Exception:
                self._conn.rollback()
                raise

    def queue_ack(self, cid: str, lease_token: str | None = None) -> bool:
        return self._queue_set_terminal(cid, "completed", lease_token=lease_token)

    def queue_drop(self, cid: str, lease_token: str | None = None, *, reason: str | None = None) -> bool:
        return self._queue_set_terminal(cid, "dropped", lease_token=lease_token, reason=reason)

    def queue_abandon(self, cid: str, *, reason: str | None = None) -> bool:
        return self._queue_set_terminal(cid, "abandoned", reason=reason)

    def _queue_set_terminal(
        self,
        cid: str,
        state: str,
        *,
        lease_token: str | None = None,
        reason: str | None = None,
    ) -> bool:
        now_ms = int(time.time() * 1000)
        with self._lock:
            params: List[Any] = [state, None, None, None, reason, now_ms, cid]
            token_clause = ""
            if lease_token:
                token_clause = " AND state='leased' AND lease_token = ?"
                params.append(lease_token)
            else:
                token_clause = " AND state IN ('ready','delayed')"
            cur = self._conn.execute(
                f"""
                UPDATE queue_items
                SET state=?, leased_by=?, lease_token=?, lease_expires_at_ms=?, last_error=?, updated_at_ms=?
                WHERE cid=?{token_clause}
                """,
                params,
            )
            self._conn.commit()
            return bool(cur.rowcount)

    def queue_recover_expired_leases(self, *, queue_name: str = "main", now_ms: int | None = None) -> Dict[str, Any]:
        now_ms = int(now_ms or time.time() * 1000)
        recovered: List[str] = []
        abandoned: List[str] = []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT cid, attempts, max_attempts FROM queue_items
                WHERE queue_name=? AND state='leased' AND lease_expires_at_ms IS NOT NULL AND lease_expires_at_ms <= ?
                """,
                (queue_name, now_ms),
            ).fetchall()
            for row in rows:
                cid = row["cid"]
                if int(row["attempts"] or 0) < int(row["max_attempts"] or 1):
                    self._conn.execute(
                        """
                        UPDATE queue_items
                        SET state='ready', leased_by=NULL, lease_token=NULL, lease_expires_at_ms=NULL, updated_at_ms=?
                        WHERE cid=?
                        """,
                        (now_ms, cid),
                    )
                    recovered.append(cid)
                else:
                    self._conn.execute(
                        """
                        UPDATE queue_items
                        SET state='abandoned', leased_by=NULL, lease_token=NULL, lease_expires_at_ms=NULL,
                            last_error='lease expired', updated_at_ms=?
                        WHERE cid=?
                        """,
                        (now_ms, cid),
                    )
                    self._mark_run_abandoned(cid, now_ms, "queue lease expired")
                    abandoned.append(cid)
            self._conn.commit()
        return {"status": "success", "recovered": recovered, "abandoned": abandoned}

    def queue_list(self, *, state: str = "ready", queue_name: str = "main", limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            if state == "ready":
                self.queue_promote_due(queue_name=queue_name)
            rows = self._conn.execute(
                """
                SELECT * FROM queue_items
                WHERE queue_name=? AND state=?
                ORDER BY priority ASC, position ASC, enqueued_at_ms ASC
                LIMIT ?
                """,
                (queue_name, state, max(1, int(limit))),
            ).fetchall()
            return [self._decode_queue_row(dict(row)) for row in rows]

    def queue_all_active(self, *, queue_name: str = "main", limit: int = 500) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM queue_items
                WHERE queue_name=? AND state IN ('ready','delayed','leased')
                ORDER BY state, priority ASC, position ASC, enqueued_at_ms ASC
                LIMIT ?
                """,
                (queue_name, max(1, int(limit))),
            ).fetchall()
            return [self._decode_queue_row(dict(row)) for row in rows]

    def queue_overview(self, *, queue_name: str = "main") -> Dict[str, Any]:
        now_ms = int(time.time() * 1000)
        with self._lock:
            self.queue_promote_due(queue_name=queue_name, now_ms=now_ms)
            rows = self._conn.execute(
                "SELECT state, COUNT(*) AS cnt FROM queue_items WHERE queue_name=? GROUP BY state",
                (queue_name,),
            ).fetchall()
            counts = {row["state"]: int(row["cnt"] or 0) for row in rows}
            waits = [
                max(0.0, (now_ms - int(row["enqueued_at_ms"] or now_ms)) / 1000.0)
                for row in self._conn.execute(
                    "SELECT enqueued_at_ms FROM queue_items WHERE queue_name=? AND state='ready'",
                    (queue_name,),
                ).fetchall()
            ]
        avg_wait = float(sum(waits) / len(waits)) if waits else 0.0
        return {
            "ready_length": counts.get("ready", 0),
            "delayed_length": counts.get("delayed", 0),
            "leased_length": counts.get("leased", 0),
            "completed_length": counts.get("completed", 0),
            "abandoned_length": counts.get("abandoned", 0),
            "avg_wait_sec": avg_wait,
        }

    def queue_remove(self, cid: str) -> bool:
        return self.queue_drop(cid, reason="removed")

    def queue_clear(self, *, queue_name: str = "main") -> int:
        now_ms = int(time.time() * 1000)
        with self._lock:
            cur = self._conn.execute(
                """
                UPDATE queue_items
                SET state='dropped', last_error='cleared', updated_at_ms=?
                WHERE queue_name=? AND state IN ('ready','delayed')
                """,
                (now_ms, queue_name),
            )
            self._conn.commit()
            return int(cur.rowcount or 0)

    def queue_move_to_position(self, cid: str, position: int, *, queue_name: str = "main") -> bool:
        position = max(0, int(position))
        with self._lock:
            row = self._conn.execute(
                "SELECT cid FROM queue_items WHERE cid=? AND queue_name=? AND state IN ('ready','delayed')",
                (cid, queue_name),
            ).fetchone()
            if not row:
                return False
            self._conn.execute(
                """
                UPDATE queue_items
                SET position = COALESCE(position, 0) + 1
                WHERE queue_name=? AND state IN ('ready','delayed') AND COALESCE(position, 0) >= ? AND cid <> ?
                """,
                (queue_name, position, cid),
            )
            self._conn.execute(
                "UPDATE queue_items SET position=?, updated_at_ms=? WHERE cid=?",
                (position, int(time.time() * 1000), cid),
            )
            self._normalize_queue_positions(queue_name)
            self._conn.commit()
            return True

    def queue_reorder(self, cid_order: List[str], *, queue_name: str = "main") -> bool:
        with self._lock:
            rows = self._conn.execute(
                "SELECT cid FROM queue_items WHERE queue_name=? AND state IN ('ready','delayed')",
                (queue_name,),
            ).fetchall()
            known = [row["cid"] for row in rows]
            order = [cid for cid in cid_order if cid in known]
            order.extend(cid for cid in known if cid not in order)
            now_ms = int(time.time() * 1000)
            for index, cid in enumerate(order):
                self._conn.execute(
                    "UPDATE queue_items SET position=?, updated_at_ms=? WHERE cid=?",
                    (index, now_ms, cid),
                )
            self._conn.commit()
            return True

    def queue_recovery_status(self, *, queue_name: str = "main") -> Dict[str, Any]:
        now_ms = int(time.time() * 1000)
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM queue_items
                WHERE queue_name=? AND (
                    state IN ('ready','delayed')
                    OR (state='leased' AND lease_expires_at_ms IS NOT NULL AND lease_expires_at_ms <= ?)
                )
                ORDER BY state, updated_at_ms ASC
                """,
                (queue_name, now_ms),
            ).fetchall()
            items = [self._decode_queue_row(dict(row)) for row in rows]
        return {
            "status": "success",
            "queue_name": queue_name,
            "recoverable_count": len([item for item in items if item.get("state") in {"ready", "delayed"}]),
            "stale_leased_count": len([item for item in items if item.get("state") == "leased"]),
            "items": items,
        }

    def queue_abandon_stale(self, *, queue_name: str = "main") -> Dict[str, Any]:
        status = self.queue_recovery_status(queue_name=queue_name)
        abandoned = []
        for item in status.get("items", []):
            if item.get("state") == "leased":
                cid = item.get("cid")
                if cid and self.queue_abandon(cid, reason="abandoned stale lease"):
                    abandoned.append(cid)
        return {"status": "success", "abandoned": abandoned}

    def _normalize_queue_positions(self, queue_name: str) -> None:
        rows = self._conn.execute(
            """
            SELECT cid FROM queue_items
            WHERE queue_name=? AND state IN ('ready','delayed')
            ORDER BY priority ASC, position ASC, enqueued_at_ms ASC
            """,
            (queue_name,),
        ).fetchall()
        for index, row in enumerate(rows):
            self._conn.execute("UPDATE queue_items SET position=? WHERE cid=?", (index, row["cid"]))

    def _decode_queue_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        row["payload"] = _loads_json(row.pop("payload_json", None))
        row["initial_context"] = _loads_json(row.pop("initial_context_json", None))
        row["tasklet"] = _loads_json(row.pop("tasklet_json", None))
        row["enqueued_at"] = (int(row.get("enqueued_at_ms") or 0) / 1000.0) if row.get("enqueued_at_ms") else None
        row["delay_until"] = (int(row.get("delay_until_ms") or 0) / 1000.0) if row.get("delay_until_ms") else None
        return row

    def _mark_run_abandoned(self, cid: str, ts_ms: int, reason: str) -> None:
        self._conn.execute(
            """
            INSERT INTO runs (cid, status, updated_at_ms, final_result_json)
            VALUES (?, 'abandoned', ?, ?)
            ON CONFLICT(cid) DO UPDATE SET
                status=CASE WHEN runs.status IN ('success','error','failed','timeout','cancelled') THEN runs.status ELSE 'abandoned' END,
                updated_at_ms=excluded.updated_at_ms,
                final_result_json=COALESCE(runs.final_result_json, excluded.final_result_json)
            """,
            (cid, ts_ms, json.dumps({"reason": reason}, ensure_ascii=False)),
        )

    def apply_event(self, name: str, payload: Dict[str, Any], timestamp_ms: int):
        cid = payload.get("cid")
        if not cid:
            return
        lowered = (name or "").lower()
        with self._lock:
            self._apply_event_unlocked(lowered, payload, timestamp_ms)
            self._conn.commit()

    def apply_events_batch(self, events: List[tuple[str, Dict[str, Any], int]]) -> None:
        if not events:
            return
        with self._lock:
            for name, payload, timestamp_ms in events:
                lowered = (name or "").lower()
                if not payload.get("cid"):
                    continue
                try:
                    self._apply_event_unlocked(lowered, payload, int(timestamp_ms))
                except Exception:
                    # Preserve batch progress for independent runs; callers still
                    # get committed critical events that were valid.
                    continue
            self._conn.commit()

    def _apply_event_unlocked(self, lowered: str, payload: Dict[str, Any], timestamp_ms: int) -> None:
        cid = payload.get("cid")
        if not cid:
            return
        if lowered == "queue.enqueued":
            self._upsert_queued(cid, payload, timestamp_ms)
        elif lowered == "task.started":
            self._upsert_started(cid, payload, timestamp_ms)
        elif lowered == "task.finished":
            self._upsert_finished(cid, payload, timestamp_ms)
        elif lowered in {"node.finished", "node.failed"}:
            self._upsert_node_terminal(cid, lowered, payload, timestamp_ms)
            self._record_node_action_payload(cid, payload, timestamp_ms)
            self._insert_resource_sample(cid, payload, timestamp_ms)

    def _get_current_status(self, cid: str) -> Optional[str]:
        row = self._conn.execute("SELECT status FROM runs WHERE cid = ?", (cid,)).fetchone()
        return (row["status"] if row else None)

    @staticmethod
    def _normalize_status(raw: Any) -> str:
        value = str(raw or "").strip().lower()
        if not value:
            return "unknown"
        return value

    def _assert_transition(self, cid: str, next_status: str):
        current = self._get_current_status(cid)
        if current in _TERMINAL_STATUSES:
            raise ValueError(f"Illegal run status transition for {cid}: {current} -> {next_status}")
        allowed = _ALLOWED_TRANSITIONS.get(current, set())
        if next_status not in allowed and next_status not in _TERMINAL_STATUSES:
            raise ValueError(f"Illegal run status transition for {cid}: {current} -> {next_status}")

    def _upsert_queued(self, cid: str, p: Dict[str, Any], ts_ms: int):
        current = self._get_current_status(cid)
        if current in _TERMINAL_STATUSES:
            return
        self._conn.execute(
            """
            INSERT INTO runs (cid, trace_id, trace_label, source, parent_cid, plan_name, task_name, status, updated_at_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?)
            ON CONFLICT(cid) DO UPDATE SET
                trace_id=excluded.trace_id,
                trace_label=excluded.trace_label,
                source=excluded.source,
                parent_cid=excluded.parent_cid,
                plan_name=excluded.plan_name,
                task_name=excluded.task_name,
                status=CASE WHEN runs.status IN ('success','error','failed','timeout','cancelled','abandoned') THEN runs.status ELSE 'queued' END,
                updated_at_ms=excluded.updated_at_ms
            """,
            (
                cid,
                p.get("trace_id"),
                p.get("trace_label"),
                p.get("source"),
                p.get("parent_cid"),
                p.get("plan_name"),
                p.get("task_name"),
                ts_ms,
            ),
        )

    def _upsert_started(self, cid: str, p: Dict[str, Any], ts_ms: int):
        self._assert_transition(cid, "running")
        start_time = p.get("start_time")
        if isinstance(start_time, (int, float)) and start_time < 1e12:
            start_ms = int(start_time * 1000)
        elif isinstance(start_time, (int, float)):
            start_ms = int(start_time)
        else:
            start_ms = ts_ms

        self._conn.execute(
            """
            INSERT INTO runs (cid, trace_id, trace_label, source, parent_cid, plan_name, task_name, status, started_at_ms, queue_wait_ms, updated_at_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?)
            ON CONFLICT(cid) DO UPDATE SET
                trace_id=excluded.trace_id,
                trace_label=excluded.trace_label,
                source=excluded.source,
                parent_cid=excluded.parent_cid,
                plan_name=excluded.plan_name,
                task_name=excluded.task_name,
                status='running',
                started_at_ms=COALESCE(runs.started_at_ms, excluded.started_at_ms),
                queue_wait_ms=COALESCE(excluded.queue_wait_ms, runs.queue_wait_ms),
                updated_at_ms=excluded.updated_at_ms
            """,
            (
                cid,
                p.get("trace_id"),
                p.get("trace_label"),
                p.get("source"),
                p.get("parent_cid"),
                p.get("plan_name"),
                p.get("task_name"),
                start_ms,
                p.get("queue_wait_ms"),
                ts_ms,
            ),
        )

    def _upsert_finished(self, cid: str, p: Dict[str, Any], ts_ms: int):
        next_status = self._normalize_status(p.get("final_status") or p.get("status"))
        if next_status not in _TERMINAL_STATUSES:
            next_status = "error"
        self._assert_transition(cid, next_status)

        end_time = p.get("end_time")
        if isinstance(end_time, (int, float)) and end_time < 1e12:
            end_ms = int(end_time * 1000)
        elif isinstance(end_time, (int, float)):
            end_ms = int(end_time)
        else:
            end_ms = ts_ms

        duration_ms = p.get("duration_ms")
        if duration_ms is None and p.get("duration") is not None:
            try:
                duration_ms = int(float(p.get("duration")) * 1000)
            except Exception:
                duration_ms = None

        final_result_json = None
        if p.get("final_result") is not None:
            try:
                final_result_json = json.dumps(p.get("final_result"), ensure_ascii=False)
            except Exception:
                final_result_json = json.dumps({"raw": str(p.get("final_result"))}, ensure_ascii=False)

        self._conn.execute(
            """
            INSERT INTO runs (cid, trace_id, trace_label, source, parent_cid, plan_name, task_name, status, finished_at_ms, duration_ms, queue_wait_ms, updated_at_ms, final_result_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cid) DO UPDATE SET
                trace_id=COALESCE(excluded.trace_id, runs.trace_id),
                trace_label=COALESCE(excluded.trace_label, runs.trace_label),
                source=COALESCE(excluded.source, runs.source),
                parent_cid=COALESCE(excluded.parent_cid, runs.parent_cid),
                plan_name=COALESCE(excluded.plan_name, runs.plan_name),
                task_name=COALESCE(excluded.task_name, runs.task_name),
                status=excluded.status,
                finished_at_ms=excluded.finished_at_ms,
                duration_ms=COALESCE(excluded.duration_ms, runs.duration_ms),
                queue_wait_ms=COALESCE(excluded.queue_wait_ms, runs.queue_wait_ms),
                updated_at_ms=excluded.updated_at_ms,
                final_result_json=COALESCE(excluded.final_result_json, runs.final_result_json)
            """,
            (
                cid,
                p.get("trace_id"),
                p.get("trace_label"),
                p.get("source"),
                p.get("parent_cid"),
                p.get("plan_name"),
                p.get("task_name"),
                next_status,
                end_ms,
                duration_ms,
                p.get("queue_wait_ms"),
                ts_ms,
                final_result_json,
            ),
        )

    def _upsert_node_terminal(self, cid: str, event_name: str, p: Dict[str, Any], ts_ms: int):
        node_id = p.get("node_id") or p.get("step_name") or "node"
        loop_index = int(p.get("loop_index") or 0)

        end_time = p.get("end_time")
        if isinstance(end_time, (int, float)) and end_time < 1e12:
            end_ms = int(end_time * 1000)
        elif isinstance(end_time, (int, float)):
            end_ms = int(end_time)
        else:
            end_ms = ts_ms

        start_time = p.get("start_time")
        if isinstance(start_time, (int, float)) and start_time < 1e12:
            start_ms = int(start_time * 1000)
        elif isinstance(start_time, (int, float)):
            start_ms = int(start_time)
        else:
            start_ms = end_ms

        status = self._normalize_status(p.get("status") or ("failed" if event_name == "node.failed" else "success"))

        loop_item_json = None
        if p.get("loop_item") is not None:
            try:
                loop_item_json = json.dumps(p.get("loop_item"), ensure_ascii=False)
            except Exception:
                loop_item_json = json.dumps(str(p.get("loop_item")), ensure_ascii=False)

        self._conn.execute(
            """
            INSERT INTO node_terminal_events (
                cid, node_id, node_name, status, start_ms, end_ms, duration_ms, retry_count,
                exception_type, exception_message, loop_index, loop_item_json, source_event, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cid, node_id, loop_index) DO UPDATE SET
                node_name=COALESCE(excluded.node_name, node_terminal_events.node_name),
                status=excluded.status,
                start_ms=COALESCE(node_terminal_events.start_ms, excluded.start_ms),
                end_ms=excluded.end_ms,
                duration_ms=COALESCE(excluded.duration_ms, node_terminal_events.duration_ms),
                retry_count=COALESCE(excluded.retry_count, node_terminal_events.retry_count),
                exception_type=COALESCE(excluded.exception_type, node_terminal_events.exception_type),
                exception_message=COALESCE(excluded.exception_message, node_terminal_events.exception_message),
                loop_item_json=COALESCE(excluded.loop_item_json, node_terminal_events.loop_item_json),
                source_event=excluded.source_event,
                updated_at_ms=excluded.updated_at_ms
            """,
            (
                cid,
                node_id,
                p.get("node_name"),
                status,
                start_ms,
                end_ms,
                p.get("duration_ms"),
                p.get("retry_count"),
                p.get("exception_type"),
                p.get("exception_message"),
                loop_index,
                loop_item_json,
                event_name,
                ts_ms,
            ),
        )

    def _record_node_action_payload(self, cid: str, p: Dict[str, Any], ts_ms: int) -> None:
        node_id = p.get("node_id") or p.get("step_name") or "node"
        loop_index = int(p.get("loop_index") or 0)
        action_result = p.get("action_result")
        if isinstance(action_result, dict):
            action_result.setdefault("node_id", node_id)
            self._insert_action_result(cid, node_id, loop_index, action_result, ts_ms)
            self._write_evidence_files(cid, action_result)
            for evidence in action_result.get("evidence") or []:
                if isinstance(evidence, dict):
                    self._insert_evidence_ref(cid, node_id, evidence, ts_ms)
        policy_decision = p.get("policy_decision")
        if isinstance(policy_decision, dict):
            self._insert_policy_audit(cid, node_id, loop_index, policy_decision, ts_ms)
        for evidence in p.get("evidence") or []:
            if isinstance(evidence, dict):
                self._insert_evidence_ref(cid, node_id, evidence, ts_ms)

    def _insert_resource_sample(self, cid: str, p: Dict[str, Any], ts_ms: int) -> None:
        sample: Dict[str, Any] = {
            "id": f"{cid}:{p.get('node_id') or 'node'}:{ts_ms}",
            "cid": cid,
            "node_id": p.get("node_id") or p.get("step_name"),
            "duration_ms": p.get("duration_ms"),
            "queue_wait_ms": p.get("queue_wait_ms"),
            "resource_tags": p.get("resource_tags") or [],
            "created_at_ms": ts_ms,
        }
        try:
            import os
            import psutil

            proc = psutil.Process(os.getpid())
            sample["process"] = {
                "pid": proc.pid,
                "rss_bytes": proc.memory_info().rss,
                "cpu_percent": proc.cpu_percent(interval=None),
            }
        except Exception:
            sample["process"] = {"available": False}
        self._conn.execute(
            "INSERT OR REPLACE INTO resource_samples (id, created_at_ms, payload_json) VALUES (?, ?, ?)",
            (sample["id"], ts_ms, json.dumps(sample, ensure_ascii=False)),
        )

    def _insert_action_result(
        self,
        cid: str,
        node_id: str,
        loop_index: int,
        payload: Dict[str, Any],
        ts_ms: int,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO action_results (
                cid, node_id, loop_index, action, backend, ok, duration_ms, payload_json, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cid, node_id, loop_index) DO UPDATE SET
                action=excluded.action,
                backend=excluded.backend,
                ok=excluded.ok,
                duration_ms=excluded.duration_ms,
                payload_json=excluded.payload_json,
                updated_at_ms=excluded.updated_at_ms
            """,
            (
                cid,
                node_id,
                loop_index,
                payload.get("action"),
                payload.get("backend"),
                1 if payload.get("ok") else 0,
                payload.get("duration_ms"),
                json.dumps(payload, ensure_ascii=False),
                ts_ms,
            ),
        )

    def _insert_policy_audit(
        self,
        cid: str,
        node_id: str,
        loop_index: int,
        payload: Dict[str, Any],
        ts_ms: int,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO policy_audit (
                cid, node_id, loop_index, action, profile, decision, reason, capabilities_json, payload_json, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cid, node_id, loop_index) DO UPDATE SET
                action=excluded.action,
                profile=excluded.profile,
                decision=excluded.decision,
                reason=excluded.reason,
                capabilities_json=excluded.capabilities_json,
                payload_json=excluded.payload_json,
                updated_at_ms=excluded.updated_at_ms
            """,
            (
                cid,
                node_id,
                loop_index,
                payload.get("action"),
                payload.get("profile"),
                payload.get("decision"),
                payload.get("reason"),
                json.dumps(payload.get("capabilities") or payload.get("capabilities_used") or [], ensure_ascii=False),
                json.dumps(payload, ensure_ascii=False),
                ts_ms,
            ),
        )

    def _insert_evidence_ref(self, cid: str, node_id: str | None, payload: Dict[str, Any], ts_ms: int) -> None:
        evidence_id = str(payload.get("id") or f"{cid}:{node_id or 'run'}:{payload.get('kind') or payload.get('type') or ts_ms}:{payload.get('path') or len(json.dumps(payload, ensure_ascii=False))}")
        self._conn.execute(
            """
            INSERT OR REPLACE INTO evidence_refs (id, cid, node_id, kind, path, payload_json, updated_at_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                cid,
                node_id,
                payload.get("kind") or payload.get("type"),
                payload.get("path"),
                json.dumps(payload, ensure_ascii=False),
                ts_ms,
            ),
        )

    def _write_evidence_files(self, cid: str, action_result: Dict[str, Any]) -> None:
        evidence_dir = self._db_path.parent / "evidence" / cid
        try:
            evidence_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = evidence_dir / "manifest.json"
            manifest = {"cid": cid, "schema_version": 1, "action_results": "action-results.jsonl"}
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            with (evidence_dir / "action-results.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(action_result, ensure_ascii=False) + "\n")
            for child in ("captures", "ocr", "backend", "locators", "yolo", "window"):
                (evidence_dir / child).mkdir(exist_ok=True)
        except Exception:
            # Evidence files are diagnostic aids; SQLite remains authoritative.
            pass

    def get_run(self, cid: str) -> Dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE cid = ?", (cid,)).fetchone()
            if not row:
                return {}
            run = dict(row)
            final_result_raw = run.pop("final_result_json", None)
            if final_result_raw:
                try:
                    run["final_result"] = json.loads(final_result_raw)
                except Exception:
                    run["final_result"] = {"raw": final_result_raw}
            nodes = self._conn.execute(
                """
                SELECT * FROM node_terminal_events
                WHERE cid = ?
                ORDER BY updated_at_ms ASC
                """,
                (cid,),
            ).fetchall()
            run["nodes"] = [self._row_to_node(dict(r)) for r in nodes]
            run["action_results"] = self.list_action_results(cid)
            run["policy_decisions"] = self.list_policy_audit(cid)
            run["evidence"] = self.list_evidence_refs(cid)
            return run

    def list_runs(
        self,
        limit: int = 50,
        plan_name: Optional[str] = None,
        task_name: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            clauses: List[str] = []
            params: List[Any] = []
            if plan_name:
                clauses.append("plan_name = ?")
                params.append(plan_name)
            if task_name:
                clauses.append("task_name = ?")
                params.append(task_name)
            if status:
                clauses.append("status = ?")
                params.append(str(status).lower())
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            query = f"SELECT * FROM runs {where} ORDER BY updated_at_ms DESC LIMIT ?"
            params.append(max(1, int(limit)))
            rows = self._conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def migrate_from_legacy(self, legacy_db_path: Path) -> Dict[str, Any]:
        legacy = Path(legacy_db_path)
        if not legacy.is_file() or legacy.resolve() == self._db_path.resolve():
            return {"status": "skipped", "reason": "legacy database not found or same path"}
        with self._lock:
            legacy_conn = None
            try:
                legacy_conn = sqlite3.connect(str(legacy), timeout=2.0)
                legacy_conn.row_factory = sqlite3.Row
                copied = {
                    "runs": self._copy_legacy_table(legacy_conn, "runs"),
                    "node_terminal_events": self._copy_legacy_table(legacy_conn, "node_terminal_events"),
                }
                self._conn.commit()
                return {"status": "success", "legacy_path": str(legacy), "copied": copied}
            except Exception as exc:  # noqa: BLE001
                return {"status": "error", "legacy_path": str(legacy), "message": str(exc)}
            finally:
                if legacy_conn is not None:
                    legacy_conn.close()

    def _copy_legacy_table(self, legacy_conn: sqlite3.Connection, table_name: str) -> int:
        if not self._table_exists(legacy_conn, table_name):
            return 0
        source_columns = self._table_columns(legacy_conn, table_name)
        target_columns = self._table_columns(self._conn, table_name)
        columns = [column for column in source_columns if column in target_columns]
        if not columns:
            return 0

        quoted_columns = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        rows = legacy_conn.execute(f"SELECT {quoted_columns} FROM {table_name}").fetchall()
        if not rows:
            return 0
        self._conn.executemany(
            f"INSERT OR IGNORE INTO {table_name} ({quoted_columns}) VALUES ({placeholders})",
            [[row[column] for column in columns] for row in rows],
        )
        return len(rows)

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (table_name,),
        ).fetchone()
        return bool(row)

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table_name: str) -> List[str]:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]

    def record_workspace_packages(self, packages: List[Dict[str, Any]]) -> None:
        now_ms = int(time.time() * 1000)
        with self._lock:
            for item in packages:
                self._conn.execute(
                    """
                    INSERT INTO workspace_packages (
                        id, name, version, enabled, source, content_hash, validation_status, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        version=excluded.version,
                        enabled=excluded.enabled,
                        source=excluded.source,
                        content_hash=excluded.content_hash,
                        validation_status=excluded.validation_status,
                        updated_at_ms=excluded.updated_at_ms
                    """,
                    (
                        item.get("id"),
                        item.get("name"),
                        item.get("version"),
                        1 if item.get("enabled") else 0,
                        item.get("source") or item.get("source_path"),
                        item.get("content_hash"),
                        item.get("validation_status"),
                        now_ms,
                    ),
                )
            self._conn.commit()

    def record_capability_snapshot(self, snapshot_id: str, payload: Dict[str, Any]) -> None:
        self._record_json("capability_snapshots", snapshot_id, payload)

    def record_action_result(self, cid: str, node_id: str, payload: Dict[str, Any], *, loop_index: int = 0) -> None:
        with self._lock:
            self._insert_action_result(cid, node_id, int(loop_index or 0), payload, int(time.time() * 1000))
            self._conn.commit()

    def record_policy_audit(self, cid: str, node_id: str, payload: Dict[str, Any], *, loop_index: int = 0) -> None:
        with self._lock:
            self._insert_policy_audit(cid, node_id, int(loop_index or 0), payload, int(time.time() * 1000))
            self._conn.commit()

    def record_evidence_ref(self, cid: str, node_id: str | None, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._insert_evidence_ref(cid, node_id, payload, int(time.time() * 1000))
            self._conn.commit()

    def list_action_results(self, cid: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM action_results WHERE cid = ? ORDER BY updated_at_ms ASC",
                (cid,),
            ).fetchall()
            return [_loads_json(row["payload_json"]) for row in rows]

    def list_policy_audit(self, cid: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM policy_audit WHERE cid = ? ORDER BY updated_at_ms ASC",
                (cid,),
            ).fetchall()
            return [_loads_json(row["payload_json"]) for row in rows]

    def list_evidence_refs(self, cid: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM evidence_refs WHERE cid = ? ORDER BY updated_at_ms ASC",
                (cid,),
            ).fetchall()
            return [_loads_json(row["payload_json"]) for row in rows]

    def evidence_manifest(self, cid: str) -> Dict[str, Any]:
        refs = self.list_evidence_refs(cid)
        domains: Dict[str, List[Dict[str, Any]]] = {
            "captures": [],
            "locators": [],
            "ocr": [],
            "yolo": [],
            "window": [],
            "backend": [],
            "other": [],
        }
        for ref in refs:
            kind = str(ref.get("kind") or ref.get("type") or "other").lower()
            if kind in {"capture", "captures"}:
                domains["captures"].append(ref)
            elif kind in {"locator", "locators"}:
                domains["locators"].append(ref)
            elif kind == "ocr":
                domains["ocr"].append(ref)
            elif kind == "yolo":
                domains["yolo"].append(ref)
            elif kind == "window":
                domains["window"].append(ref)
            elif kind == "backend":
                domains["backend"].append(ref)
            else:
                domains["other"].append(ref)
        return {"cid": cid, "schema_version": 2, **domains, "refs": refs}

    def list_locators(self, cid: str) -> List[Dict[str, Any]]:
        manifest = self.evidence_manifest(cid)
        locators = [_normalize_locator_ref(item) for item in (manifest.get("locators") or [])]
        for action_result in self.list_action_results(cid):
            data = action_result.get("data") or {}
            if isinstance(data.get("locator"), dict):
                locators.append(_normalize_locator_ref({"kind": "locator", "payload": data["locator"], "source": action_result.get("action")}))
            for item in data.get("locators") or []:
                if isinstance(item, dict):
                    locators.append(_normalize_locator_ref({"kind": "locator", "payload": item, "source": action_result.get("action")}))
            value = (data.get("value") or {})
            if isinstance(value, dict):
                if isinstance(value.get("locator"), dict):
                    locators.append(_normalize_locator_ref({"kind": "locator", "payload": value["locator"], "source": action_result.get("action")}))
                for item in value.get("locators") or []:
                    if isinstance(item, dict):
                        locators.append(_normalize_locator_ref({"kind": "locator", "payload": item, "source": action_result.get("action")}))
        return locators

    def debug_report(self, cid: str) -> Dict[str, Any]:
        run = self.get_run(cid)
        if not run:
            return {"status": "error", "cid": cid, "message": "Run not found."}
        action_by_node = {
            str(item.get("node_id")): item
            for item in run.get("action_results", [])
            if item.get("node_id") is not None
        }
        failed_nodes = []
        for node in run.get("nodes", []):
            if str(node.get("status")).lower() in {"success", "skipped"}:
                continue
            row = dict(node)
            action_result = action_by_node.get(str(row.get("node_id")))
            if action_result:
                row["action_result"] = action_result
                rendered = (action_result.get("data") or {}).get("rendered_params")
                if isinstance(rendered, dict):
                    row["rendered_params"] = rendered
            failed_nodes.append(row)
        return {
            "status": "success",
            "cid": cid,
            "summary": {
                "plan_name": run.get("plan_name"),
                "task_name": run.get("task_name"),
                "status": run.get("status"),
                "duration_ms": run.get("duration_ms"),
            },
            "failed_nodes": failed_nodes,
            "rendered_params": [
                (item.get("data") or {}).get("rendered_params")
                for item in run.get("action_results", [])
                if isinstance((item.get("data") or {}).get("rendered_params"), dict)
            ],
            "action_results": run.get("action_results") or [],
            "policy_decisions": run.get("policy_decisions") or [],
            "locators": self.list_locators(cid),
            "evidence_manifest": self.evidence_manifest(cid),
        }

    def record_resource_sample(self, payload: Dict[str, Any]) -> None:
        sample_id = str(payload.get("id") or f"resource-{uuid.uuid4().hex[:12]}")
        self._record_json("resource_samples", sample_id, payload)

    def list_resource_samples(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM resource_samples ORDER BY created_at_ms DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            return [_loads_json(row["payload_json"]) for row in rows]

    def record_diagnostic_bundle(self, bundle_id: str, path: str, status: str, summary: Dict[str, Any]) -> None:
        now_ms = int(time.time() * 1000)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO diagnostic_bundles (id, created_at_ms, path, status, summary_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    path=excluded.path,
                    status=excluded.status,
                    summary_json=excluded.summary_json
                """,
                (bundle_id, now_ms, path, status, json.dumps(summary, ensure_ascii=False)),
            )
            self._conn.commit()

    def list_diagnostic_bundles(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM diagnostic_bundles ORDER BY created_at_ms DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            return [self._decode_diagnostic_row(dict(row)) for row in rows]

    def get_diagnostic_bundle(self, bundle_id: str) -> Dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM diagnostic_bundles WHERE id = ?", (bundle_id,)).fetchone()
            return self._decode_diagnostic_row(dict(row)) if row else {}

    def _record_json(self, table: str, item_id: str, payload: Dict[str, Any]) -> None:
        now_ms = int(time.time() * 1000)
        with self._lock:
            self._conn.execute(
                f"INSERT INTO {table} (id, created_at_ms, payload_json) VALUES (?, ?, ?)",
                (item_id, now_ms, json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()

    @staticmethod
    def _decode_diagnostic_row(row: Dict[str, Any]) -> Dict[str, Any]:
        summary_raw = row.get("summary_json")
        if summary_raw:
            try:
                row["summary"] = json.loads(summary_raw)
            except Exception:
                row["summary"] = {"raw": summary_raw}
        row.pop("summary_json", None)
        return row

    def get_metrics_snapshot(self, running_tasks: int = 0) -> Dict[str, Any]:
        with self._lock:
            out = {
                "tasks_started": 0,
                "tasks_finished": 0,
                "tasks_success": 0,
                "tasks_error": 0,
                "tasks_failed": 0,
                "tasks_timeout": 0,
                "tasks_cancelled": 0,
                "tasks_running": int(running_tasks),
                "nodes_total": 0,
                "nodes_succeeded": 0,
                "nodes_failed": 0,
                "nodes_duration_ms_sum": 0.0,
                "nodes_duration_ms_avg": 0.0,
                "updated_at": time.time(),
            }

            total_started = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM runs WHERE started_at_ms IS NOT NULL"
            ).fetchone()["cnt"]
            out["tasks_started"] = int(total_started or 0)

            terminal_rows = self._conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM runs WHERE status IN ('success','error','failed','timeout','cancelled') GROUP BY status"
            ).fetchall()
            finished = 0
            for row in terminal_rows:
                status = row["status"]
                cnt = int(row["cnt"] or 0)
                finished += cnt
                out[f"tasks_{status}"] = cnt
            out["tasks_finished"] = finished

            node_rows = self._conn.execute(
                """
                SELECT status, COUNT(*) AS cnt, COALESCE(SUM(duration_ms), 0.0) AS dur
                FROM node_terminal_events
                WHERE source_event = 'node.finished'
                GROUP BY status
                """
            ).fetchall()
            total_nodes = 0
            duration_sum = 0.0
            for row in node_rows:
                cnt = int(row["cnt"] or 0)
                total_nodes += cnt
                duration_sum += float(row["dur"] or 0.0)
                status = str(row["status"] or "").lower()
                if status == "success":
                    out["nodes_succeeded"] += cnt
                elif status in {"failed", "error"}:
                    out["nodes_failed"] += cnt
            out["nodes_total"] = total_nodes
            out["nodes_duration_ms_sum"] = duration_sum
            out["nodes_duration_ms_avg"] = (duration_sum / total_nodes) if total_nodes > 0 else 0.0
            return out

    @staticmethod
    def _row_to_node(row: Dict[str, Any]) -> Dict[str, Any]:
        loop_item_raw = row.get("loop_item_json")
        loop_item = None
        if loop_item_raw is not None:
            try:
                loop_item = json.loads(loop_item_raw)
            except Exception:
                loop_item = loop_item_raw
        return {
            "node_id": row.get("node_id"),
            "node_name": row.get("node_name"),
            "status": row.get("status"),
            "startMs": row.get("start_ms"),
            "endMs": row.get("end_ms"),
            "duration_ms": row.get("duration_ms"),
            "retry_count": row.get("retry_count"),
            "exception_type": row.get("exception_type"),
            "exception_message": row.get("exception_message"),
            "loop_index": row.get("loop_index"),
            "loop_item": loop_item,
            "source_event": row.get("source_event"),
        }


def _loads_json(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {"value": value}
    except Exception:
        return {"raw": raw}


def _normalize_locator_ref(item: Dict[str, Any]) -> Dict[str, Any]:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    merged = {**payload, **{key: value for key, value in item.items() if key != "payload"}}
    merged.setdefault("kind", "locator")
    return merged


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps({"raw": str(value)}, ensure_ascii=False)

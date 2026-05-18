# -*- coding: utf-8 -*-
"""Read-only observability query service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from packages.aura_core.observability.run_store import RunStore


ERROR_TAXONOMY = [
    "policy_denied",
    "backend_unavailable",
    "action_validation_failed",
    "template_render_failed",
    "dsl_schema_invalid",
    "capture_failed",
    "locator_not_found",
    "ocr_failed",
    "yolo_failed",
    "timeout",
    "dependency_unavailable",
    "unknown_error",
]


class ObservabilityQueryService:
    """Aggregates V4 run/action/policy/evidence data into operational views."""

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path).resolve()
        self.store = RunStore(self.base_path / "logs" / "aura.sqlite3")

    def list_traces(self, *, limit: int = 50) -> dict[str, Any]:
        runs = self.store.list_runs(limit=limit)
        traces = [
            {
                "trace_id": row.get("trace_id") or row.get("cid"),
                "cid": row.get("cid"),
                "trace_label": row.get("trace_label"),
                "plan_name": row.get("plan_name"),
                "task_name": row.get("task_name"),
                "status": row.get("status"),
                "updated_at_ms": row.get("updated_at_ms"),
                "duration_ms": row.get("duration_ms"),
            }
            for row in runs
        ]
        return {"traces": traces}

    def get_trace(self, trace_id: str) -> dict[str, Any]:
        for row in self.store.list_runs(limit=1000):
            if trace_id in {row.get("trace_id"), row.get("cid")}:
                return {"trace_id": trace_id, "run": self.store.get_run(row["cid"])}
        return {"trace_id": trace_id, "run": None}

    def error_summary(self) -> dict[str, Any]:
        counts = {key: 0 for key in ERROR_TAXONOMY}
        examples: dict[str, list[dict[str, Any]]] = {key: [] for key in ERROR_TAXONOMY}
        for row in self.store.list_runs(limit=1000):
            run = self.store.get_run(row["cid"])
            category = self.classify_run(run)
            if category:
                counts[category] += 1
                if len(examples[category]) < 5:
                    examples[category].append(
                        {
                            "cid": run.get("cid"),
                            "trace_id": run.get("trace_id"),
                            "plan_name": run.get("plan_name"),
                            "task_name": run.get("task_name"),
                            "status": run.get("status"),
                        }
                    )
        return {"taxonomy": ERROR_TAXONOMY, "counts": counts, "examples": examples}

    def action_metrics(self) -> dict[str, Any]:
        buckets: dict[str, dict[str, Any]] = {}
        for row in self.store.list_runs(limit=1000):
            for result in self.store.list_action_results(row["cid"]):
                action = result.get("action") or "unknown"
                bucket = buckets.setdefault(action, {"action": action, "count": 0, "ok": 0, "failed": 0, "duration_ms_total": 0})
                bucket["count"] += 1
                if result.get("ok"):
                    bucket["ok"] += 1
                else:
                    bucket["failed"] += 1
                bucket["duration_ms_total"] += int(result.get("duration_ms") or 0)
        for bucket in buckets.values():
            bucket["duration_ms_avg"] = bucket["duration_ms_total"] / bucket["count"] if bucket["count"] else 0
        return {"actions": sorted(buckets.values(), key=lambda item: item["action"])}

    def backend_metrics(self) -> dict[str, Any]:
        buckets: dict[str, dict[str, Any]] = {}
        for row in self.store.list_runs(limit=1000):
            for result in self.store.list_action_results(row["cid"]):
                backend = result.get("backend") or "none"
                bucket = buckets.setdefault(backend, {"backend": backend, "count": 0, "ok": 0, "failed": 0, "fallbacks": 0})
                bucket["count"] += 1
                if result.get("ok"):
                    bucket["ok"] += 1
                else:
                    bucket["failed"] += 1
                bucket["fallbacks"] += len(result.get("fallbacks") or [])
        return {"backends": sorted(buckets.values(), key=lambda item: item["backend"])}

    def service_metrics(self) -> dict[str, Any]:
        buckets: dict[str, dict[str, Any]] = {}
        for row in self.store.list_runs(limit=1000):
            run = self.store.get_run(row["cid"])
            for node in run.get("nodes", []) or []:
                node_name = str(node.get("node_name") or node.get("node_id") or "unknown")
                bucket = buckets.setdefault(node_name, {"service_or_node": node_name, "count": 0, "failed": 0, "duration_ms_total": 0.0})
                bucket["count"] += 1
                if str(node.get("status")).lower() not in {"success", "skipped"}:
                    bucket["failed"] += 1
                bucket["duration_ms_total"] += float(node.get("duration_ms") or 0.0)
        for bucket in buckets.values():
            bucket["duration_ms_avg"] = bucket["duration_ms_total"] / bucket["count"] if bucket["count"] else 0.0
        return {"services": sorted(buckets.values(), key=lambda item: item["service_or_node"])}

    def desktop_metrics(self) -> dict[str, Any]:
        domains = {key: {"domain": key, "count": 0, "failed": 0, "duration_ms_total": 0} for key in ("capture", "ocr", "yolo", "locator", "input")}
        for row in self.store.list_runs(limit=1000):
            for result in self.store.list_action_results(row["cid"]):
                raw = json.dumps(result, ensure_ascii=False).lower()
                domain = "input"
                if "yolo" in raw:
                    domain = "yolo"
                elif "ocr" in raw:
                    domain = "ocr"
                elif "locator" in raw or "bbox" in raw:
                    domain = "locator"
                elif "capture" in raw or "screenshot" in raw:
                    domain = "capture"
                bucket = domains[domain]
                bucket["count"] += 1
                if not result.get("ok"):
                    bucket["failed"] += 1
                bucket["duration_ms_total"] += int(result.get("duration_ms") or 0)
        for bucket in domains.values():
            bucket["failure_rate"] = bucket["failed"] / bucket["count"] if bucket["count"] else 0.0
            bucket["duration_ms_avg"] = bucket["duration_ms_total"] / bucket["count"] if bucket["count"] else 0.0
        return {"desktop": list(domains.values())}

    def resources(self, *, limit: int = 200) -> dict[str, Any]:
        samples = self.store.list_resource_samples(limit=limit)
        return {"samples": samples, "count": len(samples)}

    def errors_by_category(self, category: str) -> dict[str, Any]:
        rows = []
        for row in self.store.list_runs(limit=1000):
            run = self.store.get_run(row["cid"])
            if self.classify_run(run) == category:
                rows.append(
                    {
                        "cid": run.get("cid"),
                        "trace_id": run.get("trace_id"),
                        "plan_name": run.get("plan_name"),
                        "task_name": run.get("task_name"),
                        "status": run.get("status"),
                        "suggestions": _suggestions_for_category(category),
                    }
                )
        return {"category": category, "runs": rows, "count": len(rows)}

    def queue_analysis(self) -> dict[str, Any]:
        runs = self.store.list_runs(limit=1000)
        status_counts: dict[str, int] = {}
        wait_values = []
        for row in runs:
            status = str(row.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            if row.get("queue_wait_ms") is not None:
                wait_values.append(float(row["queue_wait_ms"]))
        return {
            "status_counts": status_counts,
            "queued": status_counts.get("queued", 0),
            "abandoned": status_counts.get("abandoned", 0),
            "queue_wait_ms_avg": sum(wait_values) / len(wait_values) if wait_values else 0,
        }

    def run_explain(self, cid: str) -> dict[str, Any]:
        run = self.store.get_run(cid)
        if not run:
            return {"status": "error", "cid": cid, "message": "Run not found."}
        category = self.classify_run(run) or "none"
        return {
            "status": "success",
            "cid": cid,
            "error_category": category,
            "summary": {
                "plan_name": run.get("plan_name"),
                "task_name": run.get("task_name"),
                "status": run.get("status"),
                "duration_ms": run.get("duration_ms"),
            },
            "action_results": run.get("action_results") or [],
            "policy_decisions": run.get("policy_decisions") or [],
            "evidence": run.get("evidence") or [],
            "locators": self.store.list_locators(cid),
            "evidence_manifest": self.store.evidence_manifest(cid),
            "rendered_params": [
                (item.get("data") or {}).get("rendered_params")
                for item in run.get("action_results", [])
                if isinstance((item.get("data") or {}).get("rendered_params"), dict)
            ],
            "suggestions": _suggestions_for_category(category),
        }

    @staticmethod
    def classify_run(run: dict[str, Any]) -> str | None:
        if str(run.get("status") or "").lower() in {"success", "queued", "running"}:
            return None
        for decision in run.get("policy_decisions") or []:
            if decision.get("decision") == "deny":
                return "policy_denied"
        payloads = [*run.get("action_results", []), *run.get("nodes", [])]
        raw = json.dumps(payloads, ensure_ascii=False).lower()
        if "backend_unavailable" in raw or "unavailable" in raw:
            return "backend_unavailable"
        if "template" in raw and "render" in raw:
            return "template_render_failed"
        if "dsl" in raw or "schema" in raw:
            return "dsl_schema_invalid"
        if "capture" in raw:
            return "capture_failed"
        if "locator" in raw or "not_found" in raw:
            return "locator_not_found"
        if "ocr" in raw:
            return "ocr_failed"
        if "yolo" in raw:
            return "yolo_failed"
        if "timeout" in raw:
            return "timeout"
        if "dependency" in raw or "import" in raw:
            return "dependency_unavailable"
        if run.get("status"):
            return "unknown_error"
        return None


def _suggestions_for_category(category: str) -> list[str]:
    return {
        "policy_denied": ["Inspect the active policy profile and package permissions before retrying."],
        "backend_unavailable": ["Run capability self-check and choose an available backend or explicit fallback."],
        "template_render_failed": ["Run `python cli.py template render` with the same context to find missing variables."],
        "dsl_schema_invalid": ["Run `python cli.py validate --strict` for structured task errors."],
        "capture_failed": ["Check capture backend availability and evidence references."],
        "locator_not_found": ["Review captured evidence and locator thresholds."],
        "ocr_failed": ["Check OCR backend health and recognized boxes in evidence."],
        "yolo_failed": ["Check YOLO model availability and detection evidence."],
        "timeout": ["Review action duration, queue wait and timeout settings."],
        "dependency_unavailable": ["Run `python cli.py package doctor` to verify imports and dependencies."],
        "unknown_error": ["Inspect action results and node exceptions in run detail."],
        "none": ["Run completed without classified errors."],
    }.get(category, ["Inspect run detail and diagnostics bundle."])

# -*- coding: utf-8 -*-
"""Debug report and fake/fixture step replay."""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path
from typing import Any

from packages.aura_core.observability.query import ObservabilityQueryService
from packages.aura_core.observability.run_store import RunStore
from packages.aura_core.security import redact_json


class DebugService:
    """Builds structured reports and performs safe fake step replay."""

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path).resolve()
        self.store = RunStore(self.base_path / "logs" / "aura.sqlite3")
        self.observability = ObservabilityQueryService(self.base_path)

    def report(self, cid: str, *, output: str | Path | None = None) -> dict[str, Any]:
        payload = self._report_payload(cid)
        payload = redact_json(payload)
        if output:
            self._write_report(payload, Path(output))
        return payload

    def replay_step(
        self,
        cid: str,
        node: str,
        *,
        backend: str = "fake",
        allow_side_effects: bool = False,
        output: str | Path | None = None,
    ) -> dict[str, Any]:
        if backend not in {"fake", "fixture"} and not allow_side_effects:
            return {
                "status": "error",
                "cid": cid,
                "node": node,
                "backend": backend,
                "message": "Real side-effect replay requires --allow-side-effects and remains subject to policy.",
            }
        source = self.store.get_run(cid)
        if not source:
            return {"status": "error", "cid": cid, "node": node, "message": "Run not found."}
        debug_cid = f"debug-{cid}-{node}-{int(time.time() * 1000)}"
        result = {
            "ok": True,
            "action": _action_for_node(source, node),
            "backend": backend,
            "duration_ms": 0,
            "data": {"value": {"replayed_from": cid, "node": node}},
            "evidence": [],
            "fallbacks": [],
        }
        now_ms = int(time.time() * 1000)
        self.store.apply_event(
            "queue.enqueued",
            {
                "cid": debug_cid,
                "trace_id": debug_cid,
                "trace_label": f"debug replay {cid}:{node}",
                "plan_name": source.get("plan_name"),
                "task_name": source.get("task_name"),
                "source": "debug.replay",
            },
            now_ms,
        )
        self.store.apply_event(
            "node.finished",
            {"cid": debug_cid, "node_id": node, "status": "success", "action_result": result},
            now_ms + 1,
        )
        self.store.apply_event(
            "task.finished",
            {"cid": debug_cid, "status": "success", "final_status": "success", "final_result": {"debug": True}},
            now_ms + 2,
        )
        payload = {
            "status": "success",
            "debug_cid": debug_cid,
            "source_cid": cid,
            "node": node,
            "backend": backend,
            "action_result": result,
        }
        if output:
            self._write_report(redact_json({"replay": payload, "source_report": self._report_payload(cid)}), Path(output))
        return payload

    def _report_payload(self, cid: str) -> dict[str, Any]:
        base_report = self.store.debug_report(cid)
        if base_report.get("status") != "success":
            return base_report
        run = self.store.get_run(cid)
        explanation = self.observability.run_explain(cid)
        return {
            "status": "success",
            "cid": cid,
            "schema_version": 2,
            "run": {
                "cid": run.get("cid"),
                "trace_id": run.get("trace_id"),
                "plan_name": run.get("plan_name"),
                "task_name": run.get("task_name"),
                "status": run.get("status"),
                "nodes": run.get("nodes") or [],
            },
            "rendered_params": base_report.get("rendered_params") or [],
            "action_results": run.get("action_results") or [],
            "policy_decisions": run.get("policy_decisions") or [],
            "evidence": run.get("evidence") or [],
            "locators": base_report.get("locators") or [],
            "evidence_manifest": base_report.get("evidence_manifest") or {},
            "explain": explanation,
        }

    @staticmethod
    def _write_report(payload: dict[str, Any], output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = redact_json(payload)
        if output.suffix.lower() == ".zip":
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("debug-report.json", json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _action_for_node(run: dict[str, Any], node_id: str) -> str | None:
    for result in run.get("action_results") or []:
        if result.get("node_id") == node_id:
            return result.get("action")
    for result in run.get("action_results") or []:
        if result.get("action"):
            return result.get("action")
    return None

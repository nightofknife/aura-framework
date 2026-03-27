from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.aura_core.api import service_registry
from packages.aura_core.scheduler import Scheduler


BENCHMARK_SERVICE_ID = "plans/aura_benchmark/benchmark_probe"
PLAN_NAME = "aura_benchmark"


@dataclass
class ScenarioResult:
    name: str
    submitted: int
    completed: int
    failures: int
    wall_time_ms: float
    peak_active_count: int
    avg_duration_ms: float
    statuses: Dict[str, int]
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "submitted": self.submitted,
            "completed": self.completed,
            "failures": self.failures,
            "wall_time_ms": round(self.wall_time_ms, 3),
            "peak_active_count": self.peak_active_count,
            "avg_duration_ms": round(self.avg_duration_ms, 3),
            "statuses": self.statuses,
            "details": self.details,
        }


def _create_runtime(concurrency: int) -> Scheduler:
    runtime = Scheduler(runtime_profile="api_full")
    runtime.execution_manager.max_concurrent_tasks = concurrency
    runtime.execution_manager._global_sem = asyncio.Semaphore(concurrency)
    runtime.start_scheduler()
    if not runtime.startup_complete_event.wait(timeout=20):
        runtime.stop_scheduler()
        raise RuntimeError(f"Runtime startup timed out for concurrency={concurrency}")
    return runtime


def _get_probe_service():
    return service_registry.get_service_instance(BENCHMARK_SERVICE_ID)


def _wait_for_completion(runtime, cids: Iterable[str], timeout_sec: float = 30.0) -> List[Dict[str, Any]]:
    pending = set(cids)
    deadline = time.time() + timeout_sec
    last_snapshot: Dict[str, Dict[str, Any]] = {}

    while pending and time.time() < deadline:
        batch = runtime.get_batch_task_status(list(pending))
        for item in batch:
            cid = item.get("cid")
            if cid:
                last_snapshot[cid] = item
            status = str(item.get("status") or "").upper()
            if status and status not in {"QUEUED", "RUNNING", "NOT_FOUND"}:
                pending.discard(cid)
        if pending:
            time.sleep(0.05)

    if pending:
        raise TimeoutError(f"Timeout waiting for tasks: {sorted(pending)}")

    return [last_snapshot[cid] for cid in cids]


def _status_counter(items: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        key = str(item.get("status") or "UNKNOWN")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _collect_startup_info(runtime: Scheduler) -> Tuple[Dict[str, Any], List[str]]:
    tasks = runtime.get_all_task_definitions_with_meta()
    task_refs = sorted(item["task_ref"] for item in tasks if item.get("plan_name") == PLAN_NAME)
    return (
        {
            "plan_count": len(runtime.get_all_plans()),
            "task_count": len(tasks),
            "benchmark_tasks": task_refs,
        },
        task_refs,
    )


def _run_batch(scenario: str, task_ref: str, inputs_list: List[Dict[str, Any]], concurrency: int) -> ScenarioResult:
    runtime = _create_runtime(concurrency)
    try:
        probe = _get_probe_service()
        probe.reset(scenario)

        start = time.perf_counter()
        batch_result = runtime.run_batch_ad_hoc_tasks(
            [
                {
                    "plan_name": PLAN_NAME,
                    "task_name": task_ref,
                    "inputs": inputs,
                }
                for inputs in inputs_list
            ]
        )
        submit_results = batch_result["results"]
        cids = [item["cid"] for item in submit_results if item.get("cid")]
        task_statuses = _wait_for_completion(runtime, cids)
        snapshot = probe.snapshot(scenario)
        wall_time_ms = (time.perf_counter() - start) * 1000.0

        completed = int(snapshot.get("completed_count", 0))
        failures = int(snapshot.get("failure_count", 0))
        avg_duration_ms = float(snapshot.get("avg_duration_ms", 0.0))

        return ScenarioResult(
            name=scenario,
            submitted=len(inputs_list),
            completed=completed,
            failures=failures,
            wall_time_ms=wall_time_ms,
            peak_active_count=int(snapshot.get("peak_active_count", 0)),
            avg_duration_ms=avg_duration_ms,
            statuses=_status_counter(task_statuses),
            details={
                "submission": {
                    "success_count": batch_result.get("success_count"),
                    "failed_count": batch_result.get("failed_count"),
                },
                "probe_snapshot": snapshot,
                "concurrency": concurrency,
            },
        )
    finally:
        runtime.stop_scheduler()


def _run_single(scenario: str, task_ref: str, inputs: Dict[str, Any], concurrency: int) -> ScenarioResult:
    runtime = _create_runtime(concurrency)
    try:
        probe = _get_probe_service()
        probe.reset(scenario)

        start = time.perf_counter()
        result = runtime.run_ad_hoc_task(PLAN_NAME, task_ref, inputs)
        cid = result["cid"]
        task_status = _wait_for_completion(runtime, [cid])[0]
        snapshot = probe.snapshot(scenario)
        wall_time_ms = (time.perf_counter() - start) * 1000.0

        return ScenarioResult(
            name=scenario,
            submitted=1,
            completed=int(snapshot.get("completed_count", 0)),
            failures=int(snapshot.get("failure_count", 0)),
            wall_time_ms=wall_time_ms,
            peak_active_count=int(snapshot.get("peak_active_count", 0)),
            avg_duration_ms=float(snapshot.get("avg_duration_ms", 0.0)),
            statuses=_status_counter([task_status]),
            details={
                "probe_snapshot": snapshot,
                "task_status": task_status,
                "concurrency": concurrency,
            },
        )
    finally:
        runtime.stop_scheduler()


def main():
    bootstrap_runtime = _create_runtime(1)
    try:
        startup, _task_refs = _collect_startup_info(bootstrap_runtime)
    finally:
        bootstrap_runtime.stop_scheduler()

    scenarios: List[ScenarioResult] = []
    scenarios.append(
        _run_batch(
            scenario="serial_queue",
            task_ref="tasks:single_sleep.yaml",
            inputs_list=[
                {"duration_ms": 180, "scenario": "serial_queue", "label": f"serial-{idx}"}
                for idx in range(6)
            ],
            concurrency=1,
        )
    )
    scenarios.append(
        _run_batch(
            scenario="concurrent_queue",
            task_ref="tasks:single_sleep.yaml",
            inputs_list=[
                {"duration_ms": 220, "scenario": "concurrent_queue", "label": f"concurrent-{idx}"}
                for idx in range(8)
            ],
            concurrency=4,
        )
    )
    scenarios.append(
        _run_batch(
            scenario="burst_queue",
            task_ref="tasks:single_sleep.yaml",
            inputs_list=[
                {"duration_ms": 90, "scenario": "burst_queue", "label": f"burst-{idx}"}
                for idx in range(24)
            ],
            concurrency=8,
        )
    )
    scenarios.append(
        _run_single(
            scenario="serial_dag",
            task_ref="tasks:serial_sleep.yaml",
            inputs={"duration_ms": 120, "scenario": "serial_dag"},
            concurrency=4,
        )
    )
    scenarios.append(
        _run_single(
            scenario="parallel_dag",
            task_ref="tasks:parallel_sleep.yaml",
            inputs={"duration_ms": 120, "scenario": "parallel_dag"},
            concurrency=4,
        )
    )

    summary = {
        "startup": startup,
        "scenarios": [scenario.to_dict() for scenario in scenarios],
    }

    peak_values = [scenario.peak_active_count for scenario in scenarios]
    summary["aggregate"] = {
        "max_peak_active_count": max(peak_values) if peak_values else 0,
        "avg_wall_time_ms": round(statistics.mean(item.wall_time_ms for item in scenarios), 3) if scenarios else 0.0,
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

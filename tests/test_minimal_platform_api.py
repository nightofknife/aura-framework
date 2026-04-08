# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import shutil
import tempfile
import textwrap
import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.dependencies import get_core_scheduler, peek_core_scheduler, reset_core_scheduler
from packages.aura_core.observability.events import Event
from packages.aura_core.scheduler.queues.task_queue import Tasklet


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def _build_workspace(root: Path) -> None:
    (root / "packages").mkdir(parents=True, exist_ok=True)
    plan_dir = root / "plans" / "demo"
    tasks_dir = plan_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    _write_text(
        tasks_dir / "valid.yaml",
        """
        meta:
          title: Valid Task
          description: Demo task
          entry_point: true
          inputs:
            - name: stage
              type: string
              required: true
        steps:
          start:
            action: test.noop
        returns:
          ok: true
        """,
    )

    _write_text(
        tasks_dir / "broken.yaml",
        """
        meta:
          title: Broken Task
        steps:
          x: [
        """,
    )


def test_minimal_platform_api_surface(monkeypatch):
    temp_root = Path.cwd() / ".pytest_tmp"
    temp_root.mkdir(exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="aura-platform-", dir=str(temp_root)))
    _build_workspace(workspace)

    monkeypatch.setenv("AURA_BASE_PATH", str(workspace))
    reset_core_scheduler()

    app = create_app()
    try:
        with TestClient(app) as client:
            status_resp = client.get("/api/v1/system/status")
            assert status_resp.status_code == 200
            status_payload = status_resp.json()
            assert status_payload["status"] == "ok"
            assert status_payload["is_running"] is False

            health_resp = client.get("/api/v1/system/health")
            assert health_resp.status_code == 200
            health_payload = health_resp.json()
            assert health_payload["status"] == "ok"
            assert health_payload["scheduler_running"] is False

            plans_resp = client.get("/api/v1/plans")
            assert plans_resp.status_code == 200
            plans = {item["name"]: item for item in plans_resp.json()}
            assert plans["demo"]["task_count"] == 1
            assert plans["demo"]["task_error_count"] == 1

            tasks_resp = client.get("/api/v1/plans/demo/tasks")
            assert tasks_resp.status_code == 200
            task = tasks_resp.json()[0]
            assert task["task_ref"] == "tasks:valid.yaml"
            assert task["meta"]["title"] == "Valid Task"
            assert task["meta"]["inputs"][0]["name"] == "stage"

            errors_resp = client.get("/api/v1/plans/demo/task-load-errors")
            assert errors_resp.status_code == 200
            assert errors_resp.json()[0]["source_file"] == "broken.yaml"

            queued_resp = client.post(
                "/api/v1/tasks/dispatch",
                json={
                    "plan_name": "demo",
                    "task_ref": "tasks:valid.yaml",
                    "inputs": {"stage": "alpha"},
                },
            )
            assert queued_resp.status_code == 202
            queued_payload = queued_resp.json()
            assert queued_payload["status"] == "queued"
            assert queued_payload["cid"]

            batch_status = client.post(
                "/api/v1/tasks/status/batch",
                json={"cids": [queued_payload["cid"]]},
            )
            assert batch_status.status_code == 200
            assert batch_status.json()["tasks"][0]["cid"] == queued_payload["cid"]

            scheduler = get_core_scheduler()
            scheduler.execution_manager.max_concurrent_tasks = 0

            start_resp = client.post("/api/v1/system/start")
            assert start_resp.status_code == 200

            scheduler = peek_core_scheduler()
            assert scheduler is not None

            async def _seed_queue_and_runs():
                now = time.time()
                queue_payloads = [
                    {
                        "cid": "queue-a",
                        "trace_id": "trace-a",
                        "trace_label": "demo/tasks:valid.yaml#a",
                        "source": "gui",
                        "plan_name": "demo",
                        "task_name": "tasks:valid.yaml",
                        "enqueued_at": now,
                        "delay_until": None,
                    },
                    {
                        "cid": "queue-b",
                        "trace_id": "trace-b",
                        "trace_label": "demo/tasks:valid.yaml#b",
                        "source": "gui",
                        "plan_name": "demo",
                        "task_name": "tasks:valid.yaml",
                        "enqueued_at": now + 1,
                        "delay_until": None,
                    },
                ]

                for payload in queue_payloads:
                    await scheduler.event_bus.publish(Event(name="queue.enqueued", payload=payload))
                    await scheduler.task_queue.put(
                        Tasklet(
                            task_name="demo/tasks:valid.yaml",
                            cid=payload["cid"],
                            trace_id=payload["trace_id"],
                            trace_label=payload["trace_label"],
                            source=payload["source"],
                            payload={
                                "plan_name": payload["plan_name"],
                                "task_name": payload["task_name"],
                            },
                        ),
                        high_priority=True,
                    )

                await scheduler.event_bus.publish(
                    Event(
                        name="task.started",
                        payload={
                            "cid": "run-active",
                            "trace_id": "trace-run-active",
                            "trace_label": "demo/tasks:valid.yaml#running",
                            "plan_name": "demo",
                            "task_name": "tasks:valid.yaml",
                            "start_time": now,
                            "source": "gui",
                        },
                    )
                )
                await scheduler.event_bus.publish(
                    Event(
                        name="task.started",
                        payload={
                            "cid": "run-finished",
                            "trace_id": "trace-run-finished",
                            "trace_label": "demo/tasks:valid.yaml#finished",
                            "plan_name": "demo",
                            "task_name": "tasks:valid.yaml",
                            "start_time": now,
                            "source": "gui",
                        },
                    )
                )
                await scheduler.event_bus.publish(
                    Event(
                        name="task.finished",
                        payload={
                            "cid": "run-finished",
                            "trace_id": "trace-run-finished",
                            "trace_label": "demo/tasks:valid.yaml#finished",
                            "plan_name": "demo",
                            "task_name": "tasks:valid.yaml",
                            "end_time": now + 2,
                            "duration": 2.0,
                            "final_status": "success",
                            "final_result": {
                                "status": "SUCCESS",
                                "user_data": {"ok": True},
                                "framework_data": {"nodes": {}},
                                "error": None,
                            },
                        },
                    )
                )

            scheduler.run_on_control_loop(_seed_queue_and_runs(), timeout=5.0)

            overview_resp = client.get("/api/v1/queue/overview")
            assert overview_resp.status_code == 200
            overview_payload = overview_resp.json()
            assert overview_payload["ready_count"] >= 2
            assert "ready_length" in overview_payload

            list_resp = client.get("/api/v1/queue/list", params={"state": "ready"})
            assert list_resp.status_code == 200
            queue_items = list_resp.json()["items"]
            assert {item["cid"] for item in queue_items} >= {"queue-a", "queue-b"}
            assert queue_items[0]["task_ref"] == "tasks:valid.yaml"
            assert queue_items[0]["task_name"] == "tasks:valid.yaml"

            move_resp = client.post("/api/v1/queue/queue-a/move-to-front")
            assert move_resp.status_code == 200
            reordered_resp = client.post("/api/v1/queue/reorder", json={"cid_order": ["queue-b", "queue-a"]})
            assert reordered_resp.status_code == 200
            remove_resp = client.delete("/api/v1/queue/queue-a")
            assert remove_resp.status_code == 200

            active_resp = client.get("/api/v1/runs/active")
            assert active_resp.status_code == 200
            active_runs = active_resp.json()
            assert any(run["cid"] == "run-active" for run in active_runs)

            history_resp = client.get("/api/v1/runs/history", params={"limit": 20})
            assert history_resp.status_code == 200
            history_runs = history_resp.json()["runs"]
            assert any(run["cid"] == "run-finished" for run in history_runs)

            detail_resp = client.get("/api/v1/runs/run-finished")
            assert detail_resp.status_code == 200
            detail = detail_resp.json()
            assert detail["status"] == "success"
            assert detail["user_data"] == {"ok": True}

            legacy_detail = client.get("/api/v1/run/run-finished/detail")
            assert legacy_detail.status_code == 200
            assert legacy_detail.json()["run"]["cid"] == "run-finished"

            clear_resp = client.delete("/api/v1/queue/clear")
            assert clear_resp.status_code == 200
    finally:
        reset_core_scheduler()
        shutil.rmtree(workspace, ignore_errors=True)

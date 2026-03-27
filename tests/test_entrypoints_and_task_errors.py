# -*- coding: utf-8 -*-

from __future__ import annotations

import importlib
import shutil
import tempfile
import textwrap
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.dependencies import reset_core_scheduler


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
          inputs:
            - name: stage
              type: string
              required: true
        steps:
          start:
            action: test.noop
        """,
    )

    _write_text(
        tasks_dir / "legacy.yaml",
        """
        meta:
          title: Legacy Task
        steps:
          first:
            action: test.noop
          second:
            action: test.noop
            depends_on:
              and:
                - first
        """,
    )

    _write_text(
        tasks_dir / "legacy_list.yaml",
        """
        meta:
          title: Legacy List Task
        steps:
          first:
            action: test.noop
          second:
            action: test.noop
            depends_on:
              - first
        """,
    )

    _write_text(
        tasks_dir / "legacy_run_task.yaml",
        """
        meta:
          title: Legacy Run Task
        steps:
          call_subtask:
            action: aura.run_task
            params:
              task_name: old_style
        """,
    )

    _write_text(
        tasks_dir / "broken_yaml.yaml",
        """
        meta:
          title: Broken YAML
        steps:
          start:
            action: test.noop
          broken: [
        """,
    )


def test_entrypoint_import_smoke():
    importlib.import_module("cli")
    importlib.import_module("backend.run")
    importlib.import_module("backend.api.routes.execution")


def test_api_smoke_and_task_error_exposure(monkeypatch):
    temp_root = Path.cwd() / ".pytest_tmp"
    temp_root.mkdir(exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="aura-test-", dir=str(temp_root)))

    _build_workspace(workspace)
    monkeypatch.setenv("AURA_BASE_PATH", str(workspace))
    reset_core_scheduler()

    app = create_app()
    try:
        with TestClient(app) as client:
            health_resp = client.get("/api/v1/system/health")
            assert health_resp.status_code == 200
            assert health_resp.json()["status"] == "ok"

            plans_resp = client.get("/api/v1/plans")
            assert plans_resp.status_code == 200
            plans = {item["name"]: item for item in plans_resp.json()}
            assert "demo" in plans
            assert plans["demo"]["task_count"] == 1
            assert plans["demo"]["task_error_count"] == 4

            tasks_resp = client.get("/api/v1/plans/demo/tasks")
            assert tasks_resp.status_code == 200
            task_refs = {item["task_ref"] for item in tasks_resp.json()}
            assert "tasks:valid.yaml" in task_refs
            assert "tasks:legacy.yaml" not in task_refs

            errors_resp = client.get("/api/v1/plans/demo/task-load-errors")
            assert errors_resp.status_code == 200
            errors = {item["source_file"]: item for item in errors_resp.json()}
            assert errors["legacy.yaml"]["error_code"] == "deprecated_syntax"
            assert errors["legacy_list.yaml"]["error_code"] == "deprecated_syntax"
            assert errors["legacy_run_task.yaml"]["error_code"] == "deprecated_syntax"
            assert errors["broken_yaml.yaml"]["error_code"] == "yaml_parse_failed"

            dispatch_resp = client.post(
                "/api/v1/tasks/dispatch",
                json={
                    "plan_name": "demo",
                    "task_ref": "tasks:valid.yaml",
                    "inputs": {"stage": "alpha"},
                },
            )
            assert dispatch_resp.status_code == 202
            assert dispatch_resp.json()["status"] == "queued"

            broken_dispatch = client.post(
                "/api/v1/tasks/dispatch",
                json={
                    "plan_name": "demo",
                    "task_ref": "tasks:legacy.yaml",
                    "inputs": {},
                },
            )
            assert broken_dispatch.status_code == 400
            detail = broken_dispatch.json()["detail"]
            assert "Task definition invalid" in detail
            assert "not found" not in detail.lower()
    finally:
        reset_core_scheduler()
        shutil.rmtree(workspace, ignore_errors=True)

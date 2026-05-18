# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.dependencies import reset_core_scheduler
from cli import aura

pytestmark = pytest.mark.api


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def _write_manifest(plan_dir: Path, name: str, *, actions: str = "[]") -> None:
    _write_text(
        plan_dir / "manifest.yaml",
        f"""
        package:
          name: '@plans/{name}'
          version: 0.1.0
          description: Test plan
          license: MIT
        requires:
          aura: '>=0.1.0'
        exports:
          services: []
          actions: {actions}
          tasks: []
        """,
    )


def _build_workspace(root: Path) -> None:
    (root / "packages").mkdir(parents=True, exist_ok=True)

    demo_dir = root / "plans" / "demo"
    _write_manifest(
        demo_dir,
        "demo",
        actions="""
          - name: noop
            module: plans.demo.src.actions.noop
            function: noop
            public: true
            read_only: true
        """,
    )
    _write_text(
        demo_dir / "tasks" / "valid.yaml",
        """
        meta:
          title: Valid
          inputs:
            - name: stage
              type: string
              default: alpha
        steps:
          start:
            action: noop
        returns:
          ok: true
        """,
    )
    _write_text(
        demo_dir / "tasks" / "broken.yaml",
        """
        meta:
          title: Broken
        steps:
          start:
            action: noop
          next:
            action: noop
            depends_on:
              - start
        """,
    )

    other_dir = root / "plans" / "other"
    _write_manifest(other_dir, "other")
    _write_text(
        other_dir / "tasks" / "valid.yaml",
        """
        meta:
          title: Other
        steps:
          start:
            action: placeholder.action
        """,
    )


def test_validate_cli_json_and_plan_filter(tmp_path: Path):
    _build_workspace(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        aura,
        ["validate", "--base-path", str(tmp_path), "--plan", "other", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == {"status": "success", "errors": []}


def test_validate_cli_reports_structured_task_errors(tmp_path: Path):
    _build_workspace(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        aura,
        ["validate", "--base-path", str(tmp_path), "--plan", "demo", "--format", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "error"
    error = payload["errors"][0]
    assert error["plan_name"] == "demo"
    assert error["error_code"] == "deprecated_syntax"
    assert error["file_path"].endswith("broken.yaml")
    assert "list dependency shorthand" in error["message"]


def test_validate_cli_dry_run_and_strict_action_check(tmp_path: Path):
    _build_workspace(tmp_path)
    runner = CliRunner()

    ok = runner.invoke(
        aura,
        [
            "validate",
            "--base-path",
            str(tmp_path),
            "--plan",
            "demo",
            "--dry-run",
            "--task-ref",
            "tasks:valid.yaml",
            "--format",
            "json",
            "--strict",
        ],
    )
    assert ok.exit_code == 0
    assert json.loads(ok.output)["status"] == "success"

    strict_failure = runner.invoke(
        aura,
        [
            "validate",
            "--base-path",
            str(tmp_path),
            "--plan",
            "other",
            "--dry-run",
            "--task-ref",
            "tasks:valid.yaml",
            "--format",
            "json",
            "--strict",
        ],
    )
    assert strict_failure.exit_code == 1
    payload = json.loads(strict_failure.output)
    assert payload["errors"][0]["error_code"] == "action_not_exported"


def test_minimal_workspace_api_health_without_desktop_plan(tmp_path: Path, monkeypatch):
    minimal_dir = tmp_path / "plans" / "minimal"
    _write_manifest(minimal_dir, "minimal")
    _write_text(
        minimal_dir / "tasks" / "valid.yaml",
        """
        meta:
          title: Minimal
        steps:
          start:
            action: placeholder.action
        """,
    )
    (tmp_path / "packages").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("AURA_BASE_PATH", str(tmp_path))
    reset_core_scheduler()
    app = create_app()
    try:
        with TestClient(app) as client:
            health = client.get("/api/v1/system/health")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"
            plans = client.get("/api/v1/plans")
            assert plans.status_code == 200
            assert plans.json()[0]["name"] == "minimal"
    finally:
        reset_core_scheduler()

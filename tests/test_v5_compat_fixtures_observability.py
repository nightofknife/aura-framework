# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from fastapi.testclient import TestClient

from backend.api.app import create_app
from cli import aura
from packages.aura_core.compat import CompatibilityService
from packages.aura_core.debugging import DebugService
from packages.aura_core.fixtures import FixtureService
from packages.aura_core.observability.query import ObservabilityQueryService
from packages.aura_core.observability.run_store import RunStore
from packages.aura_core.observability.writer import ObservabilityWriter
from packages.aura_core.packaging.core.workspace_lifecycle import WorkspaceLifecycleService


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def test_compat_matrix_check_and_diff(tmp_path: Path):
    service = CompatibilityService(Path.cwd())
    matrix = service.matrix()
    assert matrix["compat_schema_version"] == 1
    assert matrix["contracts"]["api"]["version"] == "v1"
    assert service.check()["status"] == "success"

    old_lock = tmp_path / "old.lock.yaml"
    new_lock = tmp_path / "packages.lock.yaml"
    old_lock.write_text(
        yaml.safe_dump({"lock_schema_version": 1, "packages": [{"id": "plans/demo", "version": "0.1.0", "content_hash": "sha256:a"}]}),
        encoding="utf-8",
    )
    new_lock.write_text(
        yaml.safe_dump({"lock_schema_version": 1, "packages": [{"id": "plans/demo", "version": "0.2.0", "content_hash": "sha256:b"}]}),
        encoding="utf-8",
    )
    diff = service.diff_locks(old_lock, new_lock)
    assert diff["changed"][0]["id"] == "plans/demo"
    assert diff["changed"][0]["changes"]["version"]["to"] == "0.2.0"


def test_compat_check_skips_contracts_for_not_enabled_packages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write(
        tmp_path / "workspace.yaml",
        """
        workspace_schema_version: 1
        workspace:
          name: default
          profile: workspace-default
        runtime:
          api_profile: local_only
          desktop_profile: default
          persistence: sqlite
        packages: []
        """,
    )
    _write(
        tmp_path / "compat" / "aura-compat.yaml",
        """
        compat_schema_version: 1
        aura_version: "0.1.0"
        contracts:
          contracts_snapshot: tests/snapshots/contracts-v1-stable.json
          workspace:
            supported_versions: [1]
          lock:
            supported_versions: [1]
        deprecated:
          actions: []
          services: []
          api_fields: []
        breaking_changes: []
        """,
    )
    (tmp_path / "tests" / "snapshots").mkdir(parents=True)
    (tmp_path / "tests" / "snapshots" / "contracts-v1-stable.json").write_text(
        json.dumps(
            {
                "snapshot_schema_version": 1,
                "actions": {"plans/demo/do": {"parameters": []}},
                "services": {"plans/demo/service": {"parameters": []}},
            }
        ),
        encoding="utf-8",
    )
    service = CompatibilityService(tmp_path)
    monkeypatch.setattr(
        service,
        "_build_contract_snapshot",
        lambda: {"snapshot_schema_version": 1, "actions": {}, "services": {}},
    )

    assert service.check()["status"] == "success"


def test_fixture_service_runs_and_verifies_basic_fixture():
    service = FixtureService(Path.cwd())
    rows = service.list()
    assert any(row["id"] == "desktop/basic-click" for row in rows)

    run = service.run("desktop/basic-click")
    assert run["status"] == "success"
    assert run["action_results"][0]["backend"] == "fake"

    verified = service.verify("desktop/basic-click")
    assert verified["status"] == "success"


def test_observability_and_debug_services_classify_and_replay(tmp_path: Path):
    store = RunStore(tmp_path / "logs" / "aura.sqlite3")
    store.apply_event(
        "queue.enqueued",
        {"cid": "run-1", "trace_id": "trace-1", "plan_name": "demo", "task_name": "tasks:click.yaml", "queue_wait_ms": 5},
        1000,
    )
    store.apply_event(
        "node.failed",
        {
            "cid": "run-1",
            "node_id": "click",
            "status": "failed",
            "exception_message": "policy denied",
            "action_result": {
                "node_id": "click",
                "ok": False,
                "action": "plans/aura_base/click",
                "backend": "fake",
                "duration_ms": 7,
                "error_code": "policy_denied",
                "fallbacks": [],
                "evidence": [{"kind": "backend", "path": "logs/evidence/run-1/backend/policy.json"}],
            },
            "policy_decision": {
                "action": "plans/aura_base/click",
                "profile": "safe",
                "decision": "deny",
                "reason": "desktop.mouse.input denied",
                "capabilities": ["desktop.mouse.input"],
            },
        },
        1100,
    )
    store.apply_event("task.finished", {"cid": "run-1", "final_status": "error", "final_result": {"error": "policy denied"}}, 1200)
    store.backfill_observability()

    query = ObservabilityQueryService(tmp_path)
    assert query.list_traces()["traces"][0]["trace_id"] == "trace-1"
    assert query.error_summary()["counts"]["policy_denied"] == 1
    assert query.action_metrics()["actions"][0]["action"] == "plans/aura_base/click"
    assert query.backend_metrics()["backends"][0]["backend"] == "fake"
    assert query.run_explain("run-1")["error_category"] == "policy_denied"

    debug = DebugService(tmp_path)
    report = debug.report("run-1")
    assert report["status"] == "success"
    assert report["explain"]["error_category"] == "policy_denied"

    denied = debug.replay_step("run-1", "click", backend="win32_sendinput")
    assert denied["status"] == "error"

    replay = debug.replay_step("run-1", "click", backend="fake")
    assert replay["status"] == "success"
    assert debug.store.get_run(replay["debug_cid"])["action_results"][0]["backend"] == "fake"


def test_observability_writer_batches_and_drops_only_debug_events(tmp_path: Path):
    store = RunStore(tmp_path / "logs" / "aura.sqlite3")
    writer = ObservabilityWriter(store, queue_max_size=1, batch_size=10)

    writer.enqueue("queue.enqueued", {"cid": "queued-run", "plan_name": "demo", "task_name": "task"}, 1000, critical=True)
    assert store.get_run("queued-run") == {}
    assert writer.flush_pending() == 1
    assert store.get_run("queued-run")["status"] == "queued"

    writer.enqueue("debug.sample", {"cid": "debug-1"}, 1001, critical=False)
    writer.enqueue("debug.sample", {"cid": "debug-2"}, 1002, critical=False)

    snapshot = writer.snapshot()
    assert snapshot["stats"]["dropped_debug"] == 1
    assert snapshot["debug_depth"] == 1


def test_package_pack_compat_and_upgrade_plan(tmp_path: Path):
    plan_dir = tmp_path / "plans" / "demo"
    _write(
        plan_dir / "manifest.yaml",
        """
        package:
          name: '@plans/demo'
          version: 0.1.0
          description: Demo package
          license: MIT
        requires:
          aura: '>=0.1.0'
        exports:
          services: []
          actions: []
          tasks: []
        """,
    )
    service = WorkspaceLifecycleService(tmp_path)
    service.save_workspace(
        {
            "workspace_schema_version": 1,
            "workspace": {"name": "default", "profile": "workspace-default"},
            "runtime": {"api_profile": "local_only", "desktop_profile": "default", "persistence": "sqlite"},
            "packages": [{"id": "plans/demo", "enabled": True, "source": "plans/demo"}],
        }
    )
    service.write_lock()

    pack = service.pack_package("plans/demo", output=tmp_path / "demo.aura")
    assert pack["status"] == "success"
    assert (tmp_path / "demo.aura").is_file()

    diff = service.diff_packages(plan_dir, plan_dir)
    assert diff["changes"] == []

    compat = service.compat_package("plans/demo")
    assert compat["status"] == "success"

    upgrade = CompatibilityService(tmp_path).upgrade_plan("plans/demo")
    assert upgrade["will_modify_workspace"] is False


def test_package_symlink_is_rejected_by_validate_doctor_and_pack(tmp_path: Path):
    plan_dir = tmp_path / "plans" / "demo"
    _write(
        plan_dir / "manifest.yaml",
        """
        package:
          name: '@plans/demo'
          version: 0.1.0
          description: Demo package
          license: MIT
        requires:
          aura: '>=0.1.0'
        exports:
          services: []
          actions: []
          tasks: []
        """,
    )
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        os.symlink(outside, plan_dir / "leak.txt")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    service = WorkspaceLifecycleService(tmp_path)
    service.save_workspace(
        {
            "workspace_schema_version": 1,
            "workspace": {"name": "default", "profile": "workspace-default"},
            "runtime": {"api_profile": "local_only", "desktop_profile": "default", "persistence": "sqlite"},
            "packages": [{"id": "plans/demo", "enabled": True, "source": "plans/demo"}],
        }
    )

    validation = service.validate_package("plans/demo")
    pack = service.pack_package("plans/demo", output=tmp_path / "demo.aura")
    doctor = service.doctor()

    assert validation["status"] == "error"
    assert validation["errors"][0]["code"] == "package_symlink_disallowed"
    assert validation["errors"][0]["escapes_root"] is True
    assert pack["status"] == "error"
    assert pack["error_code"] == "package_symlink_disallowed"
    assert doctor["status"] == "error"


def test_observability_api_and_cli_smoke(tmp_path: Path):
    client = TestClient(create_app())
    response = client.get("/api/v1/observability/errors/summary")
    assert response.status_code == 200
    assert "policy_denied" in response.json()["taxonomy"]

    runner = CliRunner()
    assert runner.invoke(aura, ["compat", "matrix", "--format", "json"]).exit_code == 0
    assert runner.invoke(aura, ["fixture", "list"]).exit_code == 0
    assert runner.invoke(aura, ["observability", "errors", "--base-path", str(tmp_path)]).exit_code == 0

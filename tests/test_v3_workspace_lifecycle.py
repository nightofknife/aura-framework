# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import yaml
from click.testing import CliRunner
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.dependencies import reset_core_scheduler
from cli import aura
from packages.aura_core.diagnostics import DiagnosticsCollector
from packages.aura_core.observability.run_store import RunStore
from packages.aura_core.packaging.core.dependency_manager import PackageDependencyService
from packages.aura_core.packaging.core.package_manager import PackageManager
from packages.aura_core.packaging.core.workspace_lifecycle import WorkspaceLifecycleService
from packages.aura_core.packaging.core.workspace_lifecycle import normalize_package_id
from packages.aura_core.utils.safe_paths import UnsafePathError


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def _write_manifest(plan_dir: Path, package_name: str) -> None:
    _write(
        plan_dir / "manifest.yaml",
        f"""
        package:
          name: '@plans/{package_name}'
          version: 0.1.0
          description: Test package
          license: MIT
        requires:
          aura: '>=0.1.0'
        exports:
          services: []
          actions: []
          tasks: []
        """,
    )


def _build_workspace(root: Path) -> None:
    (root / "packages").mkdir(parents=True, exist_ok=True)
    _write_manifest(root / "plans" / "aura_base", "aura_base")
    _write_manifest(root / "plans" / "aura_benchmark", "aura_benchmark")
    _write(
        root / "workspace.yaml",
        """
        workspace_schema_version: 1
        workspace:
          name: default
          profile: workspace-default
        runtime:
          api_profile: local_only
          desktop_profile: default
          persistence: sqlite
        packages:
          - id: plans/aura_base
            enabled: true
            source: plans/aura_base
          - id: plans/aura_benchmark
            enabled: false
            source: plans/aura_benchmark
        """,
    )


def test_workspace_profile_filters_package_manager(tmp_path: Path):
    _build_workspace(tmp_path)

    manager = PackageManager(tmp_path / "packages", tmp_path / "plans")
    manifests = manager._discover_packages()

    assert set(manifests) == {"plans/aura_base"}


def _write_dependency_workspace(root: Path, requirements: str) -> None:
    _write_manifest(root / "packages" / "demo", "demo")
    _write(root / "packages" / "demo" / "requirements.txt", requirements)
    _write(
        root / "workspace.yaml",
        """
        workspace_schema_version: 1
        workspace:
          name: default
          profile: workspace-default
        runtime:
          api_profile: local_only
          desktop_profile: default
          persistence: sqlite
        packages:
          - id: plans/demo
            enabled: true
            source: packages/demo
        """,
    )


def test_package_dependency_doctor_plan_and_dry_run_cli(tmp_path: Path):
    _write_dependency_workspace(
        tmp_path,
        """
        pip>=0
        definitely-missing-aura-dep-xyz>=1
        """,
    )
    service = PackageDependencyService(tmp_path)

    doctor = service.doctor("plans/demo")
    assert doctor["status"] == "error"
    assert any(error["code"] == "dependency_missing" for error in doctor["errors"])

    plan = service.plan("plans/demo")
    assert plan["status"] == "success"
    assert plan["will_install"] is True
    assert "definitely-missing-aura-dep-xyz>=1" in plan["install_requirements"]

    result = CliRunner().invoke(
        aura,
        ["package", "deps", "plan", "plans/demo", "--base-path", str(tmp_path), "--format", "json"],
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["will_install"] is True


def test_package_dependency_install_apply_requires_trust_and_network(tmp_path: Path):
    _write_dependency_workspace(tmp_path, "definitely-missing-aura-dep-xyz>=1")
    service = PackageDependencyService(tmp_path)

    missing = service.install("plans/demo", apply=True, trusted=False, allow_network=True)
    assert missing["status"] == "error"
    assert missing["errors"][0]["code"] == "package_trust_required"

    no_network = service.install("plans/demo", apply=True, trusted=True, allow_network=False)
    assert no_network["status"] == "error"
    assert no_network["errors"][0]["code"] == "network_not_confirmed"


def test_package_dependency_install_apply_runs_pip_when_trusted(tmp_path: Path, monkeypatch):
    _write_dependency_workspace(tmp_path, "definitely-missing-aura-dep-xyz>=1")
    monkeypatch.setenv("AURA_POLICY_PROFILE", "trusted")
    calls = []

    def fake_run(command, **kwargs):  # noqa: ANN001
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="installed", stderr="")

    monkeypatch.setattr("packages.aura_core.packaging.core.dependency_manager.subprocess.run", fake_run)
    result = PackageDependencyService(tmp_path).install(
        "plans/demo",
        apply=True,
        trusted=True,
        allow_network=True,
    )

    assert result["status"] == "success"
    assert calls
    assert "definitely-missing-aura-dep-xyz>=1" in calls[0]


def test_package_dependency_blocks_direct_references(tmp_path: Path):
    _write_dependency_workspace(tmp_path, "demo @ file:///C:/tmp/demo.whl")

    plan = PackageDependencyService(tmp_path).plan("plans/demo")

    assert plan["status"] == "error"
    assert plan["errors"][0]["code"] == "dependency_direct_reference_disallowed"


def test_workspace_lifecycle_enable_disable_lock_and_doctor(tmp_path: Path):
    _build_workspace(tmp_path)
    service = WorkspaceLifecycleService(tmp_path)

    assert [row["id"] for row in service.list_packages()] == ["plans/aura_base", "plans/aura_benchmark"]
    disabled = service.disable_package("@plans/aura_base")
    assert disabled["status"] == "success"
    enabled = service.enable_package("plans/aura_benchmark")
    assert enabled["status"] == "success"

    lock = service.write_lock()
    assert lock["lock_schema_version"] == 1
    assert {item["id"] for item in lock["packages"]} == {"plans/aura_base", "plans/aura_benchmark"}
    assert service.doctor()["status"] == "success"


def test_package_id_rejects_traversal_and_windows_reserved_names():
    for value in ["@evil/..", "@evil/.", "@evil/con", "@evil/C:/temp", "@evil/name."]:
        try:
            normalize_package_id(value)
        except UnsafePathError:
            pass
        else:
            raise AssertionError(f"Expected unsafe package id to fail: {value}")


def test_package_cli_list_and_doctor(tmp_path: Path):
    _build_workspace(tmp_path)
    runner = CliRunner()

    result = runner.invoke(aura, ["package", "list", "--base-path", str(tmp_path), "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["packages"][0]["id"] == "plans/aura_base"

    result = runner.invoke(aura, ["package", "doctor", "--base-path", str(tmp_path), "--format", "json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["status"] == "success"


def test_run_store_v3_tables_and_legacy_migration(tmp_path: Path):
    legacy = RunStore(tmp_path / "logs" / "runs" / "run_store.sqlite3")
    legacy.apply_event("queue.enqueued", {"cid": "c1", "plan_name": "demo", "task_name": "tasks:x.yaml"}, 1000)

    store = RunStore(tmp_path / "logs" / "aura.sqlite3")
    result = store.migrate_from_legacy(tmp_path / "logs" / "runs" / "run_store.sqlite3")

    assert result["status"] == "success"
    assert store.get_run("c1")["status"] == "queued"
    store.record_workspace_packages([{"id": "plans/aura_base", "enabled": True, "validation_status": "ok"}])
    store.record_diagnostic_bundle("diag-1", str(tmp_path / "diagnostics" / "diag-1"), "success", {"run_count": 0})
    assert store.get_diagnostic_bundle("diag-1")["summary"]["run_count"] == 0


def test_diagnostics_collects_redacted_bundle(tmp_path: Path):
    _build_workspace(tmp_path)
    _write(
        tmp_path / "config.example.yaml",
        """
        api:
          api_key: should-not-leak
        normal: visible
        """,
    )
    store = RunStore(tmp_path / "logs" / "aura.sqlite3")
    store.apply_event("queue.enqueued", {"cid": "secret-run", "plan_name": "demo", "task_name": "secret"}, 1000)
    store.apply_event(
        "node.failed",
        {
            "cid": "secret-run",
            "node_id": "n1",
            "status": "failed",
            "exception_message": "Authorization: Bearer leak-token",
            "action_result": {
                "ok": False,
                "action": "demo/secret",
                "data": {"rendered_params": {"password": "run-password", "normal": "visible"}},
                "evidence": [{"kind": "backend", "token": "evidence-token"}],
            },
            "policy_decision": {"decision": "deny", "api_key": "policy-key"},
        },
        1100,
    )
    store.apply_event("task.finished", {"cid": "secret-run", "status": "failed", "final_result": {"secret": "final-secret"}}, 1200)
    store._conn.close()
    _write(tmp_path / "logs" / "aura.log", "Authorization: Bearer log-token\nprivate_key=log-key\nnormal=visible")

    result = DiagnosticsCollector(tmp_path).collect()

    assert result["status"] == "success"
    bundle_dir = Path(result["path"])
    redacted = json.loads((bundle_dir / "config.redacted.json").read_text(encoding="utf-8"))
    assert redacted["config.example.yaml"]["api"]["api_key"] == "***REDACTED***"
    payload = (bundle_dir / "run-details" / "secret-run.json").read_text(encoding="utf-8")
    evidence = (bundle_dir / "evidence" / "secret-run" / "action-results.jsonl").read_text(encoding="utf-8")
    logs = "\n".join(path.read_text(encoding="utf-8") for path in (bundle_dir / "logs").glob("*.log"))
    assert "run-password" not in payload
    assert "evidence-token" not in evidence
    assert "log-token" not in logs
    assert "log-key" not in logs
    assert "visible" in payload
    assert (bundle_dir / "workspace.json").is_file()
    assert DiagnosticsCollector(tmp_path).recent()[0]["id"] == result["bundle_id"]


def test_diagnostics_refuses_existing_non_bundle_output_dir(tmp_path: Path):
    _build_workspace(tmp_path)
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep.txt").write_text("do not delete", encoding="utf-8")

    try:
        DiagnosticsCollector(tmp_path).collect(output=output)
    except FileExistsError:
        pass
    else:
        raise AssertionError("Expected existing non-bundle diagnostics path to fail")

    assert (output / "keep.txt").is_file()


def test_workspace_and_diagnostics_api(tmp_path: Path, monkeypatch):
    _build_workspace(tmp_path)
    monkeypatch.setenv("AURA_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("AURA_API_AUTH_KEY", "local-secret")
    monkeypatch.setenv("AURA_API_ENABLE_PACKAGE_ADMIN", "1")
    reset_core_scheduler()
    client = TestClient(create_app())

    try:
        headers = {"X-Aura-Api-Key": "local-secret"}
        response = client.get("/api/v1/workspace/packages")
        assert response.status_code == 200
        assert response.json()[0]["id"] == "plans/aura_base"

        response = client.post("/api/v1/workspace/packages/plans%2Faura_benchmark/enable", headers=headers)
        assert response.status_code == 200
        workspace = yaml.safe_load((tmp_path / "workspace.yaml").read_text(encoding="utf-8"))
        benchmark = [item for item in workspace["packages"] if item["id"] == "plans/aura_benchmark"][0]
        assert benchmark["enabled"] is True

        response = client.post("/api/v1/diagnostics/collect", headers=headers)
        assert response.status_code == 200
        bundle_id = response.json()["bundle_id"]
        assert client.get("/api/v1/diagnostics/recent").status_code == 200
        assert client.get(f"/api/v1/diagnostics/{bundle_id}").status_code == 200
    finally:
        reset_core_scheduler()

# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner
from fastapi.testclient import TestClient

from backend.api.app import create_app
from cli import aura
from packages.aura_core.observability.run_store import RunStore
from packages.aura_core.policy import evaluate_action_policy


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def _dummy_action(*, capabilities: list[str], read_only: bool = False, requires_admin: bool = False) -> SimpleNamespace:
    package = SimpleNamespace(canonical_id="plans/aura_base")
    plugin = SimpleNamespace(package=package)
    return SimpleNamespace(
        name="click",
        fqid="plans/aura_base/click",
        plugin=plugin,
        read_only=read_only,
        capabilities=capabilities,
        side_effect_level="read" if read_only else "input",
        requires_admin=requires_admin,
    )


def test_policy_profiles_fail_closed_for_high_risk_capabilities():
    mouse_action = _dummy_action(capabilities=["desktop.mouse.input"])
    safe = evaluate_action_policy(action_def=mouse_action, profile="safe")
    assert safe.decision == "deny"
    assert "desktop.mouse.input" in safe.reason

    default = evaluate_action_policy(action_def=mouse_action, profile="default")
    assert default.decision == "allow"

    hid = evaluate_action_policy(
        action_def=mouse_action,
        rendered_params={"backend": "hid_mouse"},
        profile="default",
    )
    assert hid.decision == "deny"
    assert "desktop.hid.input" in hid.reason

    admin = evaluate_action_policy(
        action_def=_dummy_action(capabilities=["desktop.mouse.input"], requires_admin=True),
        profile="default",
    )
    assert admin.decision == "deny"
    assert "requires admin" in admin.reason


def test_run_store_records_action_policy_and_evidence(tmp_path: Path):
    store = RunStore(tmp_path / "logs" / "aura.sqlite3")
    store.apply_event(
        "queue.enqueued",
        {"cid": "run-1", "plan_name": "demo", "task_name": "tasks:valid.yaml"},
        1000,
    )
    store.apply_event(
        "node.finished",
        {
            "cid": "run-1",
            "node_id": "start",
            "status": "success",
            "action_result": {
                "ok": True,
                "action": "plans/aura_base/click",
                "backend": "fake",
                "duration_ms": 3,
                "data": {"value": {}},
                "evidence": [{"kind": "capture", "path": "logs/evidence/run-1/captures/shot.png"}],
                "fallbacks": [],
            },
            "policy_decision": {
                "profile": "default",
                "decision": "allow",
                "action": "plans/aura_base/click",
                "capabilities": ["desktop.mouse.input"],
                "reason": "",
            },
        },
        2000,
    )

    run = store.get_run("run-1")
    assert run["action_results"][0]["backend"] == "fake"
    assert run["policy_decisions"][0]["decision"] == "allow"
    assert run["evidence"][0]["kind"] == "capture"
    assert (tmp_path / "logs" / "evidence" / "run-1" / "manifest.json").is_file()
    assert (tmp_path / "logs" / "evidence" / "run-1" / "action-results.jsonl").is_file()


def test_policy_api_contract():
    client = TestClient(create_app())

    response = client.get("/api/v1/policy")
    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"] == "default"
    assert "desktop.mouse.input" in payload["capabilities"]

    response = client.get("/api/v1/policy/effective")
    assert response.status_code == 200
    effective = response.json()
    assert effective["profile"] == "default"
    assert "desktop.hid.input" in effective["deny"]


def test_task_authoring_cli_graph_explain_template_and_scaffold(tmp_path: Path):
    plan_dir = tmp_path / "plans" / "demo"
    _write(
        plan_dir / "manifest.yaml",
        """
        package:
          name: '@plans/demo'
          version: 0.1.0
          description: Demo
          license: MIT
        requires:
          aura: '>=0.1.0'
        exports:
          services: []
          actions:
            - name: noop
              module: plans.demo.src.actions.noop
              function: noop
              public: true
              read_only: true
          tasks: []
        """,
    )
    _write(
        plan_dir / "tasks" / "valid.yaml",
        """
        meta:
          title: Valid
        steps:
          start:
            action: noop
            params:
              value: "{{ value }}"
          next:
            action: noop
            depends_on: start
        returns:
          value: "{{ value }}"
        """,
    )
    _write(tmp_path / "context.json", '{"value": "alpha"}')

    runner = CliRunner()
    graph = runner.invoke(
        aura,
        ["task", "graph", "--base-path", str(tmp_path), "--plan", "demo", "--task-ref", "tasks:valid.yaml", "--format", "json"],
    )
    assert graph.exit_code == 0
    graph_payload = json.loads(graph.output)
    assert graph_payload["edges"] == [{"from": "start", "to": "next"}]

    explain = runner.invoke(
        aura,
        ["task", "explain", "--base-path", str(tmp_path), "--plan", "demo", "--task-ref", "tasks:valid.yaml", "--format", "json"],
    )
    assert explain.exit_code == 0
    assert json.loads(explain.output)["steps"][0]["action"] == "noop"

    rendered = runner.invoke(
        aura,
        [
            "template",
            "render",
            "--base-path",
            str(tmp_path),
            "--plan",
            "demo",
            "--task-ref",
            "tasks:valid.yaml",
            "--context",
            str(tmp_path / "context.json"),
            "--format",
            "json",
        ],
    )
    assert rendered.exit_code == 0
    payload = json.loads(rendered.output)
    assert payload["status"] == "success"
    assert payload["rendered"]["params"][0]["value"]["value"] == "alpha"

    scaffold_task = runner.invoke(
        aura,
        ["scaffold", "task", "--base-path", str(tmp_path), "--plan", "demo", "--name", "generated"],
    )
    assert scaffold_task.exit_code == 0
    assert (plan_dir / "tasks" / "generated.yaml").is_file()

    scaffold_package = runner.invoke(
        aura,
        ["scaffold", "package", "scratch", "--base-path", str(tmp_path)],
    )
    assert scaffold_package.exit_code == 0
    assert (tmp_path / "plans" / "scratch" / "manifest.yaml").is_file()

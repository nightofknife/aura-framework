import json
import ast
from pathlib import Path

import yaml

from cli import _core_smoke
from packages.aura_core.compat import CompatibilityService
from packages.aura_core.fixtures.service import FixtureService
from packages.aura_core.observability.query import ObservabilityQueryService
from packages.aura_core.observability.persistence import PersistenceLifecycleService
from packages.aura_core.observability.run_store import RunStore
from packages.aura_core.packaging.core.workspace_lifecycle import WorkspaceLifecycleService
from plans.aura_base.src.desktop_runtime import DesktopFacade


def test_framework_core_smoke_keeps_desktop_boundary():
    result = _core_smoke(profile="framework-core", minimal_workspace=True)

    assert result["status"] == "success"
    assert result["blocked_modules"] == []
    assert [step["name"] for step in result["steps"]] == [
        "import aura_core",
        "create runtime",
        "load empty/minimal workspace",
        "api health",
    ]


def test_fixture_v2_matrix_verify_all():
    result = FixtureService(Path.cwd()).verify_all()

    assert result["status"] == "success"
    fixture_ids = {item["fixture"]["id"] for item in result["fixtures"]}
    assert "capture/basic-screen" in fixture_ids
    assert "ocr/simple-text" in fixture_ids
    assert "yolo/simple-detections" in fixture_ids
    assert "failure/locator-not-found" in fixture_ids


def test_real_fixtures_are_explicit_opt_in():
    service = FixtureService(Path.cwd())

    default_ids = {item["id"] for item in service.list()}
    all_ids = {item["id"] for item in service.list(include_real=True)}
    blocked = service.run("real/capture")

    assert "real/capture" not in default_ids
    assert "real/capture" in all_ids
    assert blocked["status"] == "error"
    assert blocked["errors"][0]["code"] == "fixture_requires_side_effects"
    assert "self_check" in blocked


def test_stable_desktop_services_do_not_import_raw_desktop_apis():
    forbidden = {"win32api", "win32gui", "win32con", "win32ui", "pyautogui", "ctypes", "paddleocr", "ultralytics"}
    targets = [
        Path("plans/aura_base/src/services/screen_service.py"),
        Path("plans/aura_base/src/services/controller_service.py"),
        Path("plans/aura_base/src/actions/atomic_actions.py"),
    ]
    violations = []
    for path in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden:
                        violations.append((str(path), alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in forbidden:
                    violations.append((str(path), node.module))

    assert violations == []


def test_desktop_facade_creates_real_backend_adapters():
    facade = DesktopFacade()

    assert facade._create_backend("capture", "gdi").backend_id == "gdi"
    assert facade._create_backend("capture", "mss").backend_id == "mss"
    assert facade._create_backend("capture", "dxgi").backend_id == "dxgi"
    assert facade._create_backend("capture", "printwindow").backend_id == "printwindow"
    assert facade._create_backend("window", "win32").backend_id == "win32"
    assert facade._create_backend("ocr", "paddleocr").backend_id == "paddleocr"
    assert facade._create_backend("mouse", "win32_postmessage").backend_id == "win32_postmessage"
    assert facade._create_backend("keyboard", "win32_postmessage").backend_id == "win32_postmessage"


def test_run_store_debug_evidence_locators_and_resources(tmp_path):
    store = RunStore(tmp_path / "aura.sqlite3")
    cid = "closure-run"
    action_result = {
        "ok": False,
        "action": "plans/aura_base/find_image",
        "backend": "fake",
        "domain": "capture",
        "operation": "find_image",
        "duration_ms": 7,
        "data": {
            "value": None,
            "rendered_params": {"template": "missing.png", "threshold": 0.9},
            "locator": {
                "ok": False,
                "bbox": None,
                "score": 0.12,
                "threshold": 0.9,
                "method": "template_match",
                "backend": "fake",
                "candidates": [{"bbox": [1, 2, 20, 10], "score": 0.12}],
                "error_code": "locator_not_found",
                "message": "Template not found",
            },
        },
        "error_code": "locator_not_found",
        "message": "Template not found",
        "evidence": [
            {"kind": "capture", "path": "captures/screen.png"},
            {"kind": "locator", "payload": {"method": "template_match", "score": 0.12}},
        ],
        "fallbacks": [{"backend": "fake", "reason": "fixture"}],
    }
    policy_decision = {
        "action": "plans/aura_base/find_image",
        "profile": "default",
        "decision": "allow",
        "capabilities": ["desktop.capture.read"],
    }

    store.apply_event("queue.enqueued", {"cid": cid, "plan_name": "plans/aura_base", "task_name": "demo"}, 1)
    store.apply_event("task.started", {"cid": cid, "plan_name": "plans/aura_base", "task_name": "demo"}, 2)
    store.apply_event(
        "node.failed",
        {
            "cid": cid,
            "node_id": "find",
            "status": "failed",
            "duration_ms": 7,
            "resource_tags": ["desktop", "locator"],
            "action_result": action_result,
            "policy_decision": policy_decision,
            "exception_type": "LocatorError",
            "exception_message": "Template not found",
        },
        3,
    )
    store.apply_event("task.finished", {"cid": cid, "status": "failed", "duration_ms": 8}, 4)

    manifest = store.evidence_manifest(cid)
    debug_report = store.debug_report(cid)
    locators = store.list_locators(cid)
    resources = store.list_resource_samples()

    assert manifest["captures"][0]["path"] == "captures/screen.png"
    assert manifest["locators"]
    assert debug_report["failed_nodes"][0]["node_id"] == "find"
    assert debug_report["failed_nodes"][0]["rendered_params"]["template"] == "missing.png"
    assert any(item.get("error_code") == "locator_not_found" for item in locators)
    assert resources[0]["cid"] == cid
    store._conn.close()


def test_observability_closure_queries(tmp_path):
    store = RunStore(tmp_path / "logs" / "aura.sqlite3")
    cid = "obs-run"
    store.apply_event("queue.enqueued", {"cid": cid, "plan_name": "plans/aura_base", "task_name": "demo"}, 1)
    store.apply_event("task.started", {"cid": cid}, 2)
    store.apply_event(
        "node.failed",
        {
            "cid": cid,
            "node_id": "ocr",
            "status": "failed",
            "duration_ms": 11,
            "action_result": {
                "ok": False,
                "action": "plans/aura_base/find_text",
                "backend": "fake",
                "domain": "ocr",
                "operation": "find_text",
                "duration_ms": 11,
                "error_code": "ocr_failed",
                "message": "OCR failed",
                "data": {"rendered_params": {"text_to_find": "Aura"}},
            },
            "policy_decision": {"action": "plans/aura_base/find_text", "profile": "default", "decision": "allow"},
        },
        3,
    )
    store.apply_event("task.finished", {"cid": cid, "status": "failed"}, 4)

    query = ObservabilityQueryService(tmp_path)
    ocr_metric = next(row for row in query.desktop_metrics()["desktop"] if row["domain"] == "ocr")
    assert ocr_metric["count"] == 1
    assert query.resources()["samples"][0]["cid"] == cid
    assert query.errors_by_category("ocr_failed")["runs"]
    explained = query.run_explain(cid)
    assert explained["locators"] == []
    assert explained["rendered_params"][0]["text_to_find"] == "Aura"
    store._conn.close()
    query.store._conn.close()


def test_persistence_lifecycle_cleanup_archive_and_export(tmp_path):
    store = RunStore(tmp_path / "logs" / "aura.sqlite3")
    store.apply_event("queue.enqueued", {"cid": "persist-run", "plan_name": "demo", "task_name": "task"}, 1)
    store.apply_event("task.finished", {"cid": "persist-run", "status": "success"}, 2)
    store.record_resource_sample({"cid": "persist-run", "node_id": "n1", "duration_ms": 1})
    store._conn.close()

    service = PersistenceLifecycleService(tmp_path)
    status = service.status()
    dry_run = service.cleanup(older_than_days=0, dry_run=True)
    applied = service.cleanup(older_than_days=0, dry_run=False)
    archive = service.archive(older_than_days=0, output=tmp_path / "archive.zip")
    exported = service.export(output=tmp_path / "runs.jsonl", output_format="jsonl")

    assert status["db_exists"] is True
    assert any(item["table"] == "resource_samples" for item in dry_run["would_delete"])
    assert applied["status"] == "success"
    assert archive["status"] == "success"
    assert exported["rows"] >= 1
    assert (tmp_path / "archive.zip").is_file()
    assert (tmp_path / "runs.jsonl").is_file()


def test_package_upgrade_dry_run_apply_and_rollback(tmp_path):
    package_dir = tmp_path / "packages" / "demo"
    source_dir = tmp_path / "upgrade-source"
    _write_minimal_package(package_dir, version="0.1.0")
    _write_minimal_package(source_dir, version="0.2.0")
    (tmp_path / "workspace.yaml").write_text(
        yaml.safe_dump(
            {
                "workspace_schema_version": 1,
                "workspace": {"name": "test", "profile": "workspace-default"},
                "runtime": {"api_profile": "local_only", "desktop_profile": "default", "persistence": "sqlite"},
                "packages": [{"id": "packages/demo", "enabled": True, "source": "packages/demo"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    service = WorkspaceLifecycleService(tmp_path)
    dry_run = service.upgrade_package("packages/demo", source_dir, dry_run=True, apply=False)
    assert dry_run["status"] == "success"
    assert dry_run["will_modify_workspace"] is False
    assert yaml.safe_load((package_dir / "manifest.yaml").read_text(encoding="utf-8"))["package"]["version"] == "0.1.0"

    applied = service.upgrade_package("packages/demo", source_dir, dry_run=False, apply=True)
    assert applied["status"] == "success"
    assert yaml.safe_load((package_dir / "manifest.yaml").read_text(encoding="utf-8"))["package"]["version"] == "0.2.0"

    rolled_back = service.rollback_package("packages/demo")
    assert rolled_back["status"] == "success"
    assert yaml.safe_load((package_dir / "manifest.yaml").read_text(encoding="utf-8"))["package"]["version"] == "0.1.0"


def test_package_migrations_are_dry_run_and_trust_gated(tmp_path):
    package_dir = tmp_path / "packages" / "demo"
    _write_minimal_package(package_dir, version="0.1.0")
    migrations = package_dir / "migrations"
    migrations.mkdir()
    (migrations / "hook.py").write_text(
        "def migrate(ctx):\n    return {'ok': True, 'dry_run': ctx['dry_run']}\n",
        encoding="utf-8",
    )
    data = yaml.safe_load((package_dir / "manifest.yaml").read_text(encoding="utf-8"))
    data["compat"]["migration_hooks"] = ["migrations/hook.py"]
    (package_dir / "manifest.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    (tmp_path / "workspace.yaml").write_text(
        yaml.safe_dump(
            {
                "workspace_schema_version": 1,
                "workspace": {"name": "test", "profile": "workspace-default"},
                "runtime": {"api_profile": "local_only", "desktop_profile": "default", "persistence": "sqlite"},
                "packages": [{"id": "packages/demo", "enabled": True, "source": "packages/demo"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    service = WorkspaceLifecycleService(tmp_path)
    dry_run = service.package_migrations("packages/demo")
    blocked = service.package_migrations("packages/demo", execute=True, trusted=False)
    executed = service.package_migrations("packages/demo", execute=True, trusted=True)

    assert dry_run["reports"][0]["mode"] == "dry-run"
    assert blocked["status"] == "error"
    assert "requires --trusted" in blocked["errors"][0]["message"]
    assert executed["status"] == "success"
    assert executed["reports"][0]["result"]["ok"] is True


def test_compat_deprecations_require_migration_note_after_window(tmp_path):
    (tmp_path / "compat").mkdir()
    (tmp_path / "workspace.yaml").write_text(
        yaml.safe_dump({"workspace_schema_version": 1, "workspace": {"name": "test"}, "packages": []}),
        encoding="utf-8",
    )
    (tmp_path / "compat" / "aura-compat.yaml").write_text(
        yaml.safe_dump(
            {
                "compat_schema_version": 1,
                "aura_version": "1.0.0",
                "contracts": {},
                "deprecated": {"actions": [{"name": "old.action", "remove_after": "0.9.0"}]},
                "breaking_changes": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = CompatibilityService(tmp_path).deprecations()

    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "deprecation_missing_migration_note"


def _write_minimal_package(path: Path, *, version: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    manifest = {
        "package": {"name": "@packages/demo", "version": version, "description": "demo", "license": "MIT"},
        "requires": {"aura": ">=2.0.0"},
        "dependencies": {},
        "pypi-dependencies": {},
        "exports": {"services": [], "actions": [], "tasks": []},
        "compat": {
            "min_aura_version": "0.1.0",
            "manifest_version": 1,
            "task_dsl_version": 1,
            "migration_hooks": [],
        },
    }
    (path / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

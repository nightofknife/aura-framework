# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import yaml

from packages.aura_core.packaging.core.workspace_lifecycle import WorkspaceLifecycleService
from packages.aura_core.packaging.core.package_manager import PackageManager
from packages.aura_core.packaging.manifest.generator import ManifestGenerator
from packages.aura_core.release_packaging import ReleasePackager

pytestmark = pytest.mark.unit


def test_release_packager_builds_three_artifacts_without_gui_builder(tmp_path: Path, monkeypatch):
    base_path = Path.cwd()

    def fake_pack_gui(self, target_zip: Path, *, version: str):
        with zipfile.ZipFile(target_zip, "w") as archive:
            archive.writestr("Aura.exe", b"fake")
            archive.writestr("resources/app.asar", b"fake")
        return {"status": "success", "path": str(target_zip)}

    monkeypatch.setattr(ReleasePackager, "_pack_gui", fake_pack_gui)

    result = ReleasePackager(base_path).pack(
        version="0.1.0",
        output=tmp_path,
        release_check={"status": "success", "checks": [{"name": "unit", "status": "success"}], "failed": []},
    )

    assert result["status"] == "success"
    assert {item["type"] for item in result["artifacts"]} == {"runtime", "gui", "package"}
    assert (tmp_path / "AuraRuntime-win-x64-0.1.0.zip").is_file()
    assert (tmp_path / "AuraGUI-win-x64-0.1.0.zip").is_file()
    assert (tmp_path / "aura_base-0.1.0.aura").is_file()
    assert (tmp_path / "release-manifest.json").is_file()
    assert (tmp_path / "checksums.sha256").is_file()

    manifest = json.loads((tmp_path / "release-manifest.json").read_text(encoding="utf-8"))
    assert manifest["release_schema_version"] == 1
    assert manifest["aura_version"] == "0.1.0"
    assert manifest["release_check"]["status"] == "success"


def test_runtime_zip_boundary_and_empty_workspace(tmp_path: Path, monkeypatch):
    base_path = Path.cwd()

    def fake_pack_gui(self, target_zip: Path, *, version: str):
        with zipfile.ZipFile(target_zip, "w") as archive:
            archive.writestr("Aura.exe", b"fake")
        return {"status": "success", "path": str(target_zip)}

    monkeypatch.setattr(ReleasePackager, "_pack_gui", fake_pack_gui)
    ReleasePackager(base_path).pack(
        version="0.1.0",
        output=tmp_path,
        release_check={"status": "success", "checks": [], "failed": []},
    )

    runtime_zip = tmp_path / "AuraRuntime-win-x64-0.1.0.zip"
    with zipfile.ZipFile(runtime_zip) as archive:
        names = archive.namelist()
        assert "AuraRuntime/cli.py" in names
        assert "AuraRuntime/AuraRuntime.cmd" in names
        assert "AuraRuntime/packages/aura_core/__init__.py" in names
        assert "AuraRuntime/scripts/install_runtime.ps1" in names
        assert "AuraRuntime/scripts/start_runtime.ps1" in names
        assert "AuraRuntime/scripts/register_runtime.ps1" in names
        assert "AuraRuntime/scripts/run_runtime.ps1" in names
        assert "AuraRuntime/tests/snapshots/api-v1-stable.json" in names
        assert "AuraRuntime/tests/snapshots/contracts-v1-stable.json" in names
        assert "18098" in archive.read("AuraRuntime/AuraRuntime.cmd").decode("utf-8", errors="ignore") + archive.read("AuraRuntime/scripts/run_runtime.ps1").decode("utf-8")
        assert not any("lsns" in name.lower() for name in names)
        assert not any(name.startswith("AuraRuntime/plans/aura_base/") for name in names)
        assert not any("/node_modules/" in name or "/logs/local_api_token" in name for name in names)
        workspace = yaml.safe_load(archive.read("AuraRuntime/workspace.yaml").decode("utf-8"))
        lock = yaml.safe_load(archive.read("AuraRuntime/packages.lock.yaml").decode("utf-8"))

    assert workspace["packages"] == []
    assert lock["packages"] == []


def test_aura_base_package_manifest_is_rebased_and_installable(tmp_path: Path):
    source = Path.cwd()
    aura_path = tmp_path / "aura_base-0.1.0.aura"

    result = WorkspaceLifecycleService(source).pack_package("plans/aura_base", output=aura_path)
    assert result["status"] == "success"

    with zipfile.ZipFile(aura_path) as archive:
        names = archive.namelist()
        assert "manifest.yaml" in names
        assert "package/manifest.yaml" in names
        root_manifest = yaml.safe_load(archive.read("manifest.yaml").decode("utf-8"))
        package_manifest = yaml.safe_load(archive.read("package/manifest.yaml").decode("utf-8"))

    for manifest in (root_manifest, package_manifest):
        modules = [
            *(item["module"] for item in manifest["exports"]["services"]),
            *(item["module"] for item in manifest["exports"]["actions"]),
        ]
        assert modules
        assert all(not module.startswith("plans.aura_base.") for module in modules)
        assert any(module.startswith("src.") for module in modules)

    runtime_root = tmp_path / "runtime"
    (runtime_root / "packages").mkdir(parents=True)
    (runtime_root / "packages" / "__init__.py").write_text("", encoding="utf-8")
    (runtime_root / "plans").mkdir()
    service = WorkspaceLifecycleService(runtime_root)
    installed = service.install_package(aura_path)

    assert installed["status"] == "success"
    assert installed["target"].endswith("packages\\aura_base") or installed["target"].endswith("packages/aura_base")
    validation = service.validate_package("plans/aura_base")
    assert validation["status"] == "success"


def test_package_manager_prefers_package_relative_import_prefix(tmp_path: Path):
    package_dir = tmp_path / "packages" / "demo"
    (tmp_path / "packages").mkdir(parents=True)
    (tmp_path / "packages" / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "src" / "actions").mkdir(parents=True)
    for init in [
        package_dir / "__init__.py",
        package_dir / "src" / "__init__.py",
        package_dir / "src" / "actions" / "__init__.py",
    ]:
        init.write_text("", encoding="utf-8")
    (package_dir / "src" / "actions" / "demo_actions.py").write_text(
        "from packages.aura_core.api import action_info\n\n"
        "@action_info(name='hello', read_only=True)\n"
        "def hello():\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )
    (package_dir / "manifest.yaml").write_text(
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
  actions:
    - name: hello
      module: src.actions.demo_actions
      function: hello
      public: true
      read_only: true
  tasks: []
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "workspace.yaml").write_text(
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
""".strip()
        + "\n",
        encoding="utf-8",
    )

    manager = PackageManager(tmp_path / "packages", tmp_path / "plans")
    manager.auto_sync_manifest = False
    manager.load_all_packages()

    try:
        from packages.aura_core.api import ACTION_REGISTRY

        actions = {action.name: action for action in ACTION_REGISTRY.get_all_action_definitions()}
        assert actions["hello"].func() == "ok"
        assert actions["hello"].func.__module__ in {
            "packages.demo.src.actions.demo_actions",
            "src.actions.demo_actions",
        }
    finally:
        manager._unload_loaded_packages()


def test_package_manager_does_not_auto_sync_installed_packages(tmp_path: Path, monkeypatch):
    package_dir = tmp_path / "packages" / "demo"
    package_dir.mkdir(parents=True)
    (package_dir / "manifest.yaml").write_text(
        """
package:
  name: "@plans/demo"
  version: "0.1.0"
exports:
  actions: []
  services: []
""".strip()
        + "\n",
        encoding="utf-8",
    )

    def fail_save(self, manifest_data):  # noqa: ANN001
        raise AssertionError("installed packages must not be auto-synced")

    monkeypatch.setattr(ManifestGenerator, "save", fail_save)
    manager = PackageManager(tmp_path / "packages", tmp_path / "plans")
    manager.auto_sync_manifest = True
    manager.auto_sync_installed_packages = False

    manager._auto_sync_manifests()

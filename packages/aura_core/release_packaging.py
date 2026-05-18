# -*- coding: utf-8 -*-
"""Local release artifact packaging."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from packages.aura_core.packaging.core.workspace_lifecycle import WorkspaceLifecycleService
from packages.aura_core.utils.safe_paths import iter_package_files, scan_symlinks


RELEASE_SCHEMA_VERSION = 1
PLATFORM_ID = "win-x64"
RUNTIME_ROOT_NAME = "AuraRuntime"


class ReleasePackager:
    """Builds Aura's runtime, GUI and official base-package artifacts."""

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path).resolve()

    def pack(self, *, version: str, output: str | Path, release_check: dict[str, Any]) -> dict[str, Any]:
        output_dir = Path(output).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        artifacts: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory(prefix="aura-release-pack-") as tmp:
            stage_root = Path(tmp)
            runtime_zip = output_dir / f"AuraRuntime-{PLATFORM_ID}-{version}.zip"
            gui_zip = output_dir / f"AuraGUI-{PLATFORM_ID}-{version}.zip"
            base_package = output_dir / f"aura_base-{version}.aura"

            self._pack_runtime(stage_root / RUNTIME_ROOT_NAME, runtime_zip, version=version)
            artifacts.append(_artifact_row("runtime", runtime_zip))

            base_result = WorkspaceLifecycleService(self.base_path).pack_package("plans/aura_base", output=base_package)
            if base_result.get("status") != "success":
                return {"status": "error", "phase": "package", "detail": base_result}
            artifacts.append(_artifact_row("package", base_package, package_id="plans/aura_base"))

            gui_result = self._pack_gui(gui_zip, version=version)
            if gui_result.get("status") != "success":
                return {"status": "error", "phase": "gui", "detail": gui_result}
            artifacts.append(_artifact_row("gui", gui_zip))

        manifest_path = output_dir / "release-manifest.json"
        checksums_path = output_dir / "checksums.sha256"
        manifest = {
            "release_schema_version": RELEASE_SCHEMA_VERSION,
            "aura_version": version,
            "platform": PLATFORM_ID,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": artifacts,
            "contracts": {
                "api_version": "v1",
                "workspace_schema_version": 1,
                "lock_schema_version": 1,
                "package_archive": ".aura",
            },
            "release_check": _release_check_summary(release_check),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        checksum_rows = []
        for artifact in artifacts:
            checksum_rows.append(f"{artifact['sha256']}  {artifact['file_name']}")
        manifest_digest = _sha256_file(manifest_path)
        checksum_rows.append(f"{manifest_digest}  {manifest_path.name}")
        checksums_path.write_text("\n".join(checksum_rows) + "\n", encoding="utf-8")

        return {
            "status": "success",
            "version": version,
            "output": str(output_dir),
            "manifest": str(manifest_path),
            "checksums": str(checksums_path),
            "artifacts": artifacts,
        }

    def _pack_runtime(self, stage_dir: Path, target_zip: Path, *, version: str) -> None:
        if stage_dir.exists():
            shutil.rmtree(stage_dir)
        stage_dir.mkdir(parents=True)

        _copy_file(self.base_path / "cli.py", stage_dir / "cli.py")
        _copy_tree(self.base_path / "backend", stage_dir / "backend")
        _copy_tree(self.base_path / "packages" / "aura_core", stage_dir / "packages" / "aura_core")
        _copy_file(self.base_path / "packages" / "__init__.py", stage_dir / "packages" / "__init__.py")
        _copy_tree(self.base_path / "requirements", stage_dir / "requirements", include_names={
            "framework-core.txt",
            "workspace-default.txt",
            "workspace-default.lock",
        })
        _copy_tree(self.base_path / "compat", stage_dir / "compat")
        _copy_tree(self.base_path / "tests" / "snapshots", stage_dir / "tests" / "snapshots")
        _copy_tree(self.base_path / "docs", stage_dir / "docs", reject_payload=b"lsns")
        _copy_file(self.base_path / "config.example.yaml", stage_dir / "config.example.yaml")
        _copy_file(self.base_path / "scripts" / "AuraRuntime.cmd", stage_dir / "AuraRuntime.cmd")

        scripts_dir = stage_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        for script_name in ("install_runtime.ps1", "start_runtime.ps1", "register_runtime.ps1", "run_runtime.ps1"):
            _copy_file(self.base_path / "scripts" / script_name, scripts_dir / script_name)

        (stage_dir / "packages").mkdir(exist_ok=True)
        (stage_dir / "plans").mkdir(exist_ok=True)
        (stage_dir / "workspace.yaml").write_text(_empty_workspace_yaml(), encoding="utf-8")
        (stage_dir / "packages.lock.yaml").write_text(_empty_lock_yaml(), encoding="utf-8")
        (stage_dir / "release.json").write_text(
            json.dumps(
                {
                    "release_schema_version": RELEASE_SCHEMA_VERSION,
                    "aura_version": version,
                    "artifact_type": "runtime",
                    "platform": PLATFORM_ID,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        _assert_no_forbidden_runtime_content(stage_dir)
        _zip_directory(stage_dir, target_zip, root_name=RUNTIME_ROOT_NAME)

    def _pack_gui(self, target_zip: Path, *, version: str) -> dict[str, Any]:
        npm_cmd = "npm.cmd" if sys.platform.startswith("win") else "npm"
        gui_root = self.base_path / "aura_gui"
        package_result = subprocess.run(
            [npm_cmd, "run", "desktop:package"],
            cwd=gui_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        if package_result.returncode != 0:
            return {
                "status": "error",
                "command": "npm run desktop:package",
                "returncode": package_result.returncode,
                "stdout_tail": (package_result.stdout or "")[-4000:],
                "stderr_tail": (package_result.stderr or "")[-4000:],
            }
        zip_result = subprocess.run(
            [
                npm_cmd,
                "run",
                "desktop:zip",
                "--",
                "--version",
                version,
                "--output",
                str(target_zip),
            ],
            cwd=gui_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        if zip_result.returncode != 0:
            return {
                "status": "error",
                "command": "npm run desktop:zip",
                "returncode": zip_result.returncode,
                "stdout_tail": (zip_result.stdout or "")[-4000:],
                "stderr_tail": (zip_result.stderr or "")[-4000:],
            }
        return {"status": "success", "path": str(target_zip)}


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_tree(
    source: Path,
    target: Path,
    *,
    include_names: set[str] | None = None,
    reject_payload: bytes | None = None,
) -> None:
    symlinks = scan_symlinks(source, skip_parts={".git", "__pycache__", ".pytest_cache", "node_modules"})
    if symlinks:
        raise ValueError(f"Refusing to package symlinked tree: {symlinks[0]}")
    for file_path in iter_package_files(source, skip_parts={".git", "__pycache__", ".pytest_cache", "node_modules"}):
        rel = file_path.relative_to(source)
        if include_names is not None and rel.as_posix() not in include_names:
            continue
        payload = file_path.read_bytes()
        if reject_payload and reject_payload.lower() in payload.lower():
            continue
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(payload)


def _zip_directory(source: Path, target: Path, *, root_name: str | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        root_prefix = root_name.strip("/\\") if root_name else ""
        for directory in sorted(path for path in source.rglob("*") if path.is_dir()):
            rel = directory.relative_to(source).as_posix()
            if root_prefix:
                rel = f"{root_prefix}/{rel}" if rel else root_prefix
            archive.writestr(f"{rel}/", b"")
        for file_path in iter_package_files(source):
            rel = file_path.relative_to(source).as_posix()
            if root_prefix:
                rel = f"{root_prefix}/{rel}"
            archive.write(file_path, rel)


def _empty_workspace_yaml() -> str:
    return yaml.safe_dump(
        {
            "workspace_schema_version": 1,
            "workspace": {"name": "default", "profile": "workspace-default"},
            "runtime": {"api_profile": "local_only", "desktop_profile": "default", "persistence": "sqlite"},
            "packages": [],
        },
        allow_unicode=True,
        sort_keys=False,
    )


def _empty_lock_yaml() -> str:
    return yaml.safe_dump(
        {
            "lock_schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "packages": [],
        },
        allow_unicode=True,
        sort_keys=False,
    )


def _artifact_row(kind: str, path: Path, **extra: Any) -> dict[str, Any]:
    return {
        "type": kind,
        "file_name": path.name,
        "path": str(path),
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
        **extra,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_check_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "failed": [item.get("name") for item in result.get("failed", [])],
        "checks": [
            {"name": item.get("name"), "status": item.get("status")}
            for item in result.get("checks", [])
        ],
    }


def _assert_no_forbidden_runtime_content(stage_dir: Path) -> None:
    forbidden_anywhere = {
        ".venv",
        ".venv-test",
        "node_modules",
        "__pycache__",
        "lsns",
    }
    forbidden_root = {"logs", "diagnostics"}
    forbidden_suffixes = {".pyc", ".sqlite3"}
    for path in stage_dir.rglob("*"):
        rel_parts = path.relative_to(stage_dir).parts
        parts = set(rel_parts)
        if parts & forbidden_anywhere:
            raise ValueError(f"Forbidden runtime package path: {path}")
        if rel_parts and rel_parts[0] in forbidden_root:
            raise ValueError(f"Forbidden runtime package path: {path}")
        if path.name == "local_api_token" or path.suffix in forbidden_suffixes:
            raise ValueError(f"Forbidden runtime package file: {path}")

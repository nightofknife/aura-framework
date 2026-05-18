"""Smoke-check Aura release artifacts.

This script is intentionally standard-library only so GitHub Actions can run it
after `cli.py release pack` without installing any extra tooling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath


RUNTIME_REQUIRED = {
    "AuraRuntime/AuraRuntime.cmd",
    "AuraRuntime/scripts/run_runtime.ps1",
    "AuraRuntime/scripts/start_runtime.ps1",
    "AuraRuntime/scripts/register_runtime.ps1",
    "AuraRuntime/scripts/install_runtime.ps1",
    "AuraRuntime/cli.py",
    "AuraRuntime/workspace.yaml",
    "AuraRuntime/requirements/framework-core.txt",
    "AuraRuntime/requirements/workspace-default.txt",
    "AuraRuntime/requirements/workspace-default.lock",
}

RUNTIME_GLOBAL_DENY_PARTS = {
    ".venv",
    ".venv-test",
    "node_modules",
    "lsns",
}

RUNTIME_TOP_LEVEL_DENY_PARTS = {
    "logs",
    "diagnostics",
    "aura_gui",
    "dist",
}

PACKAGE_REQUIRED = {
    "manifest.yaml",
    "package/manifest.yaml",
    "checksums.sha256",
    "package-lock.snapshot.yaml",
    "compat-report.json",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    release_dir = Path(args.release_dir)
    version = args.version
    runtime_zip = release_dir / f"AuraRuntime-win-x64-{version}.zip"
    gui_zip = release_dir / f"AuraGUI-win-x64-{version}.zip"
    base_package = release_dir / f"aura_base-{version}.aura"
    manifest_path = release_dir / "release-manifest.json"
    checksums_path = release_dir / "checksums.sha256"

    errors: list[str] = []
    for path in (runtime_zip, gui_zip, base_package, manifest_path, checksums_path):
        if not path.is_file():
            errors.append(f"missing artifact: {path}")

    if errors:
        return _finish(errors)

    _verify_checksums(checksums_path, [runtime_zip, gui_zip, base_package, manifest_path], errors)
    _verify_manifest(manifest_path, version, errors)
    _verify_runtime_zip(runtime_zip, errors)
    _verify_gui_zip(gui_zip, errors)
    _verify_package_zip(base_package, errors)
    return _finish(errors)


def _verify_checksums(checksums_path: Path, artifacts: list[Path], errors: list[str]) -> None:
    expected: dict[str, str] = {}
    for raw in checksums_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            errors.append(f"invalid checksum line: {line}")
            continue
        expected[parts[-1].replace("\\", "/")] = parts[0].lower()

    for artifact in artifacts:
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        recorded = expected.get(artifact.name)
        if recorded != digest:
            errors.append(f"checksum mismatch for {artifact.name}: expected {recorded}, actual {digest}")


def _verify_manifest(manifest_path: Path, version: str, errors: list[str]) -> None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"release manifest is not valid JSON: {exc}")
        return

    manifest_version = manifest.get("aura_version") or manifest.get("version")
    if manifest_version != version:
        errors.append(f"release manifest version mismatch: {manifest_version} != {version}")
    artifact_types = {item.get("type") for item in manifest.get("artifacts", [])}
    for artifact_type in ("runtime", "gui", "package"):
        if artifact_type not in artifact_types:
            errors.append(f"release manifest missing artifact type: {artifact_type}")


def _verify_runtime_zip(runtime_zip: Path, errors: list[str]) -> None:
    with zipfile.ZipFile(runtime_zip) as archive:
        names = set(archive.namelist())
        missing = sorted(RUNTIME_REQUIRED - names)
        if missing:
            errors.append(f"runtime zip missing required files: {missing}")

        for name in names:
            parts_tuple = PurePosixPath(name).parts
            parts = set(parts_tuple)
            denied = sorted(parts & RUNTIME_GLOBAL_DENY_PARTS)
            if denied:
                errors.append(f"runtime zip contains denied path part {denied}: {name}")
            if (
                len(parts_tuple) >= 2
                and parts_tuple[0] == "AuraRuntime"
                and parts_tuple[1] in RUNTIME_TOP_LEVEL_DENY_PARTS
            ):
                errors.append(f"runtime zip contains denied top-level path: {name}")
            lower_name = name.lower()
            if lower_name.endswith((".sqlite3", ".pyc")) or lower_name.endswith("local_api_token"):
                errors.append(f"runtime zip contains denied generated file: {name}")

        _assert_zip_text_contains(archive, "AuraRuntime/scripts/run_runtime.ps1", "18098", errors)
        _assert_zip_text_contains(archive, "AuraRuntime/scripts/register_runtime.ps1", "info_port", errors)
        _assert_zip_text_contains(archive, "AuraRuntime/AuraRuntime.cmd", "run_runtime.ps1", errors)


def _verify_gui_zip(gui_zip: Path, errors: list[str]) -> None:
    with zipfile.ZipFile(gui_zip) as archive:
        names = archive.namelist()
        if not any(name.endswith("Aura.exe") for name in names):
            errors.append("GUI zip does not contain Aura.exe")


def _verify_package_zip(base_package: Path, errors: list[str]) -> None:
    with zipfile.ZipFile(base_package) as archive:
        names = set(archive.namelist())
        missing = sorted(PACKAGE_REQUIRED - names)
        if missing:
            errors.append(f"aura package missing required files: {missing}")
        for name in names:
            normalized = name.replace("\\", "/")
            if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
                errors.append(f"aura package contains unsafe archive path: {name}")


def _assert_zip_text_contains(archive: zipfile.ZipFile, name: str, needle: str, errors: list[str]) -> None:
    try:
        payload = archive.read(name).decode("utf-8")
    except KeyError:
        return
    if needle not in payload:
        errors.append(f"{name} does not contain expected marker: {needle}")


def _finish(errors: list[str]) -> int:
    if errors:
        print(json.dumps({"status": "error", "errors": errors}, ensure_ascii=True, indent=2))
        return 1
    print(json.dumps({"status": "success"}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

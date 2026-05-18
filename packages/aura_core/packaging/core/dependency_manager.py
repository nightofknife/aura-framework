from __future__ import annotations

import subprocess
import sys
import time
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional

from importlib import metadata
from packaging.requirements import Requirement
from packaging.specifiers import InvalidSpecifier

from packages.aura_core.config.loader import get_config_value
from packages.aura_core.observability.logging.core_logger import logger
from packages.aura_core.packaging.manifest.parser import ManifestParser
from packages.aura_core.policy import evaluate_capability_policy
from packages.aura_core.security.redaction import redact_json
from packages.aura_core.utils.safe_paths import (
    UnsafePathError,
    ensure_path_under,
    validate_safe_relative_path,
)

from .workspace_lifecycle import WorkspaceLifecycleService, normalize_package_id


@dataclass
class DependencyCheckResult:
    ok: bool
    missing: List[str]


class DependencyManager:
    """Plan dependency checker and installer (requirements.txt)."""

    def __init__(self, base_path: Path):
        self.base_path = base_path

    def ensure_plan_dependencies(self, plan_path: Path) -> DependencyCheckResult:
        req_file = plan_path / self._requirements_file_name()
        if not req_file.is_file():
            return DependencyCheckResult(ok=True, missing=[])

        requirements = self._read_requirements(req_file)
        missing = self._find_missing(requirements)
        if not missing:
            return DependencyCheckResult(ok=True, missing=[])

        logger.warning(
            "Plan dependencies missing for '%s': %s",
            plan_path.name,
            ", ".join(missing),
        )

        if self._auto_install_enabled():
            installed = self._install_requirements(req_file)
            if installed:
                missing = self._find_missing(requirements)
                if not missing:
                    return DependencyCheckResult(ok=True, missing=[])

        return DependencyCheckResult(ok=False, missing=missing)

    def _requirements_file_name(self) -> str:
        return str(get_config_value("dependencies.requirements_file", "requirements.txt"))

    def _auto_install_enabled(self) -> bool:
        return bool(get_config_value("dependencies.auto_install", False))

    def _pip_args(self) -> List[str]:
        args = get_config_value("dependencies.pip.args", [])
        return args if isinstance(args, list) else []

    def _pip_timeout(self) -> int:
        return int(get_config_value("dependencies.pip.timeout_sec", 120))

    def _install_requirements(self, req_file: Path) -> bool:
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(req_file),
            *self._pip_args(),
        ]
        try:
            logger.info("Installing plan requirements: %s", " ".join(cmd))
            result = subprocess.run(cmd, check=False, timeout=self._pip_timeout())
            if result.returncode == 0:
                return True
            logger.error("pip install failed with code %s for %s", result.returncode, req_file)
            return False
        except subprocess.TimeoutExpired:
            logger.error("pip install timed out for %s", req_file)
            return False
        except Exception as exc:
            logger.error("pip install failed for %s: %s", req_file, exc)
            return False

    def _read_requirements(self, req_file: Path) -> List[Requirement]:
        raw = self._read_requirements_lines(req_file)
        requirements: List[Requirement] = []
        for line in raw:
            try:
                requirements.append(Requirement(line))
            except (InvalidSpecifier, ValueError):
                logger.warning("Skipping invalid requirement in %s: %s", req_file.name, line)
        return requirements

    def _read_requirements_lines(self, req_file: Path, seen: Optional[set] = None) -> List[str]:
        seen = seen or set()
        req_file = req_file.resolve()
        if req_file in seen:
            return []
        seen.add(req_file)

        lines: List[str] = []
        for raw in req_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("-r") or line.startswith("--requirement"):
                parts = line.split(maxsplit=1)
                if len(parts) == 2:
                    nested = (req_file.parent / parts[1]).resolve()
                    if nested.is_file():
                        lines.extend(self._read_requirements_lines(nested, seen))
                    else:
                        logger.warning("Requirement file not found: %s", nested)
                continue

            if line.startswith("-"):
                continue

            lines.append(line)

        return lines

    def _find_missing(self, requirements: Iterable[Requirement]) -> List[str]:
        missing: List[str] = []
        for req in requirements:
            if req.marker and not req.marker.evaluate():
                continue
            try:
                version = metadata.version(req.name)
            except metadata.PackageNotFoundError:
                missing.append(str(req))
                continue
            if req.specifier and not req.specifier.contains(version, prereleases=True):
                missing.append(f"{req.name}{req.specifier}")
        return missing


class PackageDependencyService:
    """Explicit package dependency doctor/plan/install workflow."""

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path).resolve()
        self.workspace = WorkspaceLifecycleService(self.base_path)
        self.requirements_file_name = str(get_config_value("dependencies.requirements_file", "requirements.txt", base_path=str(self.base_path)))

    def doctor(self, package_id: str, *, profile: str = "workspace-default") -> dict[str, Any]:
        result = self._collect(package_id, profile=profile)
        if result.get("status") == "error":
            return result
        errors = [
            _dependency_error(row)
            for row in result["dependencies"]
            if row["status"] in {"missing", "version_mismatch", "invalid", "blocked"}
        ]
        return {
            **result,
            "status": "error" if errors else "success",
            "errors": errors,
            "missing": [row["requirement"] for row in result["dependencies"] if row["status"] in {"missing", "version_mismatch"}],
        }

    def plan(self, package_id: str, *, profile: str = "workspace-default") -> dict[str, Any]:
        doctor = self.doctor(package_id, profile=profile)
        if doctor.get("status") == "error":
            blocking = [
                item
                for item in doctor.get("errors", [])
                if item.get("code") not in {"dependency_missing", "dependency_version_mismatch"}
            ]
            if blocking:
                return {**doctor, "will_install": False, "install_requirements": [], "pip_command": []}
        install_rows = [
            row
            for row in doctor.get("dependencies", [])
            if row.get("status") in {"missing", "version_mismatch"}
        ]
        install_requirements = list(dict.fromkeys(row["requirement"] for row in install_rows))
        pip_command = _pip_install_command(install_requirements, base_path=self.base_path) if install_requirements else []
        return {
            **doctor,
            "status": "error"
            if any(err.get("code") not in {"dependency_missing", "dependency_version_mismatch"} for err in doctor.get("errors", []))
            else "success",
            "will_install": bool(install_requirements),
            "install_requirements": install_requirements,
            "pip_command": pip_command,
            "steps": [
                "check package trust",
                "check filesystem.write policy",
                "check network.remote policy when --allow-network is used",
                "run pip install for missing/version-mismatched requirements",
                "record dependency operation",
            ],
        }

    def install(
        self,
        package_id: str,
        *,
        profile: str = "workspace-default",
        apply: bool = False,
        trusted: bool = False,
        allow_network: bool = False,
    ) -> dict[str, Any]:
        plan = self.plan(package_id, profile=profile)
        plan["dry_run"] = not apply
        if plan.get("status") != "success":
            return plan
        if not plan.get("will_install"):
            result = {**plan, "status": "success", "message": "All package dependencies are already satisfied.", "installed": []}
            self._record_operation(result)
            return result
        if not apply:
            return plan
        if not trusted:
            return {**plan, "status": "error", "errors": [{"code": "package_trust_required", "message": "Installing package dependencies requires --trusted."}]}
        if not allow_network:
            return {**plan, "status": "error", "errors": [{"code": "network_not_confirmed", "message": "Installing missing dependencies may contact package indexes; pass --allow-network and use a policy profile that allows network.remote."}]}

        policy_checks = [
            evaluate_capability_policy(
                subject="package.deps.install",
                package_id=plan["package_id"],
                capabilities=["filesystem.write"],
                side_effect_level="write",
            ),
            evaluate_capability_policy(
                subject="package.deps.install.network",
                package_id=plan["package_id"],
                capabilities=["network.remote"],
                side_effect_level="network",
            ),
        ]
        denied = [decision.to_dict() for decision in policy_checks if decision.decision != "allow"]
        if denied:
            return {**plan, "status": "error", "policy_decisions": [item.to_dict() for item in policy_checks], "errors": [{"code": "policy_denied", "decisions": denied}]}

        command = list(plan["pip_command"])
        started = time.time()
        try:
            completed = subprocess.run(
                command,
                cwd=self.base_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_pip_timeout(self.base_path),
                check=False,
            )
            result = {
                **plan,
                "status": "success" if completed.returncode == 0 else "error",
                "returncode": completed.returncode,
                "duration_ms": int((time.time() - started) * 1000),
                "stdout_tail": (completed.stdout or "")[-4000:],
                "stderr_tail": (completed.stderr or "")[-4000:],
                "policy_decisions": [item.to_dict() for item in policy_checks],
                "installed": plan["install_requirements"] if completed.returncode == 0 else [],
            }
        except subprocess.TimeoutExpired as exc:
            result = {
                **plan,
                "status": "error",
                "duration_ms": int((time.time() - started) * 1000),
                "errors": [{"code": "pip_timeout", "message": str(exc)}],
                "policy_decisions": [item.to_dict() for item in policy_checks],
            }
        self._record_operation(result)
        return result

    def _collect(self, package_id: str, *, profile: str) -> dict[str, Any]:
        target_id = normalize_package_id(package_id)
        try:
            package_dir = self._package_dir(target_id)
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "package_id": target_id, "profile": profile, "dependencies": [], "errors": [{"code": "package_not_found", "message": str(exc)}]}
        manifest_path = package_dir / "manifest.yaml"
        if not manifest_path.is_file():
            return {"status": "error", "package_id": target_id, "profile": profile, "dependencies": [], "errors": [{"code": "manifest_missing", "path": str(manifest_path)}]}

        manifest = ManifestParser.parse(manifest_path)
        rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        req_file = package_dir / self.requirements_file_name
        if req_file.is_file():
            collected = self._read_requirement_rows(req_file, package_dir=package_dir)
            rows.extend(collected["rows"])
            errors.extend(collected["errors"])
        for name, spec in (manifest.pypi_dependencies or {}).items():
            rows.append(self._row_for_requirement(_requirement_from_manifest(str(name), str(spec or "")), source="manifest:pypi-dependencies"))

        rows = _dedupe_dependency_rows(rows)
        errors.extend(_dependency_error(row) for row in rows if row["status"] in {"invalid", "blocked"})
        return {
            "status": "error" if errors else "success",
            "package_id": target_id,
            "package_path": str(package_dir),
            "profile": profile,
            "requirements_file": str(req_file) if req_file.is_file() else None,
            "dependencies": rows,
            "errors": errors,
        }

    def _read_requirement_rows(self, req_file: Path, *, package_dir: Path, seen: set[Path] | None = None) -> dict[str, Any]:
        seen = seen or set()
        req_file = req_file.resolve()
        if req_file in seen:
            return {"rows": [], "errors": []}
        seen.add(req_file)
        rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for line_no, raw in enumerate(req_file.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-r") or line.startswith("--requirement"):
                parts = line.split(maxsplit=1)
                if len(parts) != 2:
                    errors.append({"code": "dependency_invalid", "path": str(req_file), "line": line_no, "message": "Invalid requirement include."})
                    continue
                nested = (req_file.parent / parts[1]).resolve()
                if not _allowed_requirement_file(nested, package_dir=package_dir, base_path=self.base_path):
                    errors.append({"code": "dependency_include_outside_allowed_roots", "path": str(req_file), "line": line_no, "include": str(nested)})
                    continue
                if not nested.is_file():
                    errors.append({"code": "dependency_include_missing", "path": str(req_file), "line": line_no, "include": str(nested)})
                    continue
                nested_result = self._read_requirement_rows(nested, package_dir=package_dir, seen=seen)
                rows.extend(nested_result["rows"])
                errors.extend(nested_result["errors"])
                continue
            if line.startswith("-"):
                errors.append({"code": "dependency_option_unsupported", "path": str(req_file), "line": line_no, "message": f"Unsupported pip option in package requirements: {line}"})
                continue
            rows.append(self._row_for_requirement(line, source=f"{req_file.relative_to(self.base_path).as_posix()}:{line_no}"))
        return {"rows": rows, "errors": errors}

    def _row_for_requirement(self, requirement_text: str, *, source: str) -> dict[str, Any]:
        row = {"source": source, "requirement": requirement_text, "name": "", "status": "invalid", "installed_version": None}
        try:
            requirement = Requirement(requirement_text)
        except Exception as exc:  # noqa: BLE001
            return {**row, "error_code": "dependency_invalid", "message": str(exc)}
        row["name"] = requirement.name
        row["requirement"] = str(requirement)
        if requirement.marker and not requirement.marker.evaluate():
            return {**row, "status": "skipped_marker"}
        if requirement.url:
            return {**row, "status": "blocked", "error_code": "dependency_direct_reference_disallowed", "message": "Direct URL/path requirements are not allowed for automatic package dependency install."}
        try:
            installed_version = metadata.version(requirement.name)
        except metadata.PackageNotFoundError:
            return {**row, "status": "missing"}
        if requirement.specifier and not requirement.specifier.contains(installed_version, prereleases=True):
            return {**row, "status": "version_mismatch", "installed_version": installed_version}
        return {**row, "status": "installed", "installed_version": installed_version}

    def _package_dir(self, package_id: str) -> Path:
        target_id = normalize_package_id(package_id)
        for ref in self.workspace.package_refs():
            if ref.id != target_id:
                continue
            relative = validate_safe_relative_path(ref.source, label="package source")
            candidate = (self.base_path / relative).resolve()
            for root in (self.base_path / "plans", self.base_path / "packages"):
                try:
                    return ensure_path_under(root, candidate, label="package source", allow_root=False)
                except UnsafePathError:
                    continue
        raise ValueError(f"Package '{target_id}' is not declared in workspace.")

    def _record_operation(self, payload: dict[str, Any]) -> None:
        log_dir = self.base_path / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "package-dependencies.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(redact_json({"created_at_ms": int(time.time() * 1000), **payload}), ensure_ascii=False, default=str) + "\n")


def _dependency_error(row: dict[str, Any]) -> dict[str, Any]:
    status = row.get("status")
    if status == "missing":
        return {"code": "dependency_missing", "requirement": row.get("requirement"), "source": row.get("source")}
    if status == "version_mismatch":
        return {"code": "dependency_version_mismatch", "requirement": row.get("requirement"), "installed_version": row.get("installed_version"), "source": row.get("source")}
    if status == "blocked":
        return {"code": row.get("error_code") or "dependency_blocked", "requirement": row.get("requirement"), "source": row.get("source"), "message": row.get("message")}
    return {"code": row.get("error_code") or "dependency_invalid", "requirement": row.get("requirement"), "source": row.get("source"), "message": row.get("message")}


def _requirement_from_manifest(name: str, spec: str) -> str:
    spec = str(spec or "").strip()
    if not spec or spec == "*":
        return name
    if spec.startswith(("==", "!=", ">=", "<=", "~=", ">", "<")):
        return f"{name}{spec}"
    if spec.lower().startswith(name.lower()):
        return spec
    return f"{name}=={spec}"


def _dedupe_dependency_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("requirement") or row.get("name") or "").lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _allowed_requirement_file(path: Path, *, package_dir: Path, base_path: Path) -> bool:
    allowed_roots = [package_dir.resolve(), (base_path / "requirements").resolve()]
    for root in allowed_roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _pip_install_command(requirements: list[str], *, base_path: Path) -> list[str]:
    return [sys.executable, "-m", "pip", "install", *requirements, *_pip_args(base_path)]


def _pip_args(base_path: Path) -> list[str]:
    args = get_config_value("dependencies.pip.args", [], base_path=str(base_path))
    return [str(item) for item in args] if isinstance(args, list) else []


def _pip_timeout(base_path: Path) -> int:
    return int(get_config_value("dependencies.pip.timeout_sec", 120, base_path=str(base_path)))

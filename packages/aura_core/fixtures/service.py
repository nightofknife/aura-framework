# -*- coding: utf-8 -*-
"""Fixture and fake E2E harness for desktop automation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


FIXTURE_SCHEMA_VERSION = 2
SUPPORTED_FIXTURE_SCHEMA_VERSIONS = {1, 2}


class FixtureService:
    """Runs deterministic fake/fixture backend checks without desktop side effects."""

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path).resolve()
        self.fixture_root = self.base_path / "tests" / "fixtures" / "desktop"

    def list(self, *, include_real: bool = False) -> list[dict[str, Any]]:
        rows = []
        for path in self._fixture_files():
            fixture = self._load_fixture(path)
            real = _is_real_fixture(fixture)
            if real and not include_real:
                continue
            rows.append(
                {
                    "id": fixture.get("id") or path.stem,
                    "path": str(path),
                    "desktop_profile": fixture.get("desktop_profile", "fixture"),
                    "schema_version": fixture.get("fixture_schema_version", 1),
                    "side_effects": real,
                    "markers": fixture.get("markers", []),
                }
            )
        return rows

    def run(self, name: str, *, allow_side_effects: bool = False) -> dict[str, Any]:
        path = self._resolve_fixture(name)
        fixture = self._load_fixture(path)
        if _is_real_fixture(fixture) and not allow_side_effects:
            return {
                "status": "error",
                "fixture": {"id": fixture.get("id"), "path": str(path), "desktop_profile": fixture.get("desktop_profile", "real")},
                "errors": [
                    {
                        "code": "fixture_requires_side_effects",
                        "message": "Real desktop/raw/hid/yolo fixtures are opt-in; pass allow_side_effects=True.",
                    }
                ],
                "self_check": _desktop_self_check(),
            }
        errors = self._validate_fixture(fixture, path)
        action_results = []
        for index, expected in enumerate(fixture.get("expected", {}).get("actions", []) or []):
            if not isinstance(expected, dict):
                continue
            action_results.append(
                {
                    "node_id": f"fixture_step_{index + 1}",
                    "ok": bool(expected.get("ok", True)),
                    "action": expected.get("action"),
                    "backend": expected.get("backend", "fake"),
                    "duration_ms": 0,
                    "data": {"value": expected.get("data", {})},
                    "evidence": _fixture_evidence(fixture, expected),
                    "fallbacks": list(expected.get("fallbacks") or fixture.get("fallbacks") or []),
                }
            )
        diagnostics = fixture.get("expected", {}).get("diagnostics", {}) or {}
        status = "error" if errors or any(not item["ok"] for item in action_results) else "success"
        return {
            "status": status,
            "fixture": {
                "id": fixture.get("id"),
                "path": str(path),
                "desktop_profile": fixture.get("desktop_profile", "fixture"),
                "schema_version": fixture.get("fixture_schema_version", 1),
            },
            "errors": errors,
            "action_results": action_results,
            "captures": fixture.get("expected", {}).get("captures", []),
            "locators": fixture.get("expected", {}).get("locators", []),
            "ocr": fixture.get("expected", {}).get("ocr", []),
            "yolo": fixture.get("expected", {}).get("yolo", []),
            "window": fixture.get("window") or fixture.get("expected", {}).get("window"),
            "diagnostics": diagnostics,
        }

    def verify(self, name: str, *, update_snapshot: bool = False, allow_side_effects: bool = False) -> dict[str, Any]:
        path = self._resolve_fixture(name)
        result = self.run(name, allow_side_effects=allow_side_effects)
        snapshot_path = path.with_name("snapshot.json") if path.name == "fixture.yaml" else path.with_suffix(".snapshot.json")
        normalized = _snapshot_payload(result)
        if update_snapshot:
            snapshot_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return {"status": "success", "fixture": result["fixture"], "snapshot_path": str(snapshot_path), "updated": True}
        if not snapshot_path.is_file():
            return {
                "status": "error",
                "fixture": result["fixture"],
                "snapshot_path": str(snapshot_path),
                "errors": [{"code": "snapshot_missing", "message": "Fixture snapshot is missing."}],
            }
        expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if expected != normalized:
            return {
                "status": "error",
                "fixture": result["fixture"],
                "snapshot_path": str(snapshot_path),
                "errors": [{"code": "snapshot_mismatch", "message": "Fixture output differs from snapshot."}],
                "expected": expected,
                "actual": normalized,
            }
        return {"status": "success", "fixture": result["fixture"], "snapshot_path": str(snapshot_path), "errors": []}

    def verify_all(self, *, include_real: bool = False, allow_side_effects: bool = False) -> dict[str, Any]:
        results = [self.verify(row["id"], allow_side_effects=allow_side_effects) for row in self.list(include_real=include_real)]
        errors = [item for item in results if item.get("status") != "success"]
        return {
            "status": "error" if errors else "success",
            "fixtures": results,
            "errors": errors,
            "include_real": include_real,
            "self_check": _desktop_self_check() if include_real else None,
        }

    def doctor(self) -> dict[str, Any]:
        errors = []
        warnings = []
        ids: set[str] = set()
        for path in self._fixture_files():
            try:
                fixture = self._load_fixture(path)
            except Exception as exc:  # noqa: BLE001
                errors.append({"code": "fixture_parse_failed", "path": str(path), "message": str(exc)})
                continue
            fixture_id = str(fixture.get("id") or path.parent.name)
            if fixture_id in ids:
                errors.append({"code": "fixture_duplicate_id", "id": fixture_id, "path": str(path)})
            ids.add(fixture_id)
            errors.extend(self._validate_fixture(fixture, path))
            if not (path.with_name("snapshot.json") if path.name == "fixture.yaml" else path.with_suffix(".snapshot.json")).is_file():
                warnings.append({"code": "fixture_snapshot_missing", "id": fixture_id, "path": str(path)})
        return {"status": "error" if errors else "success", "errors": errors, "warnings": warnings}

    def update(self, name: str, *, snapshot_only: bool = True) -> dict[str, Any]:
        result = self.verify(name, update_snapshot=True)
        result["snapshot_only"] = snapshot_only
        return result

    def _fixture_files(self) -> list[Path]:
        if not self.fixture_root.exists():
            return []
        files = [*self.fixture_root.glob("*.yaml"), *self.fixture_root.rglob("fixture.yaml")]
        return sorted({path.resolve() for path in files})

    def _resolve_fixture(self, name: str) -> Path:
        for path in self._fixture_files():
            fixture = self._load_fixture(path)
            if name in {str(fixture.get("id")), path.stem, path.parent.name}:
                return path
        raise FileNotFoundError(f"Fixture not found: {name}")

    @staticmethod
    def _load_fixture(path: Path) -> dict[str, Any]:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Fixture must contain a mapping: {path}")
        return data

    @staticmethod
    def _validate_fixture(fixture: dict[str, Any], path: Path) -> list[dict[str, Any]]:
        errors = []
        real_fixture = _is_real_fixture(fixture)
        if fixture.get("fixture_schema_version", 1) not in SUPPORTED_FIXTURE_SCHEMA_VERSIONS:
            errors.append({"code": "fixture_schema_unsupported", "path": str(path), "supported": sorted(SUPPORTED_FIXTURE_SCHEMA_VERSIONS)})
        for action in fixture.get("expected", {}).get("actions", []) or []:
            if not isinstance(action, dict):
                errors.append({"code": "fixture_action_invalid", "path": str(path)})
                continue
            backend = action.get("backend", "fake")
            if backend not in {"fake", "fixture"} and not real_fixture:
                errors.append(
                    {
                        "code": "fixture_backend_not_fake",
                        "backend": backend,
                        "path": str(path),
                        "message": "Fixture run only allows fake/fixture backends.",
                    }
                )
        return errors


def _snapshot_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "fixture": {
            "id": result.get("fixture", {}).get("id"),
            "desktop_profile": result.get("fixture", {}).get("desktop_profile"),
            "schema_version": result.get("fixture", {}).get("schema_version"),
        },
        "action_results": [
            {
                "ok": item.get("ok"),
                "action": item.get("action"),
                "backend": item.get("backend"),
                "data": item.get("data"),
            }
            for item in result.get("action_results", [])
        ],
        "captures": result.get("captures") or [],
        "locators": result.get("locators") or [],
        "ocr": result.get("ocr") or [],
        "yolo": result.get("yolo") or [],
        "window": result.get("window"),
        "diagnostics": result.get("diagnostics") or {},
    }


def _fixture_evidence(fixture: dict[str, Any], expected_action: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = list(expected_action.get("evidence") or [])
    expected = fixture.get("expected", {}) or {}
    for capture in expected.get("captures", []) or []:
        evidence.append({"kind": "capture", "payload": capture})
    for locator in expected.get("locators", []) or []:
        evidence.append({"kind": "locator", "payload": locator})
    for ocr in expected.get("ocr", []) or []:
        evidence.append({"kind": "ocr", "payload": ocr})
    for yolo in expected.get("yolo", []) or []:
        evidence.append({"kind": "yolo", "payload": yolo})
    if fixture.get("window") or expected.get("window"):
        evidence.append({"kind": "window", "payload": fixture.get("window") or expected.get("window")})
    return evidence


def _is_real_fixture(fixture: dict[str, Any]) -> bool:
    markers = {str(item).lower() for item in fixture.get("markers", []) or []}
    real_markers = {"desktop", "raw_input", "hid", "yolo", "slow", "real"}
    profile = str(fixture.get("desktop_profile") or "").lower()
    return bool(fixture.get("side_effects")) or bool(markers & real_markers) or profile in {"real", "desktop", "raw", "hid"}


def _desktop_self_check() -> dict[str, Any]:
    try:
        from plans.aura_base.src.desktop_runtime import get_desktop_registry

        return get_desktop_registry().self_check()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

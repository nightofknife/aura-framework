# -*- coding: utf-8 -*-

from __future__ import annotations

import shutil
import tempfile
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.dependencies import reset_core_scheduler
from backend.run import serve_api
from packages.aura_core.config.loader import reset_config_service_cache

pytestmark = pytest.mark.security


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def _build_workspace(root: Path) -> None:
    (root / "packages").mkdir(parents=True, exist_ok=True)
    tasks_dir = root / "plans" / "demo" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    _write_text(
        tasks_dir / "valid.yaml",
        """
        meta:
          title: Valid Task
        steps:
          start:
            action: test.noop
        """,
    )


def _build_app(monkeypatch: pytest.MonkeyPatch, **env: str):
    for key in (
        "AURA_BASE_PATH",
        "AURA_API_HOST",
        "AURA_API_PORT",
        "AURA_API_REMOTE_ENABLED",
        "AURA_API_AUTH_KEY",
        "AURA_API_TRUSTED_HOSTS",
        "AURA_API_ENABLE_LOGS",
        "AURA_API_ENABLE_PLAN_EDITING",
        "AURA_API_ENABLE_HOT_RELOAD_ADMIN",
        "AURA_API_ENABLE_PACKAGE_ADMIN",
        "AURA_API_CORS_ENABLED",
        "AURA_API_CORS_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    reset_core_scheduler()
    return create_app()


def test_local_only_mode_allows_public_health_but_blocks_remote_protected_route(monkeypatch):
    app = _build_app(monkeypatch)

    with TestClient(app, client=("203.0.113.7", 50000)) as client:
        assert client.get("/api/v1/system/health").status_code == 200
        assert client.get("/api/v1/system/status").status_code == 200

        protected = client.get("/api/v1/plans")
        assert protected.status_code == 403
        assert protected.json()["detail"] == "Local access only."


def test_remote_mode_requires_api_key_for_protected_routes(monkeypatch):
    app = _build_app(
        monkeypatch,
        AURA_API_REMOTE_ENABLED="1",
        AURA_API_AUTH_KEY="secret-key",
        AURA_API_TRUSTED_HOSTS="api.example",
        AURA_API_HOST="0.0.0.0",
    )

    with TestClient(
        app,
        base_url="http://api.example",
        client=("203.0.113.7", 50000),
    ) as client:
        assert client.get("/api/v1/system/health").status_code == 200
        assert client.get("/api/v1/system/status").status_code == 200

        missing = client.get("/api/v1/plans")
        assert missing.status_code == 401
        assert missing.json()["detail"] == "Missing API key."

        invalid = client.get("/api/v1/plans", headers={"X-Aura-Api-Key": "wrong"})
        assert invalid.status_code == 403
        assert invalid.json()["detail"] == "Invalid API key."

        allowed = client.get("/api/v1/plans", headers={"X-Aura-Api-Key": "secret-key"})
        assert allowed.status_code == 200


def test_feature_flagged_routes_are_closed_by_default(monkeypatch):
    app = _build_app(monkeypatch)

    with TestClient(app) as client:
        assert client.get("/api/v1/system/logs").status_code == 404
        assert client.get("/api/v1/system/hot_reload/status").status_code == 404
        assert client.get("/api/v1/plans/demo/files/tree").status_code == 404
        assert client.delete("/api/v1/plans/demo").status_code == 404
        assert client.post("/api/v1/workspace/packages/plans%2Faura_benchmark/enable").status_code == 404


def test_local_only_mutating_routes_require_token(monkeypatch):
    app = _build_app(monkeypatch, AURA_API_AUTH_KEY="local-secret")

    with TestClient(app) as client:
        missing = client.post("/api/v1/system/start")
        assert missing.status_code == 401
        assert missing.json()["detail"] == "Missing local API token."

        invalid = client.post("/api/v1/system/start", headers={"X-Aura-Api-Key": "wrong"})
        assert invalid.status_code == 403
        assert invalid.json()["detail"] == "Invalid local API token."


def test_local_only_mode_allows_loopback_gui_dev_cors(monkeypatch):
    app = _build_app(monkeypatch)

    with TestClient(app) as client:
        response = client.options(
            "/api/v1/observability/errors/summary",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_feature_flags_restore_logs_hot_reload_and_plan_file_routes(monkeypatch):
    temp_root = Path.cwd() / ".pytest_tmp"
    temp_root.mkdir(exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="aura-security-", dir=str(temp_root)))
    _build_workspace(workspace)

    try:
        app = _build_app(
            monkeypatch,
            AURA_BASE_PATH=str(workspace),
            AURA_API_AUTH_KEY="local-secret",
            AURA_API_ENABLE_LOGS="1",
            AURA_API_ENABLE_PLAN_EDITING="1",
            AURA_API_ENABLE_HOT_RELOAD_ADMIN="1",
        )

        with TestClient(app) as client:
            headers = {"X-Aura-Api-Key": "local-secret"}
            assert client.get("/api/v1/system/logs").status_code == 200
            assert client.get("/api/v1/system/hot_reload/status").status_code == 200

            tree_resp = client.get("/api/v1/plans/demo/files/tree")
            assert tree_resp.status_code == 200
            assert "tasks" in tree_resp.json()

            delete_resp = client.delete("/api/v1/plans/demo", headers=headers)
            assert delete_resp.status_code == 200
            assert "removed" in delete_resp.json()["message"].lower()
    finally:
        reset_core_scheduler()
        shutil.rmtree(workspace, ignore_errors=True)


def test_non_loopback_bind_requires_explicit_remote_mode(monkeypatch):
    monkeypatch.delenv("AURA_API_REMOTE_ENABLED", raising=False)
    monkeypatch.delenv("AURA_API_AUTH_KEY", raising=False)
    monkeypatch.delenv("AURA_API_TRUSTED_HOSTS", raising=False)
    reset_config_service_cache()

    try:
        with pytest.raises(RuntimeError, match="AURA_API_REMOTE_ENABLED=1"):
            serve_api(host="0.0.0.0", port=19098)
    finally:
        reset_config_service_cache()


def test_remote_bind_requires_auth_material_and_sets_uvicorn_host(monkeypatch):
    calls = []

    def _fake_run(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr("backend.run.uvicorn.run", _fake_run)
    monkeypatch.setenv("AURA_API_REMOTE_ENABLED", "1")
    monkeypatch.setenv("AURA_API_AUTH_KEY", "secret-key")
    monkeypatch.setenv("AURA_API_TRUSTED_HOSTS", "api.example,127.0.0.1")
    reset_config_service_cache()

    try:
        serve_api(host="0.0.0.0", port=19099, access_log=False)
    finally:
        reset_config_service_cache()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == "backend.api.app:create_app"
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 19099
    assert kwargs["access_log"] is False
    assert kwargs["factory"] is True

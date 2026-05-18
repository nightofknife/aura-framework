# -*- coding: utf-8 -*-
"""API security and exposure controls."""

from __future__ import annotations

import ipaddress
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from packages.aura_core.config.loader import get_config_bool, get_config_list, get_config_value
from packages.aura_core.observability.logging.core_logger import logger

_PUBLIC_ROUTES = {
    ("GET", "/api/v1/system/health"),
    ("GET", "/api/v1/system/status"),
}

_TEST_HOSTS = {"testclient", "testserver"}
_LOCAL_GUI_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]


@dataclass(frozen=True, slots=True)
class ApiSecuritySettings:
    bind_host: str
    mode: str
    auth_key: str
    trusted_hosts: list[str]
    enable_logs: bool
    enable_plan_editing: bool
    enable_hot_reload_admin: bool
    enable_package_admin: bool
    cors_enabled: bool
    cors_allowed_origins: list[str]


def _normalize_host_token(raw: Optional[str]) -> str:
    token = str(raw or "").strip()
    if token.startswith("[") and token.endswith("]"):
        token = token[1:-1]
    return token


def is_loopback_host(raw: Optional[str]) -> bool:
    host = _normalize_host_token(raw).lower()
    if not host:
        return False
    if host in {"localhost", "::1", "127.0.0.1"} | _TEST_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def build_api_security_settings(bind_host: Optional[str] = None) -> ApiSecuritySettings:
    resolved_host = str(bind_host or get_config_value("api.host", "127.0.0.1") or "127.0.0.1").strip()
    remote_enabled = get_config_bool("api.remote.enabled", False)
    auth_key = str(get_config_value("api.auth.key", "") or "").strip()
    trusted_hosts = get_config_list("api.trusted.hosts", [])
    enable_logs = get_config_bool("api.enable.logs", False)
    enable_plan_editing = get_config_bool("api.enable.plan.editing", False)
    enable_hot_reload_admin = get_config_bool("api.enable.hot.reload.admin", False)
    enable_package_admin = get_config_bool("api.enable.package.admin", False)
    cors_enabled = get_config_bool("api.cors.enabled", False)
    cors_allowed_origins = get_config_list("api.cors.allowed.origins", [])

    mode = "remote" if remote_enabled or not is_loopback_host(resolved_host) else "local_only"
    if not is_loopback_host(resolved_host) and not remote_enabled:
        raise RuntimeError(
            "Refusing to bind API to a non-loopback host without AURA_API_REMOTE_ENABLED=1."
        )
    if mode == "remote":
        if not auth_key:
            raise RuntimeError("Remote API mode requires AURA_API_AUTH_KEY.")
        if not trusted_hosts:
            raise RuntimeError("Remote API mode requires AURA_API_TRUSTED_HOSTS.")
    elif not cors_enabled and not cors_allowed_origins:
        cors_enabled = True
        cors_allowed_origins = list(_LOCAL_GUI_ORIGINS)
    elif cors_enabled and not cors_allowed_origins and mode == "local_only":
        cors_allowed_origins = list(_LOCAL_GUI_ORIGINS)

    return ApiSecuritySettings(
        bind_host=resolved_host,
        mode=mode,
        auth_key=auth_key,
        trusted_hosts=trusted_hosts,
        enable_logs=enable_logs,
        enable_plan_editing=enable_plan_editing,
        enable_hot_reload_admin=enable_hot_reload_admin,
        enable_package_admin=enable_package_admin,
        cors_enabled=cors_enabled,
        cors_allowed_origins=cors_allowed_origins,
    )


def apply_api_security(app: FastAPI, settings: Optional[ApiSecuritySettings] = None) -> ApiSecuritySettings:
    resolved = settings or build_api_security_settings()
    app.state.api_security = resolved

    if resolved.mode == "remote":
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=resolved.trusted_hosts)

    if resolved.cors_enabled and resolved.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved.cors_allowed_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if _is_feature_disabled(request, resolved):
            _log_rejection(request, "feature_disabled")
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

        if request.method.upper() == "OPTIONS" or _is_public_route(request):
            return await call_next(request)

        client_host = request.client.host if request.client else None
        if resolved.mode == "local_only":
            if not is_loopback_host(client_host):
                _log_rejection(request, "local_only")
                return JSONResponse(status_code=403, content={"detail": "Local access only."})
            if _is_mutating_request(request):
                local_key = _local_auth_key(resolved)
                supplied_key = _supplied_local_token(request)
                if not supplied_key:
                    _log_rejection(request, "missing_local_token")
                    return JSONResponse(status_code=401, content={"detail": "Missing local API token."})
                if not secrets.compare_digest(supplied_key, local_key):
                    _log_rejection(request, "invalid_local_token")
                    return JSONResponse(status_code=403, content={"detail": "Invalid local API token."})
                if not _browser_origin_allowed(request, resolved):
                    _log_rejection(request, "cross_site_mutation")
                    return JSONResponse(status_code=403, content={"detail": "Cross-site mutation rejected."})
            return await call_next(request)

        supplied_key = str(request.headers.get("X-Aura-Api-Key", "") or "").strip()
        if not supplied_key:
            _log_rejection(request, "missing_api_key")
            return JSONResponse(status_code=401, content={"detail": "Missing API key."})
        if not secrets.compare_digest(supplied_key, resolved.auth_key):
            _log_rejection(request, "invalid_api_key")
            return JSONResponse(status_code=403, content={"detail": "Invalid API key."})
        return await call_next(request)

    return resolved


def _is_public_route(request: Request) -> bool:
    return (request.method.upper(), request.url.path) in _PUBLIC_ROUTES


def _is_feature_disabled(request: Request, settings: ApiSecuritySettings) -> bool:
    path = request.url.path
    method = request.method.upper()

    if path == "/api/v1/system/logs" and not settings.enable_logs:
        return True
    if path.startswith("/api/v1/system/hot_reload/") and not settings.enable_hot_reload_admin:
        return True
    if path.startswith("/api/v1/runtime/reload/") and not settings.enable_hot_reload_admin:
        return True
    if path.startswith("/api/v1/migrations/") and method == "POST" and not settings.enable_hot_reload_admin:
        return True
    if _is_package_admin_route(path, method) and not settings.enable_package_admin:
        return True
    if path.startswith("/api/v1/plans/") and "/files/" in path and not settings.enable_plan_editing:
        return True

    parts = [part for part in path.split("/") if part]
    if (
        method == "DELETE"
        and len(parts) == 4
        and parts[:3] == ["api", "v1", "plans"]
        and not settings.enable_plan_editing
    ):
        return True
    return False


def _is_mutating_request(request: Request) -> bool:
    return request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}


def _supplied_local_token(request: Request) -> str:
    return str(
        request.headers.get("X-Aura-Api-Key")
        or request.headers.get("X-Aura-CSRF-Token")
        or ""
    ).strip()


def _local_auth_key(settings: ApiSecuritySettings) -> str:
    if settings.auth_key:
        return settings.auth_key
    base_path = Path(str(get_config_value("base.path", os.environ.get("AURA_BASE_PATH") or Path.cwd()) or Path.cwd()))
    token_path = base_path / "logs" / "local_api_token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    if token_path.is_file():
        token = token_path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    token_path.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        pass
    logger.warning("Generated local API token at %s. Mutating local API requests must send it.", token_path)
    return token


def _browser_origin_allowed(request: Request, settings: ApiSecuritySettings) -> bool:
    origin = str(request.headers.get("Origin") or "").strip()
    sec_fetch_site = str(request.headers.get("Sec-Fetch-Site") or "").strip().lower()
    if origin and origin not in settings.cors_allowed_origins:
        return False
    if sec_fetch_site and sec_fetch_site not in {"same-origin", "same-site", "none"}:
        return False
    content_type = str(request.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if origin and content_type in {"application/x-www-form-urlencoded", "multipart/form-data", "text/plain"}:
        return False
    return True


def _is_package_admin_route(path: str, method: str) -> bool:
    if method != "POST":
        return False
    if path == "/api/v1/workspace/packages/lock":
        return True
    if not path.startswith("/api/v1/workspace/packages/"):
        return False
    safe_suffixes = ("/validate", "/upgrade-plan", "/permissions", "/migrations")
    if any(path.endswith(suffix) for suffix in safe_suffixes):
        return False
    admin_suffixes = ("/upgrade", "/rollback", "/reload", "/enable", "/disable")
    return any(path.endswith(suffix) for suffix in admin_suffixes)


def _log_rejection(request: Request, reason: str) -> None:
    client_host = request.client.host if request.client else "unknown"
    logger.warning(
        "API request rejected: host=%s method=%s path=%s reason=%s",
        client_host,
        request.method.upper(),
        request.url.path,
        reason,
    )

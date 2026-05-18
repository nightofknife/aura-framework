# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
import json

import pytest

pytestmark = pytest.mark.unit


def test_gui_default_navigation_exposes_only_workbench_pages():
    config_js = Path("aura_gui/src/config.js").read_text(encoding="utf-8")
    app_vue = Path("aura_gui/src/App.vue").read_text(encoding="utf-8")

    for key in ["execute", "tasks", "runs", "capabilities", "settings"]:
        assert f"key: '{key}'" in config_js

    for experimental in [
        "dashboard",
        "actions",
        "services",
        "automation",
        "plans",
        "packages",
        "observability",
    ]:
        assert f"key: '{experimental}'" not in config_js

    assert "ExecuteView" in app_vue
    assert "PlansView" in app_vue
    assert "tasks: PlansView" in app_vue
    assert "RunsView" in app_vue
    assert "CapabilitiesView" in app_vue
    assert "SettingsView" in app_vue

    for experimental_component in [
        "DashboardView",
        "ActionsView",
        "ServicesView",
        "AutomationView",
        "WorkspacePackagesView",
        "ObservabilityView",
        "PackagesView",
    ]:
        assert experimental_component not in app_vue

    assert "./pages/PackagesView.vue" not in app_vue


def test_gui_default_pages_do_not_import_legacy_runtime_channels():
    default_pages = [
        Path("aura_gui/src/pages/ExecuteView.vue"),
        Path("aura_gui/src/pages/PlansView.vue"),
        Path("aura_gui/src/pages/RunsView.vue"),
        Path("aura_gui/src/pages/CapabilitiesView.vue"),
        Path("aura_gui/src/pages/SettingsView.vue"),
    ]
    banned_imports = [
        "axios.create",
        "useGuiQueue",
        "useStagingRunner",
        "useBackendQueue",
        "useQueueStore",
        "useAuraSockets",
    ]
    banned_routes = [
        "/actions/{fqid}",
        "/packages/{name}/manifest",
        "/services/{id}",
    ]

    for page in default_pages:
        text = page.read_text(encoding="utf-8")
        for banned in banned_imports + banned_routes:
            assert banned not in text, f"{page} still references {banned}"


def test_gui_api_client_enforces_local_token_for_mutations():
    client_js = Path("aura_gui/src/api/client.js").read_text(encoding="utf-8")
    errors_js = Path("aura_gui/src/api/errors.js").read_text(encoding="utf-8")

    assert "aura_local_api_token" in client_js
    assert "X-Aura-CSRF-Token" in client_js
    assert "post', 'put', 'patch', 'delete" in client_js
    assert "Local API token is required" in client_js
    assert "requiresToken" in errors_js


def test_gui_settings_gates_admin_actions():
    settings_vue = Path("aura_gui/src/pages/SettingsView.vue").read_text(encoding="utf-8")

    assert "localAdminEnabled" in settings_vue
    assert "adminActionDisabled" in settings_vue
    assert "tokenActionDisabled" in settings_vue
    assert "canRunAdminAction" in settings_vue
    assert "canRunMutatingAction" in settings_vue
    assert "setApiToken" in settings_vue
    assert "clearApiToken" in settings_vue
    assert "discoverRuntimeCandidates" in settings_vue
    assert "readRuntimeToken" in settings_vue


def test_hidden_ops_pages_use_shared_api_client():
    hidden_pages = [
        Path("aura_gui/src/pages/WorkspacePackagesView.vue"),
        Path("aura_gui/src/pages/ObservabilityView.vue"),
    ]

    for page in hidden_pages:
        text = page.read_text(encoding="utf-8")
        assert "axios.create" not in text, f"{page} still creates a raw axios client"


def test_electron_shell_uses_hardened_renderer_boundary():
    package_json = json.loads(Path("aura_gui/package.json").read_text(encoding="utf-8"))
    main_cjs = Path("aura_gui/electron/main.cjs").read_text(encoding="utf-8")
    preload_cjs = Path("aura_gui/electron/preload.cjs").read_text(encoding="utf-8")
    index_html = Path("aura_gui/index.html").read_text(encoding="utf-8")
    config_js = Path("aura_gui/src/config.js").read_text(encoding="utf-8")
    desktop_js = Path("aura_gui/src/api/desktop.js").read_text(encoding="utf-8")

    assert package_json["main"] == "electron/main.cjs"
    assert "desktop:dev" in package_json["scripts"]
    assert "electron" in package_json["devDependencies"]

    assert "contextIsolation: true" in main_cjs
    assert "nodeIntegration: false" in main_cjs
    assert "sandbox: true" in main_cjs
    assert "LOOPBACK_HOSTS" in main_cjs
    assert "DEFAULT_RUNTIME_PORT = 18098" in main_cjs
    assert "infoPort" in main_cjs
    assert "tokenPathAllowlist" in main_cjs

    assert "contextBridge.exposeInMainWorld('auraDesktop'" in preload_cjs
    assert "require('node:fs')" not in preload_cjs
    assert "child_process" not in preload_cjs

    assert "aura_runtime_connection" in config_js
    assert "setRuntimeConnection" in config_js
    assert "window.auraDesktop" in desktop_js
    assert "Content-Security-Policy" in index_html

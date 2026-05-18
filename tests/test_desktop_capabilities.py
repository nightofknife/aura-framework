from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from packages.aura_core.config.loader import reset_config_service_cache
from plans.aura_base.src.desktop_runtime import DesktopFacade, get_desktop_registry
from plans.aura_base.src.desktop_runtime.raw_input import normalize_raw_mouse_event


def test_capability_registry_contains_v2_backends():
    registry = get_desktop_registry()
    rows = registry.list()

    assert {"capture", "mouse", "keyboard", "window", "ocr"}.issubset(rows.keys())
    assert {item["backend_id"] for item in rows["capture"]} >= {"gdi", "mss", "dxgi", "printwindow", "fake"}
    assert {item["backend_id"] for item in rows["mouse"]} >= {
        "win32_sendinput",
        "win32_mouse_event",
        "win32_postmessage",
        "raw_input",
        "hid_mouse",
        "fake",
    }
    assert {item["backend_id"] for item in rows["keyboard"]} >= {
        "win32_sendinput",
        "win32_keybd_event",
        "win32_postmessage",
        "clipboard_paste",
        "fake",
    }

    hid_mouse = registry.get("mouse", "hid_mouse")
    assert hid_mouse is not None
    assert hid_mouse.available is False
    assert hid_mouse.last_error


def test_registry_selection_respects_explicit_fallback():
    registry = get_desktop_registry()

    explicit_missing = registry.select("mouse", requested="not_a_backend")
    assert explicit_missing.selected_backend is None
    assert explicit_missing.fallbacks[0]["reason"] == "not_registered"

    selection = registry.select("mouse", requested={"prefer": "not_a_backend", "fallback": ["fake"]})
    assert selection.selected_backend == "fake"
    assert selection.fallbacks[0]["backend"] == "not_a_backend"


def test_fake_facade_returns_structured_desktop_result():
    facade = DesktopFacade(profile="default")

    result = facade.mouse("click", backend="fake", x=10, y=20, button="left")

    assert result.ok is True
    assert result.backend == "fake"
    assert result.domain == "mouse"
    assert result.operation == "click"
    assert result.data["simulated"] is True
    assert result.error_code is None

    capture = facade.capture_screen(backend="fake")
    assert capture.ok is True
    assert capture.backend == "fake"
    assert capture.domain == "capture"
    assert capture.data["width"] == 100

    window = facade.window("list_windows", backend="fake")
    assert window.ok is True
    assert window.domain == "window"
    assert window.data["windows"][0]["title"] == "Fake Window"

    ocr = facade.ocr("recognize", backend="fake")
    assert ocr.ok is True
    assert ocr.domain == "ocr"
    assert ocr.data["simulated"] is True


def test_raw_input_normalizes_mouse_events():
    event = normalize_raw_mouse_event(
        device_handle=100,
        button_flags=0x0001 | 0x0002 | 0x0400,
        button_data=0xFF88,
        last_x=-4,
        last_y=7,
    )

    assert event.device_handle == 100
    assert event.buttons == ["left_down", "left_up"]
    assert event.wheel_delta == -120
    assert event.dx == -4
    assert event.dy == 7


def test_capabilities_api_contract(monkeypatch):
    monkeypatch.setenv("AURA_API_AUTH_KEY", "local-secret")
    reset_config_service_cache()
    client = TestClient(create_app())
    headers = {"X-Aura-Api-Key": "local-secret"}

    response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert "domains" in payload
    assert "mouse" in payload["domains"]
    assert payload["domains"]["mouse"][0]["backend_id"]

    response = client.get("/api/v1/capabilities/mouse")
    assert response.status_code == 200
    assert any(item["backend_id"] == "raw_input" for item in response.json())

    response = client.post("/api/v1/capabilities/self-check", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_sendinput_backend_can_be_monkeypatched(monkeypatch):
    ctypes = pytest.importorskip("ctypes")
    if not hasattr(ctypes, "windll"):
        pytest.skip("ctypes.windll is Windows-only")

    calls = []

    class User32:
        def SendInput(self, count, _inputs, _size):
            calls.append(count)
            return count

        def GetSystemMetrics(self, index):
            return 1920 if index == 0 else 1080

    monkeypatch.setattr(ctypes, "windll", type("Windll", (), {"user32": User32()})())

    facade = DesktopFacade()
    result = facade.mouse("click", backend="win32_sendinput", x=1, y=1)

    assert result.ok is True
    assert result.backend == "win32_sendinput"
    assert calls

from __future__ import annotations

import sys

import pytest

pytestmark = [
    pytest.mark.desktop,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows-only desktop services"),
]


class _DummyConfig:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key, default=None):
        return self._values.get(key, default)


def test_screen_service_import_and_backend_defaults():
    from plans.aura_base.src.services.screen_service import ScreenService

    service = ScreenService(config=_DummyConfig({"screen.capture.enabled_backends": ["gdi"]}))
    backends = service.list_backends()

    assert "gdi" in backends["available"]
    assert backends["default"] == "gdi"


def test_controller_service_import_smoke(monkeypatch):
    from plans.aura_base.src.services.controller_service import ControllerService

    monkeypatch.setattr(ControllerService, "__del__", lambda self: None)
    service = ControllerService()

    assert callable(service.click)
    assert callable(service.press_key)


def test_ocr_service_import_smoke():
    from plans.aura_base.src.services.ocr_service import OcrService

    service = OcrService()

    assert service._engine is None
    assert callable(service.preload_engine)

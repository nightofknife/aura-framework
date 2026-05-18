from __future__ import annotations

import pytest

from packages.aura_core.services.yolo_service import YoloService

pytestmark = pytest.mark.yolo


class _DummyConfig:
    def get(self, key, default=None):
        return default


def test_yolo_profile_import_smoke():
    pytest.importorskip("ultralytics")

    service = YoloService(config=_DummyConfig())
    yolo_cls = service._load_yolo_class()

    assert yolo_cls.__name__ == "YOLO"

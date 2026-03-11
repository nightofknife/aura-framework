from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from packages.aura_core.context.plan import current_plan_name
from packages.aura_core.services.yolo_service import YoloService


class _FakeConfig:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key, default=None):
        return self._values.get(key, default)


class _FakeTensor:
    def __init__(self, values):
        self._values = values

    def cpu(self):
        return self

    def numpy(self):
        return self._values


class _FakeBoxes:
    def __init__(self):
        self.xyxy = _FakeTensor([[10, 20, 110, 220]])
        self.conf = _FakeTensor([0.93])
        self.cls = _FakeTensor([1])


class _FakePrediction:
    def __init__(self):
        self.boxes = _FakeBoxes()


class _FakeModel:
    def __init__(self, source):
        self.source = source
        self.names = {0: "person", 1: "vehicle"}
        self.predict_calls = []

    def predict(self, **kwargs):
        self.predict_calls.append(kwargs)
        return [_FakePrediction()]


class _FakeYoloFactory:
    def __init__(self):
        self.created = []

    def __call__(self, source):
        model = _FakeModel(source)
        self.created.append(model)
        return model


class TestCoreYoloService(unittest.TestCase):
    def setUp(self):
        self.service = YoloService(config=_FakeConfig({"yolo.default_variant": "n"}))

    def test_supported_generations_cover_requested_families(self):
        self.assertEqual(
            self.service.supported_generations(),
            ["yolo8", "yolo10", "yolo11", "yolo26"],
        )

    def test_resolve_known_family_aliases(self):
        cases = {
            "yolo8": "yolov8n.pt",
            "yolov10m": "yolov10m.pt",
            "yolo11l": "yolo11l.pt",
            "yolo26x": "yolo26x.pt",
        }
        for raw, expected_source in cases.items():
            with self.subTest(raw=raw):
                ref = self.service.resolve_model_reference(raw)
                self.assertEqual(ref.source, expected_source)
                self.assertFalse(ref.is_path)

    def test_resolve_relative_path_prefers_current_plan_when_file_exists(self):
        repo_root = Path(__file__).resolve().parents[1]
        plan_file = repo_root / "plans" / "aura_benchmark" / "models" / "demo.pt"
        token = current_plan_name.set("aura_benchmark")
        try:
            with patch.object(Path, "exists", autospec=True) as exists_mock:
                def fake_exists(path_self):
                    return str(path_self).endswith(str(plan_file).replace("/", "\\"))
                exists_mock.side_effect = fake_exists
                ref = self.service.resolve_model_reference("models/demo.pt")
            self.assertTrue(ref.is_path)
            self.assertTrue(ref.source.endswith("plans\\aura_benchmark\\models\\demo.pt") or ref.source.endswith("plans/aura_benchmark/models/demo.pt"))
        finally:
            current_plan_name.reset(token)

    def test_preload_and_detect_image(self):
        fake_factory = _FakeYoloFactory()
        with patch.object(self.service, "_load_yolo_class", return_value=fake_factory):
            info = self.service.preload_model("yolo11")
            self.assertTrue(info["loaded"])
            self.assertEqual(info["family"], "yolo11")

            result = self.service.detect_image(image="dummy-image", model_name="yolo11")

        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], "yolo11n")
        self.assertEqual(len(result["detections"]), 1)
        self.assertEqual(result["detections"][0]["label"], "vehicle")
        self.assertEqual(result["detections"][0]["bbox_xywh"], [10.0, 20.0, 100.0, 200.0])
        self.assertEqual(fake_factory.created[0].predict_calls[0]["source"], "dummy-image")


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from packages.aura_core.api import register_service
from packages.aura_core.context.plan import current_plan_name
from packages.aura_core.observability.logging.core_logger import logger
from plans.aura_base.src.services.app_provider_service import AppProviderService
from plans.aura_base.src.services.config_service import ConfigService


@dataclass
class YoloResult:
    found: bool = False
    top_left: tuple[int, int] | None = None
    center_point: tuple[int, int] | None = None
    rect: tuple[int, int, int, int] | None = None
    confidence: float = 0.0
    label: str | None = None
    class_id: int | None = None
    debug_info: dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiYoloResult:
    count: int = 0
    matches: list[YoloResult] = field(default_factory=list)


@register_service(alias="yolo", public=True)
class YoloService:
    """
    Ultralytics YOLO detection service.

    - Manual preload/unload/switch for models
    - Runtime model switching
    - detect_on_screen with ROI (global coords output)
    - Only returns bbox_global (window absolute coords)
    """

    def __init__(self, app: AppProviderService, config: ConfigService):
        self.app = app
        self.config = config
        self._lock = threading.RLock()
        self._models: Dict[str, Any] = {}
        self._names: Dict[str, Dict[int, str]] = {}
        self._active_key: Optional[str] = None

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    def preload_model(self, name: str) -> Dict[str, Any]:
        from ultralytics import YOLO

        path, key = self._resolve_model_path(name)
        with self._lock:
            if key in self._models:
                return {"ok": True, "model": key, "path": str(path), "loaded": True}

            if not path.is_file():
                raise FileNotFoundError(f"YOLO model not found: {path}")

            logger.info("Loading YOLO model: %s", path)
            model = YOLO(str(path))

            names = self._extract_names(model)
            if not names:
                raise ValueError(f"YOLO model has no names: {path}")

            self._models[key] = model
            self._names[key] = names
            logger.info("YOLO model loaded: %s (classes=%d)", key, len(names))
            return {"ok": True, "model": key, "path": str(path), "loaded": True}

    def set_active_model(self, name: str) -> Dict[str, Any]:
        path, key = self._resolve_model_path(name)
        with self._lock:
            if key not in self._models:
                self.preload_model(name)
            self._active_key = key
        return {"ok": True, "active_model": key, "path": str(path)}

    def unload_model(self, name: str) -> Dict[str, Any]:
        _, key = self._resolve_model_path(name)
        with self._lock:
            model = self._models.pop(key, None)
            self._names.pop(key, None)
            if self._active_key == key:
                self._active_key = None

        if model is not None:
            try:
                import torch
                del model
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception as exc:
                logger.warning("Failed to release YOLO model '%s': %s", key, exc)

        return {"ok": True, "unloaded": key}

    def list_loaded_models(self) -> List[str]:
        with self._lock:
            return sorted(self._models.keys())

    def get_active_model(self) -> Optional[str]:
        with self._lock:
            return self._active_key

    def get_class_names(self, model_name: Optional[str] = None) -> Dict[int, str]:
        _, key = self._get_model(model_name)
        return dict(self._names.get(key, {}))

    def resolve_class_ids(self, labels: List[str], model_name: Optional[str] = None) -> List[int]:
        if not labels:
            return []
        names = self.get_class_names(model_name)
        reverse = {v.lower(): k for k, v in names.items()}
        class_ids = []
        for label in labels:
            if not label:
                continue
            key = str(label).lower()
            if key in reverse:
                class_ids.append(int(reverse[key]))
        return class_ids

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect_on_screen(
        self,
        roi: Optional[Tuple[int, int, int, int]] = None,
        model_name: Optional[str] = None,
        **override,
    ) -> Dict[str, Any]:
        capture = self.app.capture(rect=roi)
        if not capture.success or capture.image is None:
            return {"ok": False, "error": capture.error_message or "capture failed"}

        image = capture.image  # RGB
        detections, key = self._detect_image_core(image, model_name=model_name, **override)

        base_origin = self._get_window_origin(capture)
        rel_rect = capture.relative_rect or (0, 0, image.shape[1], image.shape[0])
        offset_x = base_origin[0] + rel_rect[0]
        offset_y = base_origin[1] + rel_rect[1]

        for det in detections:
            x, y, w, h = det["bbox"]
            det["bbox_global"] = [int(x + offset_x), int(y + offset_y), int(w), int(h)]
            det.pop("bbox", None)

        return {
            "ok": True,
            "model": key,
            "image_size": [int(image.shape[1]), int(image.shape[0])],
            "detections": detections,
        }

    def detect_image(
        self,
        image: np.ndarray | str,
        model_name: Optional[str] = None,
        **override,
    ) -> Dict[str, Any]:
        img = self._load_image(image)
        detections, key = self._detect_image_core(img, model_name=model_name, **override)

        for det in detections:
            x, y, w, h = det["bbox"]
            det["bbox_global"] = [int(x), int(y), int(w), int(h)]
            det.pop("bbox", None)

        return {
            "ok": True,
            "model": key,
            "image_size": [int(img.shape[1]), int(img.shape[0])],
            "detections": detections,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_image_core(
        self,
        image: np.ndarray,
        model_name: Optional[str],
        **override,
    ) -> Tuple[List[Dict[str, Any]], str]:
        model, key = self._get_model(model_name)
        settings = self._get_infer_settings(override)

        results = model.predict(
            source=image,
            device=settings["device"],
            imgsz=settings["imgsz"],
            conf=settings["conf"],
            iou=settings["iou"],
            max_det=settings["max_det"],
            classes=settings["classes"],
            agnostic_nms=settings["agnostic_nms"],
            half=settings["half"],
            verbose=settings["verbose"],
        )

        if not results:
            return [], key

        res = results[0]
        boxes = res.boxes
        if boxes is None or boxes.xyxy is None:
            return [], key

        xyxy = boxes.xyxy.cpu().numpy()
        conf = boxes.conf.cpu().numpy()
        cls = boxes.cls.cpu().numpy().astype(int)

        names = self._names.get(key, {})
        detections: List[Dict[str, Any]] = []
        for i in range(len(xyxy)):
            x1, y1, x2, y2 = xyxy[i]
            w = x2 - x1
            h = y2 - y1
            class_id = int(cls[i])
            label = names.get(class_id, str(class_id))
            detections.append({
                "class_id": class_id,
                "label": label,
                "score": float(conf[i]),
                "bbox": [float(x1), float(y1), float(w), float(h)],
            })
        return detections, key

    def _get_model(self, model_name: Optional[str]) -> Tuple[Any, str]:
        with self._lock:
            target_name = model_name or self._active_key
            if not target_name:
                default_name = self._get("yolo.default_model", None)
                if not default_name:
                    raise ValueError("No active model and no yolo.default_model configured.")
                target_name = str(default_name)

            _, key = self._resolve_model_path(str(target_name))

            if key not in self._models:
                self.preload_model(str(target_name))

            return self._models[key], key

    def _resolve_model_path(self, name: str) -> Tuple[Path, str]:
        model_dir = Path(self._get("yolo.model_dir", "models"))
        model_ext = str(self._get("yolo.model_ext", ".pt"))

        raw = str(name).strip()
        raw_path = Path(raw)

        has_dir = raw_path.is_absolute() or raw_path.parent != Path(".")
        if has_dir:
            if raw_path.is_absolute():
                path = raw_path
            else:
                plan_root = self._get_plan_root()
                path = plan_root / raw_path
        else:
            plan_root = self._get_plan_root()
            filename = raw if raw.endswith(model_ext) else (raw + model_ext)
            path = plan_root / model_dir / filename

        key = path.stem
        return path, key

    def _get_plan_root(self) -> Path:
        env_base = os.getenv("AURA_BASE_PATH")
        if env_base:
            base_path = Path(env_base).resolve()
        else:
            base_path = Path(__file__).resolve().parents[4]

        plan_name = current_plan_name.get()
        if not plan_name:
            raise RuntimeError(
                "Cannot resolve relative YOLO model path without active plan context. "
                "Use an absolute model path or run inside a plan task."
            )

        return base_path / "plans" / plan_name

    def _extract_names(self, model: Any) -> Dict[int, str]:
        names = getattr(model, "names", None)
        if names is None and hasattr(model, "model"):
            names = getattr(model.model, "names", None)

        if isinstance(names, list):
            return {i: str(n) for i, n in enumerate(names)}
        if isinstance(names, dict):
            return {int(k): str(v) for k, v in names.items()}

        return {}

    def _get_window_origin(self, capture) -> Tuple[int, int]:
        client_rect = self.app.screen.get_client_rect()
        if client_rect:
            return int(client_rect[0]), int(client_rect[1])
        if capture.window_rect:
            return int(capture.window_rect[0]), int(capture.window_rect[1])
        return 0, 0

    def _load_image(self, image: np.ndarray | str) -> np.ndarray:
        if isinstance(image, np.ndarray):
            return image
        if isinstance(image, str):
            bgr = cv2.imread(image, cv2.IMREAD_COLOR)
            if bgr is None:
                raise FileNotFoundError(f"Image not found: {image}")
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            return rgb
        raise TypeError(f"Unsupported image input: {type(image)}")

    def _get_infer_settings(self, override: Dict[str, Any]) -> Dict[str, Any]:
        def pick(key: str, default: Any):
            return override.get(key, self._get(f"yolo.{key}", default))

        classes = pick("classes", None)
        if classes == []:
            classes = None

        return {
            "device": pick("device", "cuda:0"),
            "imgsz": int(pick("imgsz", 640)),
            "conf": float(pick("conf", 0.25)),
            "iou": float(pick("iou", 0.45)),
            "max_det": int(pick("max_det", 100)),
            "classes": classes,
            "agnostic_nms": bool(pick("agnostic_nms", False)),
            "half": bool(pick("half", True)),
            "verbose": bool(pick("verbose", False)),
        }

    def _get(self, key: str, default: Any):
        return self.config.get(key, default)

    def detections_to_multi_match(self, detections: List[Dict[str, Any]]) -> MultiYoloResult:
        matches = [self._detection_to_match(det) for det in detections]
        return MultiYoloResult(count=len(matches), matches=matches)

    def select_best_match(self, matches: List[YoloResult]) -> YoloResult:
        if not matches:
            return YoloResult(found=False)
        best = max(matches, key=lambda m: m.confidence)
        return best

    def _detection_to_match(self, det: Dict[str, Any]) -> YoloResult:
        bbox = det.get("bbox_global")
        if not bbox or len(bbox) != 4:
            return YoloResult(found=False)
        x, y, w, h = bbox
        rect = (int(x), int(y), int(w), int(h))
        center = (int(x + w / 2), int(y + h / 2))
        return YoloResult(
            found=True,
            top_left=(int(x), int(y)),
            center_point=center,
            rect=rect,
            confidence=float(det.get("score", 0.0)),
            label=det.get("label"),
            class_id=det.get("class_id"),
            debug_info={"score": float(det.get("score", 0.0))},
        )

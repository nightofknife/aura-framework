from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from packages.aura_core.api import service_info
from packages.aura_core.config.service import ConfigService
from packages.aura_core.context.plan import current_plan_name
from packages.aura_core.observability.logging.core_logger import logger


@dataclass(frozen=True)
class YoloModelReference:
    requested: str
    source: str
    cache_key: str
    family: Optional[str] = None
    variant: Optional[str] = None
    is_path: bool = False


@service_info(
    alias="yolo",
    public=True,
    description="Core Ultralytics YOLO service with model-family support for YOLO 8/10/11/26.",
)
class YoloService:
    _SUPPORTED_FAMILIES = ("yolo8", "yolo10", "yolo11", "yolo26")
    _FAMILY_PREFIXES = {
        "yolo8": "yolov8",
        "yolo10": "yolov10",
        "yolo11": "yolo11",
        "yolo26": "yolo26",
    }
    _FAMILY_ALIASES = {
        "yolo8": "yolo8",
        "yolov8": "yolo8",
        "v8": "yolo8",
        "yolo10": "yolo10",
        "yolov10": "yolo10",
        "v10": "yolo10",
        "yolo11": "yolo11",
        "yolov11": "yolo11",
        "v11": "yolo11",
        "yolo26": "yolo26",
        "yolov26": "yolo26",
        "v26": "yolo26",
    }
    _MODEL_TOKEN_RE = re.compile(r"^(?P<family>yolo(?:v)?(?:8|10|11|26)|v(?:8|10|11|26))(?P<variant>[nslmx])?$", re.I)
    _PATH_HINT_RE = re.compile(r"[\\/]|^\.+$")
    _MODEL_EXTENSIONS = {
        ".pt",
        ".onnx",
        ".engine",
        ".torchscript",
        ".mlpackage",
        ".savedmodel",
        ".pb",
        ".tflite",
    }

    def __init__(self, config: ConfigService):
        self._config = config
        self._lock = threading.RLock()
        self._models: Dict[str, Any] = {}
        self._model_refs: Dict[str, YoloModelReference] = {}
        self._class_names: Dict[str, Dict[int, str]] = {}
        self._active_model_key: Optional[str] = None

    def supported_generations(self) -> List[str]:
        return list(self._SUPPORTED_FAMILIES)

    def resolve_model_reference(self, model_name: str, *, variant: Optional[str] = None) -> YoloModelReference:
        raw = str(model_name or "").strip()
        if not raw:
            raise ValueError("model_name is required.")

        if self._looks_like_path(raw):
            resolved_path = self._resolve_explicit_path(raw)
            return YoloModelReference(
                requested=raw,
                source=str(resolved_path),
                cache_key=resolved_path.stem or resolved_path.name,
                family=self._infer_family_from_name(resolved_path.stem),
                variant=self._infer_variant_from_name(resolved_path.stem),
                is_path=True,
            )

        canonical_family = None
        resolved_variant = None
        token_match = self._MODEL_TOKEN_RE.match(raw)
        if token_match:
            canonical_family = self._normalize_family(token_match.group("family"))
            resolved_variant = (variant or token_match.group("variant") or self._default_variant()).lower()
            model_source = f"{self._FAMILY_PREFIXES[canonical_family]}{resolved_variant}.pt"
            return YoloModelReference(
                requested=raw,
                source=model_source,
                cache_key=Path(model_source).stem,
                family=canonical_family,
                variant=resolved_variant,
                is_path=False,
            )

        lowered = raw.lower()
        if lowered in self._FAMILY_ALIASES:
            canonical_family = self._normalize_family(lowered)
            resolved_variant = (variant or self._default_variant()).lower()
            model_source = f"{self._FAMILY_PREFIXES[canonical_family]}{resolved_variant}.pt"
            return YoloModelReference(
                requested=raw,
                source=model_source,
                cache_key=Path(model_source).stem,
                family=canonical_family,
                variant=resolved_variant,
                is_path=False,
            )

        return YoloModelReference(
            requested=raw,
            source=raw,
            cache_key=Path(raw).stem or raw.replace("/", "_").replace("\\", "_"),
            family=self._infer_family_from_name(raw),
            variant=self._infer_variant_from_name(raw),
            is_path=False,
        )

    def preload_model(
        self,
        model_name: str,
        *,
        alias: Optional[str] = None,
        variant: Optional[str] = None,
        force_reload: bool = False,
    ) -> Dict[str, Any]:
        model_ref = self.resolve_model_reference(model_name, variant=variant)
        cache_key = str(alias or model_ref.cache_key)

        with self._lock:
            if cache_key in self._models and not force_reload:
                return self.get_model_info(cache_key)

        model_cls = self._load_yolo_class()
        logger.info("Loading core YOLO model '%s' from '%s'", cache_key, model_ref.source)
        model = model_cls(model_ref.source)
        class_names = self._extract_class_names(model)

        with self._lock:
            if force_reload and cache_key in self._models:
                self._models.pop(cache_key, None)
                self._class_names.pop(cache_key, None)
                self._model_refs.pop(cache_key, None)
            self._models[cache_key] = model
            self._class_names[cache_key] = class_names
            self._model_refs[cache_key] = model_ref
            if self._active_model_key is None:
                self._active_model_key = cache_key

        info = self.get_model_info(cache_key)
        info["loaded"] = True
        return info

    def set_active_model(self, model_name: str, *, variant: Optional[str] = None) -> Dict[str, Any]:
        model_ref = self.resolve_model_reference(model_name, variant=variant)
        cache_key = model_ref.cache_key
        with self._lock:
            if cache_key not in self._models:
                self.preload_model(model_name, variant=variant)
            self._active_model_key = cache_key
            return self.get_model_info(cache_key) | {"active": True}

    def unload_model(self, model_name: str) -> Dict[str, Any]:
        model_ref = self.resolve_model_reference(model_name)
        cache_key = model_ref.cache_key
        with self._lock:
            removed = self._models.pop(cache_key, None)
            self._class_names.pop(cache_key, None)
            self._model_refs.pop(cache_key, None)
            if self._active_model_key == cache_key:
                self._active_model_key = None

        if removed is not None:
            self._release_model_resources(removed)
        return {"ok": True, "model": cache_key, "unloaded": removed is not None}

    def list_loaded_models(self) -> List[str]:
        with self._lock:
            return sorted(self._models)

    def list_loaded_model_infos(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self.get_model_info(key) for key in sorted(self._models)]

    def get_active_model(self) -> Optional[str]:
        with self._lock:
            return self._active_model_key

    def get_model_info(self, model_name: str) -> Dict[str, Any]:
        with self._lock:
            model_ref = self._model_refs.get(model_name)
            return {
                "ok": True,
                "model": model_name,
                "active": self._active_model_key == model_name,
                "family": model_ref.family if model_ref else None,
                "variant": model_ref.variant if model_ref else None,
                "source": model_ref.source if model_ref else None,
                "is_path": model_ref.is_path if model_ref else False,
                "class_count": len(self._class_names.get(model_name, {})),
            }

    def get_class_names(self, model_name: Optional[str] = None) -> Dict[int, str]:
        _, cache_key = self._get_loaded_model(model_name)
        with self._lock:
            return dict(self._class_names.get(cache_key, {}))

    def resolve_class_ids(self, labels: Sequence[str], model_name: Optional[str] = None) -> List[int]:
        if not labels:
            return []
        reverse_index = {label.lower(): class_id for class_id, label in self.get_class_names(model_name).items()}
        resolved: List[int] = []
        for label in labels:
            key = str(label).strip().lower()
            if key and key in reverse_index:
                resolved.append(int(reverse_index[key]))
        return resolved

    def detect(
        self,
        source: Any,
        *,
        model_name: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        model, cache_key = self._get_loaded_model(model_name)
        infer_settings = self._build_infer_settings(options or {})
        predictions = model.predict(source=source, **infer_settings)
        detections, image_size = self._parse_detections(predictions, cache_key)
        return {
            "ok": True,
            "model": cache_key,
            "detections": detections,
            "family": self._model_refs.get(cache_key).family if cache_key in self._model_refs else None,
            "image_size": image_size,
        }

    def detect_image(
        self,
        image: Any,
        *,
        model_name: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result = self.detect(image, model_name=model_name, options=options)
        for det in result.get("detections", []):
            bbox_xywh = det.get("bbox_xywh")
            if isinstance(bbox_xywh, list) and len(bbox_xywh) == 4:
                det["bbox_global"] = [int(round(value)) for value in bbox_xywh]
        return result

    def detect_on_screen(
        self,
        *,
        app: Any,
        roi: Optional[Tuple[int, int, int, int]] = None,
        model_name: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if app is None:
            raise ValueError("app service is required for detect_on_screen.")

        capture = app.capture(rect=roi)
        if not getattr(capture, "success", False) or getattr(capture, "image", None) is None:
            return {
                "ok": False,
                "error": getattr(capture, "error_message", None) or "capture failed",
                "detections": [],
            }

        result = self.detect(capture.image, model_name=model_name, options=options)
        offset_x, offset_y = self._resolve_capture_origin(app, capture)
        relative_rect = getattr(capture, "relative_rect", None) or (
            0,
            0,
            int(capture.image.shape[1]),
            int(capture.image.shape[0]),
        )
        offset_x += int(relative_rect[0])
        offset_y += int(relative_rect[1])

        for det in result.get("detections", []):
            bbox_xywh = det.get("bbox_xywh")
            if isinstance(bbox_xywh, list) and len(bbox_xywh) == 4:
                x, y, w, h = [float(value) for value in bbox_xywh]
                det["bbox_global"] = [
                    int(round(x + offset_x)),
                    int(round(y + offset_y)),
                    int(round(w)),
                    int(round(h)),
                ]

        return result

    def _get_loaded_model(self, model_name: Optional[str]) -> Tuple[Any, str]:
        with self._lock:
            if model_name:
                cache_key = self.resolve_model_reference(model_name).cache_key
            else:
                cache_key = self._active_model_key or self._get_default_model_cache_key()

            if cache_key not in self._models:
                default_variant = self._model_refs.get(cache_key).variant if cache_key in self._model_refs else None
                preload_name = model_name or self._get_default_model_name()
                self.preload_model(preload_name, variant=default_variant)

            return self._models[cache_key], cache_key

    def _get_default_model_name(self) -> str:
        configured = self._config.get("yolo.default_model", None)
        if configured:
            return str(configured)
        return "yolo11"

    def _get_default_model_cache_key(self) -> str:
        return self.resolve_model_reference(self._get_default_model_name()).cache_key

    def _build_infer_settings(self, overrides: Dict[str, Any]) -> Dict[str, Any]:
        def pick(key: str, default: Any) -> Any:
            return overrides.get(key, self._config.get(f"yolo.{key}", default))

        classes = pick("classes", None)
        if classes == []:
            classes = None

        return {
            "device": pick("device", None),
            "imgsz": int(pick("imgsz", 640)),
            "conf": float(pick("conf", 0.25)),
            "iou": float(pick("iou", 0.45)),
            "max_det": int(pick("max_det", 100)),
            "classes": classes,
            "agnostic_nms": bool(pick("agnostic_nms", False)),
            "half": bool(pick("half", False)),
            "verbose": bool(pick("verbose", False)),
        }

    def _parse_detections(self, predictions: Any, cache_key: str) -> Tuple[List[Dict[str, Any]], Optional[List[int]]]:
        if not predictions:
            return [], None

        class_names = self._class_names.get(cache_key, {})
        detections: List[Dict[str, Any]] = []
        image_size: Optional[List[int]] = None

        for image_index, prediction in enumerate(predictions):
            if image_size is None:
                prediction_size = self._extract_prediction_size(prediction)
                if prediction_size is not None:
                    image_size = prediction_size
            boxes = getattr(prediction, "boxes", None)
            if boxes is None:
                continue

            xyxy_values = self._to_native_sequence(getattr(boxes, "xyxy", None))
            conf_values = self._to_native_sequence(getattr(boxes, "conf", None))
            cls_values = self._to_native_sequence(getattr(boxes, "cls", None))
            if not xyxy_values:
                continue

            for row_index, xyxy in enumerate(xyxy_values):
                x1, y1, x2, y2 = [float(value) for value in xyxy]
                class_id = int(cls_values[row_index]) if row_index < len(cls_values) else -1
                score = float(conf_values[row_index]) if row_index < len(conf_values) else 0.0
                detections.append(
                    {
                        "image_index": image_index,
                        "class_id": class_id,
                        "label": class_names.get(class_id, str(class_id)),
                        "score": score,
                        "bbox_xyxy": [x1, y1, x2, y2],
                        "bbox_xywh": [x1, y1, x2 - x1, y2 - y1],
                    }
                )
        return detections, image_size

    def _load_yolo_class(self):
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError(
                "ultralytics is required for core YOLO service. Install it with `pip install ultralytics`."
            ) from exc
        return YOLO

    @staticmethod
    def _extract_class_names(model: Any) -> Dict[int, str]:
        names = getattr(model, "names", None)
        if names is None and hasattr(model, "model"):
            names = getattr(model.model, "names", None)

        if isinstance(names, list):
            return {index: str(value) for index, value in enumerate(names)}
        if isinstance(names, dict):
            return {int(key): str(value) for key, value in names.items()}
        return {}

    @classmethod
    def _normalize_family(cls, family_token: str) -> str:
        normalized = str(family_token).lower()
        if normalized not in cls._FAMILY_ALIASES:
            raise ValueError(f"Unsupported YOLO family token: {family_token}")
        return cls._FAMILY_ALIASES[normalized]

    @staticmethod
    def _infer_variant_from_name(token: str) -> Optional[str]:
        match = re.search(r"([nslmx])(?:\.[A-Za-z0-9]+)?$", str(token).lower())
        return match.group(1) if match else None

    def _infer_family_from_name(self, token: str) -> Optional[str]:
        lowered = str(token).lower()
        for family, prefix in self._FAMILY_PREFIXES.items():
            if lowered.startswith(prefix):
                return family
        return None

    def _default_variant(self) -> str:
        configured = str(self._config.get("yolo.default_variant", "n") or "n").strip().lower()
        return configured if configured in {"n", "s", "m", "l", "x"} else "n"

    def _looks_like_path(self, token: str) -> bool:
        raw = str(token).strip()
        suffix = Path(raw).suffix.lower()
        return bool(self._PATH_HINT_RE.search(raw)) or suffix in self._MODEL_EXTENSIONS

    def _resolve_explicit_path(self, raw: str) -> Path:
        candidate = Path(raw)
        if candidate.is_absolute():
            return candidate.resolve()

        base_path = self._repo_root()
        plan_name = current_plan_name.get()
        if plan_name:
            plan_candidate = (base_path / "plans" / plan_name / candidate).resolve()
            if plan_candidate.exists():
                return plan_candidate

        direct_candidate = (base_path / candidate).resolve()
        if direct_candidate.exists():
            return direct_candidate

        models_root = (base_path / str(self._config.get("yolo.models_root", "models/yolo"))).resolve()
        return (models_root / candidate.name).resolve()

    @staticmethod
    def _to_native_sequence(value: Any) -> List[Any]:
        if value is None:
            return []
        if hasattr(value, "cpu"):
            value = value.cpu()
        if hasattr(value, "numpy"):
            value = value.numpy()
        if hasattr(value, "tolist"):
            value = value.tolist()
        if isinstance(value, tuple):
            return list(value)
        return list(value)

    @staticmethod
    def _release_model_resources(model: Any) -> None:
        try:
            import torch

            del model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[3]

    @staticmethod
    def _extract_prediction_size(prediction: Any) -> Optional[List[int]]:
        orig_shape = getattr(prediction, "orig_shape", None)
        if isinstance(orig_shape, (list, tuple)) and len(orig_shape) >= 2:
            height = int(orig_shape[0])
            width = int(orig_shape[1])
            return [width, height]
        return None

    @staticmethod
    def _resolve_capture_origin(app: Any, capture: Any) -> Tuple[int, int]:
        screen = getattr(app, "screen", None)
        if screen is not None and hasattr(screen, "get_client_rect"):
            client_rect = screen.get_client_rect()
            if client_rect:
                return int(client_rect[0]), int(client_rect[1])
        window_rect = getattr(capture, "window_rect", None)
        if isinstance(window_rect, (list, tuple)) and len(window_rect) >= 2:
            return int(window_rect[0]), int(window_rect[1])
        return 0, 0

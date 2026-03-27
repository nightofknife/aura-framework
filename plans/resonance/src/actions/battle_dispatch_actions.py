"""Actions for auto battle dispatch/grouping and OCR-driven selectors."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from packages.aura_core.api import action_info, requires_services

_PLAN_ROOT = Path(__file__).resolve().parents[2]
_BATTLE_CATALOG_FILE = _PLAN_ROOT / "data" / "meta" / "battle_catalog.json"

_ACTION_SUMMARY_GROUP_TEXT: Dict[str, str] = {
    "blade_encirclement": "\u5229\u5203\u56f4\u527f",
    "global_supply": "\u5168\u5883\u7279\u4f9b",
    "smuggler_crackdown": "\u79c1\u8d29\u8ffd\u7f34",
}

_ACTION_SUMMARY_STAGE_TEXT: Dict[str, str] = {
    "special_order": "\u7279\u6b8a\u8ba2\u5355",
    "blade_action": "\u5229\u5203\u884c\u52a8",
    "read_by_lamp": "\u6311\u706f\u770b\u5251",
    "weapon_material_analysis": "\u6b66\u5668\u6750\u8d28\u5206\u6790",
    "knight_novel": "\u9a91\u58eb\u5c0f\u8bf4",
    "i_think_i_am": "\u6211\u601d\u6211\u5728",
    "what_i_know": "\u6240\u77e5\u6240\u95fb",
    "big_one": "\u5927\u7684\uff01",
    "total_encirclement": "\u603b\u4f53\u56f4\u527f",
    "elegant": "\u7279\u4f9b\u00b7\u96c5\u81f4",
    "standard": "\u7279\u4f9b\u00b7\u5236\u5f0f",
    "savior": "\u7279\u4f9b\u00b7\u6551\u4e16",
    "cutting_edge": "\u7279\u4f9b\u00b7\u5c16\u7aef",
    "chaos": "\u7279\u4f9b\u00b7\u6df7\u6c8c",
    "magic": "\u7279\u4f9b\u00b7\u9b54\u529b",
    "blind_box": "\u7279\u4f9b\u00b7\u76f2\u76d2",
}

_ACTION_SUMMARY_STAGE_ORDER: Dict[str, List[str]] = {
    "blade_encirclement": [
        "special_order",
        "blade_action",
        "read_by_lamp",
        "weapon_material_analysis",
        "knight_novel",
        "i_think_i_am",
        "what_i_know",
        "big_one",
        "total_encirclement",
    ],
    "global_supply": [
        "elegant",
        "standard",
        "savior",
        "cutting_edge",
        "chaos",
        "magic",
    ],
    "smuggler_crackdown": [
        "blind_box",
    ],
}

_STRUCTURAL_STAGE_TEXT: Dict[str, str] = {
    "disordered_roots": "\u4e71\u5e8f\u6839\u987b",
    "hetero_branches": "\u5f02\u6784\u5384\u679d",
    "echo_buoy": "\u6df7\u54cd\u6d6e\u6807",
    "birch_buoy": "\u6866\u6811\u6d6e\u6807",
}

_STRUCTURAL_SAMPLE_POINTS: Dict[str, Tuple[int, int]] = {
    "disordered_roots": (300, 375),
    "hetero_branches": (300, 440),
    "echo_buoy": (300, 500),
    "birch_buoy": (300, 560),
}


class BattleDispatchError(RuntimeError):
    """Structured error for battle dispatch and selectors."""

    def __init__(self, code: str, message: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.detail = detail or {}

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def _raise_error(code: str, message: str, detail: Optional[Dict[str, Any]] = None) -> None:
    raise BattleDispatchError(code=code, message=message, detail=detail)


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        _raise_error("file_not_found", f"Required file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _raise_error("json_invalid", f"Invalid JSON file: {path}", {"cause": str(exc)})
    if not isinstance(payload, dict):
        _raise_error("json_invalid", f"JSON root must be object: {path}")
    return payload


def _load_catalog() -> Dict[str, Any]:
    payload = _load_json(_BATTLE_CATALOG_FILE)
    routes = payload.get("routes")
    if not isinstance(routes, list):
        _raise_error("catalog_invalid", "battle_catalog.routes must be a list")
    route_index: Dict[str, Dict[str, Any]] = {}
    for item in routes:
        if not isinstance(item, dict):
            continue
        route_id = str(item.get("route_id") or "").strip()
        if not route_id:
            continue
        route_index[route_id] = item
    payload["route_index"] = route_index
    return payload


def _normalize_text(text: str) -> str:
    return re.sub(r"[\s\u3000\-_:锛氾紝,銆?!锛侊紵?()锛堬級\[\]{}<>]+", "", str(text or "")).lower()


def _match_mode_hit(actual: str, target: str, match_mode: str) -> bool:
    if match_mode == "exact":
        return actual == target
    if match_mode == "contains":
        return target in actual
    return target in actual


def _coerce_region(value: Any, fallback: List[int]) -> Tuple[int, int, int, int]:
    base = fallback if isinstance(fallback, list) and len(fallback) == 4 else [0, 0, 1280, 720]
    if not isinstance(value, list) or len(value) != 4:
        value = base
    try:
        x = int(value[0])
        y = int(value[1])
        w = int(value[2])
        h = int(value[3])
    except (TypeError, ValueError):
        x, y, w, h = base
    return (x, y, max(w, 1), max(h, 1))


def _coerce_drag(value: Any, fallback: List[int]) -> Tuple[int, int, int, int]:
    base = fallback if isinstance(fallback, list) and len(fallback) == 4 else [640, 500, 640, 220]
    if not isinstance(value, list) or len(value) != 4:
        value = base
    try:
        sx = int(value[0])
        sy = int(value[1])
        ex = int(value[2])
        ey = int(value[3])
    except (TypeError, ValueError):
        sx, sy, ex, ey = base
    return (sx, sy, ex, ey)


def _recognize_text_items(
    app: Any,
    ocr: Any,
    region: Tuple[int, int, int, int],
) -> List[Dict[str, Any]]:
    capture = app.capture(rect=region)
    if not capture.success:
        _raise_error("capture_failed", "Failed to capture screen region.", {"region": list(region)})

    result = ocr.recognize_all(capture.image)
    items: List[Dict[str, Any]] = []
    for row in result.results:
        if not row.center_point:
            continue
        cx = int(row.center_point[0]) + region[0]
        cy = int(row.center_point[1]) + region[1]
        txt = str(row.text or "")
        items.append(
            {
                "text": txt,
                "normalized": _normalize_text(txt),
                "center": (cx, cy),
                "confidence": float(row.confidence),
            }
        )
    return items


def _city_from_ocr(items: List[Dict[str, Any]], city_order: List[str], match_mode: str) -> List[Dict[str, Any]]:
    normalized_order = [(_normalize_text(name), name, idx) for idx, name in enumerate(city_order)]
    hits: List[Dict[str, Any]] = []
    for row in items:
        normalized = row["normalized"]
        for city_norm, city_name, city_idx in normalized_order:
            if _match_mode_hit(normalized, city_norm, match_mode):
                hits.append(
                    {
                        "city_name": city_name,
                        "city_index": city_idx,
                        "center": row["center"],
                        "text": row["text"],
                        "confidence": row["confidence"],
                    }
                )
                break
    return hits


def _direction_from_city_hits(target_idx: int, hit_indexes: List[int]) -> str:
    if not hit_indexes:
        return "larger"
    min_idx = min(hit_indexes)
    max_idx = max(hit_indexes)
    if target_idx > max_idx:
        return "larger"
    if target_idx < min_idx:
        return "smaller"
    mid = (min_idx + max_idx) / 2.0
    return "larger" if target_idx >= mid else "smaller"


def _extract_level(text: str) -> Optional[int]:
    m = re.search(r"(\d+)", str(text or ""))
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _levels_from_ocr(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    parsed: List[Dict[str, Any]] = []
    seen = set()
    for row in items:
        level = _extract_level(row["text"])
        if level is None:
            continue
        key = (level, row["center"])
        if key in seen:
            continue
        seen.add(key)
        parsed.append(
            {
                "level": level,
                "center": row["center"],
                "text": row["text"],
                "confidence": row["confidence"],
            }
        )
    return parsed


def _ordered_hits(items: List[Dict[str, Any]], order: List[str], match_mode: str) -> List[Dict[str, Any]]:
    normalized_order = [(_normalize_text(name), name, idx) for idx, name in enumerate(order)]
    hits: List[Dict[str, Any]] = []
    for row in items:
        normalized = row["normalized"]
        for item_norm, item_name, item_idx in normalized_order:
            if _match_mode_hit(normalized, item_norm, match_mode):
                hits.append(
                    {
                        "label_name": item_name,
                        "label_index": item_idx,
                        "center": row["center"],
                        "text": row["text"],
                        "confidence": row["confidence"],
                    }
                )
                break
    return hits


@action_info(
    name="resonance.group_battle_jobs",
    public=True,
    read_only=True,
    description="Group auto battle jobs by top-level category and preserve first-seen category order.",
)
def resonance_group_battle_jobs(jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(jobs, list):
        raise ValueError("jobs must be a list.")

    ct_jobs: List[Dict[str, Any]] = []
    gp_jobs: List[Dict[str, Any]] = []
    unknown_jobs: List[Dict[str, Any]] = []
    category_order: List[str] = []

    for raw in jobs:
        if not isinstance(raw, dict):
            unknown_jobs.append({"raw": raw, "reason": "job must be an object"})
            continue

        route_id = str(raw.get("route_id") or "").strip()
        if route_id.startswith("ct."):
            ct_jobs.append(raw)
            if "ct" not in category_order:
                category_order.append("ct")
            continue
        if route_id.startswith("gp."):
            gp_jobs.append(raw)
            if "gp" not in category_order:
                category_order.append("gp")
            continue
        unknown_jobs.append({"job": raw, "reason": "route_id must start with 'ct.' or 'gp.'"})

    return {
        "ct_jobs": ct_jobs,
        "gp_jobs": gp_jobs,
        "unknown_jobs": unknown_jobs,
        "category_order": category_order,
        "has_ct": len(ct_jobs) > 0,
        "has_gp": len(gp_jobs) > 0,
    }


@action_info(
    name="resonance.group_ct_jobs",
    public=True,
    read_only=True,
    description="Group 鍗忓悓缁堢 jobs into 閾佹灞€ and 鍖哄煙浣滄垬涓績 buckets with first-seen order.",
)
def resonance_group_ct_jobs(jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(jobs, list):
        raise ValueError("jobs must be a list.")

    tie_an_jobs: List[Dict[str, Any]] = []
    regional_ops_jobs: List[Dict[str, Any]] = []
    unknown_jobs: List[Dict[str, Any]] = []
    category_order: List[str] = []

    for raw in jobs:
        if not isinstance(raw, dict):
            unknown_jobs.append({"raw": raw, "reason": "job must be an object"})
            continue

        route_id = str(raw.get("route_id") or "").strip()
        if route_id.startswith("ct.tie_an."):
            tie_an_jobs.append(raw)
            if "tie_an" not in category_order:
                category_order.append("tie_an")
            continue
        if route_id.startswith("ct.regional_ops_center."):
            regional_ops_jobs.append(raw)
            if "regional_ops_center" not in category_order:
                category_order.append("regional_ops_center")
            continue
        unknown_jobs.append(
            {
                "job": raw,
                "reason": "CT route_id must start with 'ct.tie_an.' or 'ct.regional_ops_center.'",
            }
        )

    return {
        "tie_an_jobs": tie_an_jobs,
        "regional_ops_jobs": regional_ops_jobs,
        "unknown_jobs": unknown_jobs,
        "category_order": category_order,
        "has_tie_an": len(tie_an_jobs) > 0,
        "has_regional_ops_center": len(regional_ops_jobs) > 0,
    }


@action_info(
    name="resonance.group_gp_jobs",
    public=True,
    read_only=True,
    description="Group GP jobs into action_summary and structural_exploration buckets with first-seen order.",
)
def resonance_group_gp_jobs(jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(jobs, list):
        raise ValueError("jobs must be a list.")

    action_summary_jobs: List[Dict[str, Any]] = []
    structural_jobs: List[Dict[str, Any]] = []
    unknown_jobs: List[Dict[str, Any]] = []
    category_order: List[str] = []

    for raw in jobs:
        if not isinstance(raw, dict):
            unknown_jobs.append({"raw": raw, "reason": "job must be an object"})
            continue

        route_id = str(raw.get("route_id") or "").strip()
        if route_id.startswith("gp.action_summary."):
            action_summary_jobs.append(raw)
            if "action_summary" not in category_order:
                category_order.append("action_summary")
            continue
        if route_id.startswith("gp.structural_exploration."):
            structural_jobs.append(raw)
            if "structural_exploration" not in category_order:
                category_order.append("structural_exploration")
            continue
        unknown_jobs.append(
            {
                "job": raw,
                "reason": "GP route_id must start with 'gp.action_summary.' or 'gp.structural_exploration.'",
            }
        )

    return {
        "action_summary_jobs": action_summary_jobs,
        "structural_exploration_jobs": structural_jobs,
        "unknown_jobs": unknown_jobs,
        "category_order": category_order,
        "has_action_summary": len(action_summary_jobs) > 0,
        "has_structural_exploration": len(structural_jobs) > 0,
    }


@action_info(
    name="resonance.group_consecutive_jobs_by_route",
    public=True,
    read_only=True,
    description="Group adjacent jobs with the same route_id while preserving order.",
)
def resonance_group_consecutive_jobs_by_route(jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(jobs, list):
        raise ValueError("jobs must be a list.")

    groups: List[Dict[str, Any]] = []
    current_group: Optional[Dict[str, Any]] = None

    for raw in jobs:
        if not isinstance(raw, dict):
            continue
        route_id = str(raw.get("route_id") or "").strip()
        if not route_id:
            continue

        if current_group is None or current_group["route_id"] != route_id:
            current_group = {
                "route_id": route_id,
                "jobs": [raw],
                "job_count": 1,
            }
            for key in (
                "main_category",
                "ct_subcategory",
                "gp_subcategory",
                "gp_group_key",
                "gp_group_name",
                "gp_stage_key",
                "gp_stage_name",
                "structural_sample_point",
            ):
                if key in raw:
                    current_group[key] = raw.get(key)
            groups.append(current_group)
            continue

        current_group["jobs"].append(raw)
        current_group["job_count"] = int(current_group["job_count"]) + 1

    return {
        "group_count": len(groups),
        "groups": groups,
    }


@action_info(
    name="resonance.annotate_job_sequence",
    public=True,
    read_only=True,
    description="Attach sequence metadata to each job item while preserving original fields.",
)
def resonance_annotate_job_sequence(jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(jobs, list):
        raise ValueError("jobs must be a list.")

    total = len(jobs)
    annotated: List[Dict[str, Any]] = []
    for idx, raw in enumerate(jobs, start=1):
        item = dict(raw) if isinstance(raw, dict) else {"raw": raw}
        item["seq"] = idx
        item["total"] = total
        item["is_first"] = idx == 1
        item["is_last"] = idx == total
        annotated.append(item)
    return {
        "job_count": total,
        "jobs": annotated,
    }


@action_info(
    name="resonance.validate_battle_jobs",
    public=True,
    read_only=True,
    description="Validate jobs against battle catalog and normalize required fields.",
)
def resonance_validate_battle_jobs(jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(jobs, list):
        _raise_error("invalid_jobs", "jobs must be a list")

    catalog = _load_catalog()
    route_index = catalog.get("route_index") or {}
    normalized_jobs: List[Dict[str, Any]] = []

    for idx, raw in enumerate(jobs):
        path = f"jobs[{idx}]"
        if not isinstance(raw, dict):
            _raise_error("invalid_job_item", f"{path} must be an object")

        unknown_fields = set(raw.keys()) - {"route_id", "difficulty", "stage", "threat_level"}
        if unknown_fields:
            _raise_error(
                "invalid_job_field",
                f"{path} has unexpected fields: {sorted(unknown_fields)}",
                {"job": raw},
            )

        route_id = str(raw.get("route_id") or "").strip()
        if not route_id:
            _raise_error("missing_route_id", f"{path}.route_id is required")
        route_meta = route_index.get(route_id)
        if not isinstance(route_meta, dict):
            _raise_error("unknown_route_id", f"{path}.route_id '{route_id}' is not in battle catalog")

        difficulty_raw = raw.get("difficulty")
        difficulty: Optional[int]
        if difficulty_raw is None:
            difficulty = None
        else:
            try:
                difficulty = int(difficulty_raw)
            except Exception as exc:  # noqa: BLE001
                _raise_error("invalid_difficulty", f"{path}.difficulty must be an integer", {"cause": str(exc)})
            if difficulty < 1 or difficulty > 6:
                _raise_error("invalid_difficulty", f"{path}.difficulty must be in [1,6]")

        stage_raw = raw.get("stage")
        stage: Optional[int]
        if stage_raw is None:
            stage = None
        else:
            try:
                stage = int(stage_raw)
            except Exception as exc:  # noqa: BLE001
                _raise_error("invalid_stage", f"{path}.stage must be an integer", {"cause": str(exc)})
            if stage < 1 or stage > 3:
                _raise_error("invalid_stage", f"{path}.stage must be in [1,3]")

        threat_raw = raw.get("threat_level")
        threat_level: Optional[int]
        if threat_raw is None:
            threat_level = None
        else:
            try:
                threat_level = int(threat_raw)
            except Exception as exc:  # noqa: BLE001
                _raise_error("invalid_threat_level", f"{path}.threat_level must be an integer", {"cause": str(exc)})
            if threat_level < 1:
                _raise_error("invalid_threat_level", f"{path}.threat_level must be >= 1")

        main_category = str(route_meta.get("main_category") or "")
        ct_subcategory = str(route_meta.get("ct_subcategory") or "")
        mission_type = route_meta.get("mission_type")
        gp_subcategory: Optional[str] = None
        gp_group_key: Optional[str] = None
        gp_group_name: Optional[str] = None
        gp_stage_key: Optional[str] = None
        gp_stage_name: Optional[str] = None
        structural_sample_point: Optional[List[int]] = None

        if main_category == "ct" and ct_subcategory == "tie_an":
            if mission_type == "expel":
                if stage is None or difficulty is None:
                    _raise_error(
                        "invalid_tie_an_expel",
                        f"{path} requires both stage and difficulty for tie_an expel route",
                    )
                if threat_level is not None:
                    _raise_error("invalid_job_field", f"{path}.threat_level is not allowed for tie_an route")
            elif mission_type == "bounty":
                if stage is not None:
                    _raise_error("invalid_job_field", f"{path}.stage is not allowed for tie_an bounty route")
                if difficulty is not None:
                    _raise_error("invalid_job_field", f"{path}.difficulty is not allowed for tie_an bounty route")
                if threat_level is not None:
                    _raise_error("invalid_job_field", f"{path}.threat_level is not allowed for tie_an bounty route")
            else:
                _raise_error("invalid_catalog", f"route '{route_id}' has invalid mission_type in catalog")

        if main_category == "ct" and ct_subcategory == "regional_ops_center":
            if difficulty is None or threat_level is None:
                _raise_error(
                    "invalid_regional_ops",
                    f"{path} requires both difficulty and threat_level for regional_ops route",
                )
            if stage is not None:
                _raise_error("invalid_job_field", f"{path}.stage is not allowed for regional_ops route")

        if main_category == "gp":
            parts = route_id.split(".")
            if len(parts) < 3:
                _raise_error("invalid_catalog", f"route '{route_id}' has invalid gp route format")
            gp_subcategory = parts[1]

            if gp_subcategory == "action_summary":
                if len(parts) != 4:
                    _raise_error("invalid_catalog", f"route '{route_id}' has invalid action_summary route format")
                gp_group_key = parts[2]
                gp_stage_key = parts[3]
                gp_group_name = _ACTION_SUMMARY_GROUP_TEXT.get(gp_group_key)
                gp_stage_name = _ACTION_SUMMARY_STAGE_TEXT.get(gp_stage_key)
                if not gp_group_name or not gp_stage_name:
                    _raise_error("invalid_catalog", f"route '{route_id}' is not mapped in action_summary catalog")
                if difficulty is None:
                    _raise_error(
                        "invalid_gp_action_summary",
                        f"{path} requires difficulty for gp action_summary route",
                    )
                if stage is not None or threat_level is not None:
                    _raise_error(
                        "invalid_job_field",
                        f"{path}.stage/threat_level are not allowed for gp action_summary routes",
                    )
            elif gp_subcategory == "structural_exploration":
                if len(parts) != 3:
                    _raise_error(
                        "invalid_catalog",
                        f"route '{route_id}' has invalid structural_exploration route format",
                    )
                gp_stage_key = parts[2]
                gp_stage_name = _STRUCTURAL_STAGE_TEXT.get(gp_stage_key)
                sample_point = _STRUCTURAL_SAMPLE_POINTS.get(gp_stage_key)
                if not gp_stage_name or not sample_point:
                    _raise_error(
                        "invalid_catalog",
                        f"route '{route_id}' is not mapped in structural_exploration catalog",
                    )
                structural_sample_point = [int(sample_point[0]), int(sample_point[1])]
                if difficulty is not None or stage is not None or threat_level is not None:
                    _raise_error(
                        "invalid_job_field",
                        f"{path}.difficulty/stage/threat_level are not allowed for gp structural_exploration routes",
                    )
            else:
                _raise_error("invalid_catalog", f"route '{route_id}' has invalid gp subcategory")

        normalized = {
            "route_id": route_id,
            "difficulty": difficulty,
            "stage": stage,
            "threat_level": threat_level,
            "main_category": main_category,
            "ct_subcategory": ct_subcategory,
            "gp_subcategory": gp_subcategory,
            "gp_group_key": gp_group_key,
            "gp_group_name": gp_group_name,
            "gp_stage_key": gp_stage_key,
            "gp_stage_name": gp_stage_name,
            "structural_sample_point": structural_sample_point,
            "city_name": route_meta.get("city_name"),
            "mission_type": mission_type,
        }
        normalized_jobs.append(normalized)

    return {
        "ok": True,
        "job_count": len(normalized_jobs),
        "normalized_jobs": normalized_jobs,
    }


@action_info(
    name="resonance.resolve_difficulty_text",
    public=True,
    read_only=True,
    description="Resolve difficulty text from numeric difficulty level.",
)
def resonance_resolve_difficulty_text(difficulty: int) -> Dict[str, Any]:
    level = int(difficulty)
    catalog = _load_catalog()
    mapping = catalog.get("difficulty_text_map") or {}
    text = str(mapping.get(str(level)) or "").strip()
    if not text:
        _raise_error("invalid_difficulty", f"difficulty '{level}' has no mapped text")
    return {"difficulty": level, "difficulty_text": text}


@action_info(
    name="resonance.select_ordered_city",
    public=True,
    read_only=False,
    description="Select target city from ordered city list by OCR + directional drag.",
)
@requires_services(
    app="plans/aura_base/app",
    ocr="plans/aura_base/ocr",
)
def resonance_select_ordered_city(
    target_city_name: str,
    city_order: List[str],
    region: Optional[List[int]] = None,
    drag_up: Optional[List[int]] = None,
    drag_down: Optional[List[int]] = None,
    max_attempts: int = 15,
    drag_duration_sec: float = 0.5,
    after_drag_sec: float = 0.5,
    match_mode: str = "contains",
    app: Any = None,
    ocr: Any = None,
) -> Dict[str, Any]:
    if app is None or ocr is None:
        _raise_error("missing_service", "app/ocr service is required")

    target_name = str(target_city_name or "").strip()
    if not target_name:
        _raise_error("invalid_city", "target_city_name is required")
    if not isinstance(city_order, list) or not city_order:
        _raise_error("invalid_city_order", "city_order must be a non-empty list")

    region_tuple = _coerce_region(region, [0, 0, 1280, 720])
    drag_up_tuple = _coerce_drag(drag_up, [900, 560, 900, 260])
    drag_down_tuple = _coerce_drag(drag_down, [900, 260, 900, 560])
    attempts = max(int(max_attempts), 1)
    after_drag = float(after_drag_sec)
    drag_duration = float(drag_duration_sec)

    normalized_order = [_normalize_text(name) for name in city_order]
    target_norm = _normalize_text(target_name)
    if target_norm not in normalized_order:
        _raise_error(
            "unknown_target_city",
            f"target city '{target_name}' not in city_order",
            {"city_order": city_order},
        )
    target_idx = normalized_order.index(target_norm)

    last_direction = "larger"
    for attempt in range(1, attempts + 1):
        items = _recognize_text_items(app=app, ocr=ocr, region=region_tuple)
        city_hits = _city_from_ocr(items=items, city_order=city_order, match_mode=match_mode)

        matched_target = [row for row in city_hits if _normalize_text(row["city_name"]) == target_norm]
        if matched_target:
            chosen = max(matched_target, key=lambda r: float(r["confidence"]))
            x, y = chosen["center"]
            app.click(x=x, y=y)
            return {
                "found": True,
                "city_name": chosen["city_name"],
                "attempt": attempt,
                "click_x": x,
                "click_y": y,
            }

        hit_indexes = [int(row["city_index"]) for row in city_hits]
        direction = _direction_from_city_hits(target_idx=target_idx, hit_indexes=hit_indexes)
        last_direction = direction

        sx, sy, ex, ey = drag_up_tuple if direction == "larger" else drag_down_tuple
        app.drag(start_x=sx, start_y=sy, end_x=ex, end_y=ey, duration=drag_duration)
        time.sleep(max(after_drag, 0.0))

    _raise_error(
        "city_select_failed",
        f"Failed to locate city '{target_name}' within {attempts} attempts",
        {"last_direction": last_direction, "region": list(region_tuple)},
    )


@action_info(
    name="resonance.select_threat_level_numeric",
    public=True,
    read_only=False,
    description="Select threat level by OCR numeric scan and directional horizontal drag.",
)
@requires_services(
    app="plans/aura_base/app",
    ocr="plans/aura_base/ocr",
)
def resonance_select_threat_level_numeric(
    threat_level: int,
    region: Optional[List[int]] = None,
    drag_increase: Optional[List[int]] = None,
    drag_decrease: Optional[List[int]] = None,
    max_attempts: int = 20,
    drag_duration_sec: float = 0.5,
    after_drag_sec: float = 0.5,
    app: Any = None,
    ocr: Any = None,
) -> Dict[str, Any]:
    if app is None or ocr is None:
        _raise_error("missing_service", "app/ocr service is required")

    try:
        target = int(threat_level)
    except Exception as exc:  # noqa: BLE001
        _raise_error("invalid_threat_level", "threat_level must be an integer", {"cause": str(exc)})
    if target < 1:
        _raise_error("invalid_threat_level", "threat_level must be >= 1")

    region_tuple = _coerce_region(region, [0, 0, 1280, 720])
    drag_inc_tuple = _coerce_drag(drag_increase, [980, 420, 420, 420])
    drag_dec_tuple = _coerce_drag(drag_decrease, [420, 420, 980, 420])
    attempts = max(int(max_attempts), 1)
    after_drag = float(after_drag_sec)
    drag_duration = float(drag_duration_sec)

    last_direction = "increase"
    for attempt in range(1, attempts + 1):
        items = _recognize_text_items(app=app, ocr=ocr, region=region_tuple)
        levels = _levels_from_ocr(items)
        exact = [row for row in levels if int(row["level"]) == target]
        if exact:
            chosen = max(exact, key=lambda r: float(r["confidence"]))
            x, y = chosen["center"]
            app.click(x=x, y=y)
            return {
                "found": True,
                "threat_level": target,
                "attempt": attempt,
                "click_x": x,
                "click_y": y,
            }

        if levels:
            min_level = min(int(row["level"]) for row in levels)
            max_level = max(int(row["level"]) for row in levels)
            if target > max_level:
                direction = "increase"
            elif target < min_level:
                direction = "decrease"
            else:
                avg = (min_level + max_level) / 2.0
                direction = "increase" if target >= avg else "decrease"
        else:
            direction = "decrease" if last_direction == "increase" else "increase"

        last_direction = direction
        sx, sy, ex, ey = drag_inc_tuple if direction == "increase" else drag_dec_tuple
        app.drag(start_x=sx, start_y=sy, end_x=ex, end_y=ey, duration=drag_duration)
        time.sleep(max(after_drag, 0.0))

    _raise_error(
        "threat_level_select_failed",
        f"Failed to locate threat level '{target}' within {attempts} attempts",
        {"last_direction": last_direction, "region": list(region_tuple)},
    )


@action_info(
    name="resonance.select_action_summary_stage",
    public=True,
    read_only=False,
    description="Select one action_summary stage by OCR + horizontal directional drag, then click with offset.",
)
@requires_services(
    app="plans/aura_base/app",
    ocr="plans/aura_base/ocr",
)
def resonance_select_action_summary_stage(
    route_id: str,
    region: Optional[List[int]] = None,
    drag_forward: Optional[List[int]] = None,
    drag_backward: Optional[List[int]] = None,
    max_attempts: int = 12,
    drag_duration_sec: float = 0.5,
    after_drag_sec: float = 0.5,
    click_offset_x: int = 0,
    click_offset_y: int = 180,
    match_mode: str = "contains",
    app: Any = None,
    ocr: Any = None,
) -> Dict[str, Any]:
    if app is None or ocr is None:
        _raise_error("missing_service", "app/ocr service is required")

    parts = str(route_id or "").strip().split(".")
    if len(parts) != 4 or parts[0] != "gp" or parts[1] != "action_summary":
        _raise_error("invalid_route_id", f"route '{route_id}' is not a gp action_summary route")

    group_key = parts[2]
    stage_key = parts[3]
    stage_order = _ACTION_SUMMARY_STAGE_ORDER.get(group_key)
    stage_name = _ACTION_SUMMARY_STAGE_TEXT.get(stage_key)
    if not stage_order or not stage_name:
        _raise_error("invalid_route_id", f"route '{route_id}' is not mapped in action_summary stage selector")

    order_names = [_ACTION_SUMMARY_STAGE_TEXT[key] for key in stage_order]
    region_tuple = _coerce_region(region, [0, 0, 1280, 720])
    drag_forward_tuple = _coerce_drag(drag_forward, [700, 400, 1100, 400])
    drag_backward_tuple = _coerce_drag(drag_backward, [1100, 400, 700, 400])
    attempts = max(int(max_attempts), 1)
    after_drag = float(after_drag_sec)
    drag_duration = float(drag_duration_sec)

    target_idx = stage_order.index(stage_key)
    target_norm = _normalize_text(stage_name)
    last_direction = "forward"

    for attempt in range(1, attempts + 1):
        items = _recognize_text_items(app=app, ocr=ocr, region=region_tuple)
        hits = _ordered_hits(items=items, order=order_names, match_mode=match_mode)

        matched_target = [row for row in hits if _normalize_text(row["label_name"]) == target_norm]
        if matched_target:
            chosen = max(matched_target, key=lambda r: float(r["confidence"]))
            x = int(chosen["center"][0]) + int(click_offset_x)
            y = int(chosen["center"][1]) + int(click_offset_y)
            app.click(x=x, y=y)
            return {
                "found": True,
                "stage_name": chosen["label_name"],
                "attempt": attempt,
                "click_x": x,
                "click_y": y,
            }

        hit_indexes = [int(row["label_index"]) for row in hits]
        direction = _direction_from_city_hits(target_idx=target_idx, hit_indexes=hit_indexes)
        last_direction = "forward" if direction == "larger" else "backward"

        sx, sy, ex, ey = drag_forward_tuple if direction == "larger" else drag_backward_tuple
        app.drag(start_x=sx, start_y=sy, end_x=ex, end_y=ey, duration=drag_duration)
        time.sleep(max(after_drag, 0.0))

    _raise_error(
        "action_summary_stage_select_failed",
        f"Failed to locate action_summary stage for route '{route_id}' within {attempts} attempts",
        {"last_direction": last_direction, "region": list(region_tuple)},
    )


@action_info(
    name="resonance.check_pixel_color_range",
    public=True,
    read_only=True,
    description="Check whether one pixel color is inside an inclusive RGB range.",
)
@requires_services(
    app="plans/aura_base/app",
)
def resonance_check_pixel_color_range(
    x: int,
    y: int,
    rgb_min: List[int],
    rgb_max: List[int],
    app: Any = None,
) -> Dict[str, Any]:
    if app is None:
        _raise_error("missing_service", "app service is required")
    if not isinstance(rgb_min, list) or not isinstance(rgb_max, list) or len(rgb_min) != 3 or len(rgb_max) != 3:
        _raise_error("invalid_rgb_range", "rgb_min/rgb_max must both be [r, g, b]")

    color = app.get_pixel_color(int(x), int(y))
    if not isinstance(color, (list, tuple)) or len(color) < 3:
        _raise_error("pixel_read_failed", f"failed to read pixel color at ({x}, {y})")

    r = int(color[0])
    g = int(color[1])
    b = int(color[2])
    selected = (
        int(rgb_min[0]) <= r <= int(rgb_max[0])
        and int(rgb_min[1]) <= g <= int(rgb_max[1])
        and int(rgb_min[2]) <= b <= int(rgb_max[2])
    )
    return {
        "x": int(x),
        "y": int(y),
        "rgb": [r, g, b],
        "selected": selected,
    }

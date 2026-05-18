from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from .service import ConfigService

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}


@lru_cache(maxsize=4)
def get_config_service(base_path: Optional[str] = None):
    """Create and cache a ConfigService instance for global config lookups."""
    root = Path(base_path) if base_path else Path(__file__).resolve().parents[2]
    service = ConfigService()
    service.load_environment_configs(root)
    return service


def reset_config_service_cache() -> None:
    get_config_service.cache_clear()


def get_config_value(key_path: str, default: Any = None, base_path: Optional[str] = None) -> Any:
    """Read a config value using dot-path lookup with env overrides."""
    return get_config_service(base_path).get(key_path, default)


def get_config_section(section: str, default: Optional[dict] = None, base_path: Optional[str] = None) -> dict:
    """Read a config section (dict) with env overrides applied."""
    value = get_config_value(section, default or {}, base_path)
    return value if isinstance(value, dict) else (default or {})


def get_config_bool(key_path: str, default: bool = False, base_path: Optional[str] = None) -> bool:
    value = get_config_value(key_path, default, base_path)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


def get_config_list(
    key_path: str,
    default: Optional[list[str]] = None,
    base_path: Optional[str] = None,
) -> list[str]:
    value = get_config_value(key_path, default or [], base_path)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return list(default or [])
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return list(default or [])

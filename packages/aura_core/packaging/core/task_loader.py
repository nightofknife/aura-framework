# -*- coding: utf-8 -*-
"""Task definition loader with cache, parsing and normalization only."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

try:
    from cachetools import TTLCache
    from cachetools.keys import hashkey

    CACHETOOLS_AVAILABLE = True
except ImportError:
    CACHETOOLS_AVAILABLE = False
    TTLCache = dict  # type: ignore
    hashkey = lambda *args, **kwargs: str(args)  # type: ignore

from packages.aura_core.config.loader import get_config_value
from packages.aura_core.observability.logging.core_logger import logger

from packages.aura_core.packaging.core.task_validator import TaskDefinitionValidator


class TaskLoader:
    """Load and cache task yaml files for one plan."""

    _global_cache_version = 0
    _version_lock = threading.Lock()
    _file_locks: Dict[str, threading.RLock] = {}
    _locks_lock = threading.Lock()

    def __init__(self, plan_name: str, plan_path: Path, manifest: Optional[Any] = None):
        self.plan_name = plan_name

        if manifest and hasattr(manifest, "task_config"):
            self.task_paths = [plan_path / path for path in manifest.task_config.task_paths]
        else:
            self.task_paths = [plan_path / "tasks"]

        self.task_paths = [path for path in self.task_paths if path.is_dir()]
        self.tasks_dir = self.task_paths[0] if self.task_paths else plan_path / "tasks"

        cache_maxsize = int(get_config_value("task_loader.cache_maxsize", 1024))
        cache_ttl = int(get_config_value("task_loader.cache_ttl_sec", 300))
        self.cache = TTLCache(maxsize=cache_maxsize, ttl=cache_ttl)

        with TaskLoader._version_lock:
            self.cache_version = TaskLoader._global_cache_version

        enable_schema_validation = get_config_value("task_loader.enable_schema_validation", True)
        strict_validation = get_config_value("task_loader.strict_validation", False)
        self.task_validator = TaskDefinitionValidator(
            plan_name=self.plan_name,
            enable_schema_validation=enable_schema_validation,
            strict_validation=strict_validation,
        )

    @classmethod
    def invalidate_all_caches(cls):
        with cls._version_lock:
            cls._global_cache_version += 1
            logger.info("Task loader caches invalidated, version=%s", cls._global_cache_version)

    def _is_cache_valid(self) -> bool:
        with TaskLoader._version_lock:
            return self.cache_version == TaskLoader._global_cache_version

    def _update_cache_version(self):
        with TaskLoader._version_lock:
            self.cache_version = TaskLoader._global_cache_version

    def _get_file_lock(self, file_path: Path) -> threading.RLock:
        file_path_str = str(file_path)
        with TaskLoader._locks_lock:
            if file_path_str not in TaskLoader._file_locks:
                TaskLoader._file_locks[file_path_str] = threading.RLock()
            return TaskLoader._file_locks[file_path_str]

    def _load_and_parse_file(self, file_path: Path) -> Dict[str, Any]:
        if not self._is_cache_valid():
            logger.debug("Task cache expired for plan '%s', clearing local cache", self.plan_name)
            self.cache.clear()
            self._update_cache_version()

        file_lock = self._get_file_lock(file_path)
        with file_lock:
            key = hashkey(file_path)
            try:
                return self.cache[key]
            except KeyError:
                pass

            if not file_path.is_file():
                self.cache[key] = {}
                return {}

            try:
                with open(file_path, "r", encoding="utf-8") as handle:
                    data = yaml.safe_load(handle)
                result = data if isinstance(data, dict) else {}
                self.task_validator.validate_file(result, file_path)

                for task_def in result.values():
                    if isinstance(task_def, dict):
                        task_def.setdefault("execution_mode", "sync")

                self.cache[key] = result
                return result
            except Exception as exc:
                logger.error("Failed to load task file '%s': %s", file_path, exc)
                return {}

    def get_task_data(self, task_name_in_plan: str) -> Optional[Dict[str, Any]]:
        parts = task_name_in_plan.split("/")
        if not parts:
            return None

        task_key = parts[-1]
        attempts = []

        for task_dir in self.task_paths:
            direct_path = task_dir.joinpath(*parts).with_suffix(".yaml")
            if direct_path.is_file():
                direct_data = self._load_and_parse_file(direct_path)
                if isinstance(direct_data, dict):
                    if isinstance(direct_data.get("steps"), (list, dict)):
                        return self._normalize_task_concurrency(direct_data)
                    task_data = direct_data.get(task_key)
                    if isinstance(task_data, dict) and "steps" in task_data:
                        return self._normalize_task_concurrency(task_data)

            file_path_parts = parts[:-1]
            if not file_path_parts:
                file_path_parts.append(task_key)
            file_path = task_dir.joinpath(*file_path_parts).with_suffix(".yaml")
            if file_path.is_file():
                all_tasks_in_file = self._load_and_parse_file(file_path)
                task_data = all_tasks_in_file.get(task_key)
                if isinstance(task_data, dict) and "steps" in task_data:
                    return self._normalize_task_concurrency(task_data)
                if isinstance(all_tasks_in_file, dict) and isinstance(all_tasks_in_file.get("steps"), (list, dict)):
                    return self._normalize_task_concurrency(all_tasks_in_file)

            attempts.append(str(direct_path))
            if str(file_path) not in attempts:
                attempts.append(str(file_path))

        logger.warning(
            "Task definition not found in plan '%s': '%s' (attempts: %s)",
            self.plan_name,
            task_name_in_plan,
            ", ".join(attempts),
        )
        return None

    def _iter_task_definitions(self, task_file_data: Dict[str, Any], file_path: Path):
        return self.task_validator._iter_task_definitions(task_file_data, file_path)

    def _validate_removed_step_fields(self, task_file_data: Dict[str, Any], file_path: Path) -> None:
        self.task_validator._validate_removed_step_fields(task_file_data, file_path)

    def _validate_depends_on_syntax(
        self,
        spec: Any,
        *,
        file_path: Path,
        task_name: str,
        step_id: str,
        field_path: str,
    ) -> None:
        self.task_validator._validate_depends_on_syntax(
            spec,
            file_path=file_path,
            task_name=task_name,
            step_id=step_id,
            field_path=field_path,
        )

    def _normalize_task_concurrency(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(task_data, dict):
            return task_data

        meta = task_data.get("meta", {})
        if not isinstance(meta, dict):
            return task_data

        meta["__normalized_concurrency__"] = self._normalize_concurrency(meta.get("concurrency"))
        return task_data

    def _normalize_concurrency(self, concurrency: Any) -> Dict[str, Any]:
        if concurrency is None:
            return {
                "mode": "exclusive",
                "resources": [],
                "mutex_group": None,
                "max_instances": None,
            }

        if isinstance(concurrency, str):
            return {
                "mode": concurrency,
                "resources": [],
                "mutex_group": None,
                "max_instances": None,
            }

        if isinstance(concurrency, dict):
            mode = concurrency.get("mode")
            resources = concurrency.get("resources", [])
            mutex_group = concurrency.get("mutex_group")
            max_instances = concurrency.get("max_instances")

            if not mode and (resources or mutex_group):
                mode = "shared"
            if not mode:
                mode = "shared"

            return {
                "mode": mode,
                "resources": resources if isinstance(resources, list) else [resources] if resources else [],
                "mutex_group": mutex_group,
                "max_instances": max_instances,
            }

        logger.warning("Unknown concurrency spec '%s', fallback to exclusive", concurrency)
        return self._normalize_concurrency(None)

    def get_all_task_definitions(self) -> Dict[str, Any]:
        all_definitions: Dict[str, Any] = {}

        for task_dir in self.task_paths:
            if not task_dir.is_dir():
                continue

            for task_file_path in task_dir.rglob("*.yaml"):
                all_tasks_in_file = self._load_and_parse_file(task_file_path)
                relative_path = task_file_path.relative_to(task_dir).with_suffix("").as_posix()

                if isinstance(all_tasks_in_file, dict) and isinstance(all_tasks_in_file.get("steps"), (list, dict)):
                    all_definitions[relative_path] = all_tasks_in_file
                    continue

                for task_key, task_definition in all_tasks_in_file.items():
                    if isinstance(task_definition, dict) and "steps" in task_definition:
                        task_id = f"{relative_path}/{task_key}"
                        all_definitions[task_id] = task_definition
                        if task_key == Path(relative_path).name:
                            all_definitions.setdefault(relative_path, task_definition)

        return all_definitions

    def reload_task_file(self, file_path: Path) -> None:
        key = hashkey(file_path)
        if key in self.cache:
            logger.info("[TaskLoader] clearing cache for task file: %s", file_path.name)
            del self.cache[key]

        self._load_and_parse_file(file_path)
        logger.info("[TaskLoader] reloaded task file: %s", file_path.name)

# -*- coding: utf-8 -*-
"""Hot-reload control domain service for Scheduler."""

import sys
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List

from packages.aura_core.observability.logging.core_logger import logger

if TYPE_CHECKING:
    from .core import Scheduler


class HotReloadControlService:
    """Encapsulates reload and hot-reload orchestration logic."""

    def __init__(self, scheduler: "Scheduler"):
        self._scheduler = scheduler
        self._last_result: Dict[str, Any] = {
            "status": "idle",
            "message": "No reload has been requested.",
            "reload_id": None,
            "mode": None,
            "package_id": None,
            "blocked_by": [],
        }

    def get_reload_status(self) -> Dict[str, Any]:
        status = dict(self._last_result)
        status["running_tasks"] = self._blocking_tasks(status.get("package_id"))
        status["hot_reload_enabled"] = self.is_hot_reload_enabled()
        return status

    def plan_reload(self, package_id: str | None = None, *, mode: str = "runtime") -> Dict[str, Any]:
        normalized = _normalize_package_id(package_id)
        affected = self._affected_tasks(normalized)
        blocked_by = self._blocking_tasks(normalized)
        return {
            "status": "blocked" if blocked_by else "success",
            "mode": mode,
            "package_id": normalized,
            "packages": [normalized] if normalized else sorted(self._loaded_package_ids()),
            "affected_tasks": affected,
            "blocked_by": blocked_by,
            "message": "Reload is blocked by active runs." if blocked_by else "Reload can be applied.",
        }

    async def apply_reload(
        self,
        package_id: str | None = None,
        *,
        mode: str = "runtime",
        drain: bool = False,
        timeout_sec: float = 30.0,
    ) -> Dict[str, Any]:
        reload_id = f"reload-{uuid.uuid4().hex[:12]}"
        normalized = _normalize_package_id(package_id)
        created_at_ms = int(time.time() * 1000)
        barrier = getattr(self._scheduler, "reload_barrier", None)
        if barrier is not None:
            barrier.clear()
        plan = self.plan_reload(normalized, mode=mode)
        if plan.get("blocked_by") and not drain:
            result = {
                "reload_id": reload_id,
                "status": "failed",
                "mode": mode,
                "package_id": normalized,
                "created_at_ms": created_at_ms,
                "finished_at_ms": int(time.time() * 1000),
                "blocked_by": plan.get("blocked_by"),
                "message": "Reload blocked by active runs. Retry with drain=true or wait for completion.",
            }
            self._record_reload_result(result)
            if barrier is not None:
                barrier.set()
            return result

        self._last_result = {
            "reload_id": reload_id,
            "status": "draining" if drain else "reloading",
            "mode": mode,
            "package_id": normalized,
            "created_at_ms": created_at_ms,
            "blocked_by": plan.get("blocked_by", []),
            "message": "Reload started.",
        }
        try:
            if drain:
                deadline = time.time() + float(timeout_sec)
                while self._blocking_tasks(normalized):
                    if time.time() >= deadline:
                        result = {
                            **self._last_result,
                            "status": "failed",
                            "finished_at_ms": int(time.time() * 1000),
                            "blocked_by": self._blocking_tasks(normalized),
                            "message": "Timed out while draining active runs.",
                        }
                        self._record_reload_result(result)
                        return result
                    await _sleep(0.1)
                self._last_result["status"] = "reloading"

            if normalized:
                result = await self._reload_package(normalized)
            else:
                result = await self.reload_all()
            final = {
                "reload_id": reload_id,
                "status": result.get("status", "error"),
                "mode": mode,
                "package_id": normalized,
                "created_at_ms": created_at_ms,
                "finished_at_ms": int(time.time() * 1000),
                "packages": [normalized] if normalized else sorted(self._loaded_package_ids()),
                "message": result.get("message", ""),
            }
            self._record_reload_result(final)
            return final
        finally:
            if barrier is not None:
                barrier.set()

    async def reload_all(self) -> Dict[str, str]:
        from packages.aura_core.api import ACTION_REGISTRY, hook_manager

        logger.warning("======= Full reload started =======")
        with self._scheduler.fallback_lock:
            if self._scheduler.running_tasks:
                active_tasks = list(self._scheduler.running_tasks.keys())
                msg = f"Cannot reload: {len(active_tasks)} tasks are running: {active_tasks}"
                logger.error(msg)
                return {"status": "error", "message": msg}
            try:
                ACTION_REGISTRY.clear()
                self._scheduler._clear_service_registry()
                self._scheduler._register_core_services()
                hook_manager.clear()
            except Exception as exc:
                logger.critical("Critical error during full reload: %s", exc, exc_info=True)
                return {"status": "error", "message": f"A critical error occurred during reload: {exc}"}

        try:
            await self._scheduler.reload_plans_async()
            logger.info("======= Full reload finished =======")
            return {"status": "success", "message": "Full reload completed successfully."}
        except Exception as exc:
            logger.critical("Critical error during full reload: %s", exc, exc_info=True)
            return {"status": "error", "message": f"A critical error occurred during reload: {exc}"}

    async def reload_task_file(self, file_path: Path):
        with self._scheduler.fallback_lock:
            try:
                plan_name = file_path.relative_to(self._scheduler.base_path / "plans").parts[0]
                orchestrator = self._scheduler.plan_manager.get_plan(plan_name)
                if orchestrator:
                    orchestrator.task_loader.reload_task_file(file_path)
                    self._scheduler.plan_registry.load_all_tasks_definitions()
                    logger.info("Task file '%s' hot reloaded in plan '%s'.", file_path.name, plan_name)
                else:
                    logger.error("Hot reload failed: cannot locate plan '%s' for file '%s'.", plan_name, file_path.name)
            except Exception as exc:
                logger.error("Failed reloading task file '%s': %s", file_path.name, exc, exc_info=True)

    async def reload_plugin_from_py_file(self, file_path: Path):
        from packages.aura_core.api import ACTION_REGISTRY

        with self._scheduler.fallback_lock:
            try:
                try:
                    plan_dir_name = file_path.relative_to(self._scheduler.base_path / "plans").parts[0]
                except ValueError:
                    logger.error("Reload failed: file '%s' is outside plans directory.", file_path)
                    return

                plan_dir = (self._scheduler.base_path / "plans" / plan_dir_name).resolve()
                manifest = next(
                    (
                        m
                        for m in self._scheduler.plan_manager.package_manager.loaded_packages.values()
                        if m.path.resolve() == plan_dir
                    ),
                    None,
                )
                if not manifest:
                    logger.error("Reload failed: no package manifest found for '%s'.", plan_dir)
                    return

                package_id = manifest.package.canonical_id
                if any(task_id.startswith(f"{package_id}/") for task_id in self._scheduler.running_tasks):
                    logger.warning("Skip reloading package '%s': tasks are still running.", package_id)
                    return

                logger.info("Reloading package '%s'...", package_id)
                ACTION_REGISTRY.remove_actions_by_plugin(package_id)
                self._scheduler._remove_services_by_prefix(f"{package_id}/")

                module_prefix = ".".join(manifest.path.relative_to(self._scheduler.base_path).parts)
                modules_to_remove = [name for name in sys.modules if name.startswith(module_prefix)]
                for mod_name in modules_to_remove:
                    del sys.modules[mod_name]

                self._scheduler.plan_registry.load_all()
                logger.info("Package '%s' reloaded.", package_id)
            except Exception as exc:
                logger.error("Error reloading plugin from python file: %s", exc, exc_info=True)

    def enable_hot_reload(self):
        return self._scheduler.hot_reload.enable()

    def disable_hot_reload(self):
        return self._scheduler.hot_reload.disable()

    def is_hot_reload_enabled(self) -> bool:
        return self._scheduler.hot_reload.is_enabled()

    async def _reload_package(self, package_id: str) -> Dict[str, str]:
        # V6 uses the same safe full registry refresh for package reload, with
        # package-scoped blocking and metadata. Partial module reload remains
        # reserved for a later compatibility pass.
        return await self.reload_all()

    def _blocking_tasks(self, package_id: str | None = None) -> List[Dict[str, Any]]:
        with self._scheduler.fallback_lock:
            rows = []
            for cid, meta in self._scheduler._running_task_meta.items():
                plan_name = meta.get("plan_name")
                if package_id and plan_name not in {package_id, package_id.split("/")[-1]}:
                    continue
                rows.append({"cid": cid, **dict(meta)})
            return rows

    def _loaded_package_ids(self) -> set[str]:
        package_manager = getattr(self._scheduler.plan_manager, "package_manager", None)
        if not package_manager:
            return set()
        ids = set()
        for manifest in package_manager.loaded_packages.values():
            package = getattr(manifest, "package", None)
            canonical = getattr(package, "canonical_id", None) or getattr(manifest, "canonical_id", None)
            if canonical:
                ids.add(str(canonical).lstrip("@"))
        return ids

    def _affected_tasks(self, package_id: str | None = None) -> List[str]:
        with self._scheduler.fallback_lock:
            all_tasks = sorted(self._scheduler.all_tasks_definitions.keys())
        if not package_id:
            return all_tasks
        tail = package_id.split("/")[-1]
        return [task_id for task_id in all_tasks if task_id.startswith(f"{tail}/") or task_id.startswith(f"{package_id}/")]

    def _record_reload_result(self, result: Dict[str, Any]) -> None:
        self._last_result = dict(result)
        store = getattr(getattr(self._scheduler, "observability", None), "run_store", None)
        if store is not None:
            try:
                store.record_reload_operation(result)
                if result.get("status") == "success":
                    store.record_runtime_generation(
                        generation_id=str(result.get("reload_id")),
                        reason=str(result.get("mode") or "runtime_reload"),
                        packages=result.get("packages") or [],
                        payload=result,
                    )
            except Exception:
                logger.debug("Failed to record reload operation", exc_info=True)


def _normalize_package_id(package_id: str | None) -> str | None:
    if not package_id:
        return None
    return str(package_id).strip().lstrip("@").replace("\\", "/")


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)

# -*- coding: utf-8 -*-
"""Package manager based on `manifest.yaml`."""

from __future__ import annotations

import logging
from graphlib import TopologicalSorter
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from ...api import ACTION_REGISTRY, ActionDefinition, ServiceDefinition, service_registry
from ...config.loader import get_config_value
from ..manifest import ManifestGenerator, ManifestParser, PluginManifest

logger = logging.getLogger(__name__)


class PackageManager:
    """Discover, validate, resolve and load manifest-based packages."""

    def __init__(self, packages_dir: Path, plans_dir: Path):
        self.packages_dir = packages_dir
        self.plans_dir = plans_dir
        self.base_path = packages_dir.parent

        manifest_mode = str(
            get_config_value("package.manifest_mode", "", base_path=str(self.base_path)) or ""
        ).strip().lower()
        if not manifest_mode:
            use_manifest_system = bool(
                get_config_value("package.use_manifest_system", True, base_path=str(self.base_path))
            )
            manifest_mode = "strict" if use_manifest_system else "off"

        if manifest_mode not in {"strict", "hybrid", "off"}:
            logger.warning("Unknown package.manifest_mode '%s', fallback to strict", manifest_mode)
            manifest_mode = "strict"

        self.manifest_mode = manifest_mode
        self.auto_sync_manifest = bool(
            get_config_value(
                "package.auto_sync_manifest_on_startup",
                self.manifest_mode in {"hybrid", "off"},
                base_path=str(self.base_path),
            )
        )

        self.loaded_packages: Dict[str, PluginManifest] = {}

    @property
    def _is_hybrid_mode(self) -> bool:
        return self.manifest_mode in {"hybrid", "off"}

    def _iter_package_dirs(self) -> Iterable[Path]:
        candidates = [(self.packages_dir, False), (self.plans_dir, True)]
        for base_dir, include_all in candidates:
            if not base_dir.exists() or not base_dir.is_dir():
                continue

            for item in base_dir.iterdir():
                if not item.is_dir():
                    continue
                if item.name.startswith(".") or item.name.startswith("__"):
                    continue

                if include_all:
                    yield item
                    continue

                manifest_path = item / "manifest.yaml"
                has_runtime_layout = (item / "src").is_dir() or (item / "tasks").is_dir()
                if manifest_path.is_file() or has_runtime_layout:
                    yield item

    def _auto_sync_manifests(self):
        if not self.auto_sync_manifest:
            return

        synced_count = 0
        for package_dir in self._iter_package_dirs():
            try:
                generator = ManifestGenerator(package_dir)
                try:
                    manifest_data = generator.generate(preserve_manual_edits=True)
                except Exception as e:
                    if not self._is_hybrid_mode:
                        raise
                    logger.warning(
                        "Manifest merge failed for '%s', fallback to generated-only manifest: %s",
                        package_dir,
                        e,
                    )
                    manifest_data = generator.generate(preserve_manual_edits=False)

                generator.save(manifest_data)
                synced_count += 1
            except Exception as e:
                if self._is_hybrid_mode:
                    logger.warning("Manifest auto-sync skipped for '%s': %s", package_dir, e)
                    continue
                raise

        if synced_count:
            logger.info("Manifest auto-sync completed: %s package(s)", synced_count)

    def _build_fallback_manifest(self, package_dir: Path, reason: str) -> Optional[PluginManifest]:
        try:
            generator = ManifestGenerator(package_dir)
            manifest_data = generator.generate(preserve_manual_edits=False)
            generator.save(manifest_data)
            manifest = ManifestParser.parse(package_dir / "manifest.yaml")
            logger.warning("Using generated fallback manifest for '%s' (%s)", package_dir, reason)
            return manifest
        except Exception as e:
            logger.error("Fallback manifest generation failed for '%s': %s", package_dir, e)
            return None

    def load_all_packages(self):
        logger.info("======= PackageManager: start loading all packages =======")

        self.loaded_packages.clear()

        if self.auto_sync_manifest:
            self._auto_sync_manifests()

        manifests = self._discover_packages()
        self._validate_manifests(manifests)
        load_order = self._resolve_dependencies(manifests)
        self._load_in_order(load_order, manifests)

        try:
            service_registry.validate_no_circular_dependencies()
        except ValueError as e:
            logger.error("Service dependency validation failed: %s", e)
            raise

        logger.info("======= loaded %s packages =======", len(self.loaded_packages))

    def _discover_packages(self) -> Dict[str, PluginManifest]:
        manifests: Dict[str, PluginManifest] = {}
        discovered_dirs: set[Path] = set()

        for base_dir in [self.packages_dir, self.plans_dir]:
            if not base_dir.exists():
                continue

            for manifest_path in base_dir.rglob("manifest.yaml"):
                discovered_dirs.add(manifest_path.parent.resolve())
                try:
                    manifest = ManifestParser.parse(manifest_path)
                    package_id = manifest.package.canonical_id
                    if package_id in manifests:
                        logger.warning(
                            "Duplicate package canonical_id '%s', last one wins: %s",
                            package_id,
                            manifest_path,
                        )
                    manifests[package_id] = manifest
                    logger.info("Discovered package %s v%s", manifest.package.canonical_id, manifest.package.version)
                except Exception as e:
                    if self._is_hybrid_mode:
                        logger.warning("Manifest parse failed for '%s': %s", manifest_path, e)
                        fallback = self._build_fallback_manifest(
                            manifest_path.parent,
                            reason=f"parse failed: {e}",
                        )
                        if fallback:
                            manifests[fallback.package.canonical_id] = fallback
                    else:
                        raise ValueError(f"Failed to parse manifest '{manifest_path}': {e}")

        if self._is_hybrid_mode:
            for package_dir in self._iter_package_dirs():
                resolved_dir = package_dir.resolve()
                if resolved_dir in discovered_dirs:
                    continue

                fallback = self._build_fallback_manifest(package_dir, reason="manifest missing")
                if fallback:
                    manifests[fallback.package.canonical_id] = fallback

        return manifests

    def _validate_manifests(self, manifests: Dict[str, PluginManifest]):
        for package_id, manifest in manifests.items():
            errors = ManifestParser.validate(manifest)
            if errors:
                if self._is_hybrid_mode:
                    logger.warning("Package %s has invalid manifest, continue in hybrid mode:", package_id)
                    for error in errors:
                        logger.warning("  - %s", error)
                    continue

                logger.error("Package %s manifest validation failed:", package_id)
                for error in errors:
                    logger.error("  - %s", error)
                raise ValueError(f"Package {package_id} has invalid manifest")

    def _resolve_dependencies(self, manifests: Dict[str, PluginManifest]) -> List[str]:
        graph: Dict[str, List[str]] = {}
        missing_deps: Dict[str, list] = {}

        for package_id, manifest in manifests.items():
            deps: List[str] = []
            for dep_spec in manifest.dependencies.values():
                dep_id = dep_spec.name.lstrip("@")

                if not dep_spec.optional and dep_id not in manifests:
                    missing_deps.setdefault(package_id, []).append((dep_id, dep_spec))
                    continue

                if dep_id in manifests:
                    deps.append(dep_id)

            graph[package_id] = deps

        if missing_deps:
            error_lines = ["Missing package dependencies detected:"]
            for pkg_id, deps in missing_deps.items():
                error_lines.append(f"\nPackage '{pkg_id}' missing required dependencies:")
                for _, dep_spec in deps:
                    error_lines.append(
                        f"  - {dep_spec.name} (version: {dep_spec.version}, source: {dep_spec.source})"
                    )

            if self._is_hybrid_mode:
                logger.warning("\n".join(error_lines))
            else:
                raise ValueError("\n".join(error_lines))

        sorter = TopologicalSorter(graph)
        try:
            load_order = list(sorter.static_order())
            logger.info("Dependency resolved, load order: %s", " -> ".join(load_order))
            return load_order
        except Exception as e:
            logger.error("Dependency resolution failed (possible cycle): %s", e)
            for pkg_id, deps in graph.items():
                logger.error("  %s -> %s", pkg_id, deps)
            if self._is_hybrid_mode:
                logger.warning("Dependency graph has cycle, fallback to discovery order in hybrid mode")
                return list(manifests.keys())
            raise ValueError(f"Cyclic package dependency detected, cannot load. detail: {e}")

    def _load_in_order(self, load_order: List[str], manifests: Dict[str, PluginManifest]):
        for package_id in load_order:
            if package_id not in manifests:
                continue

            manifest = manifests[package_id]
            logger.info("Loading package: %s", package_id)

            try:
                if manifest.lifecycle.on_load:
                    self._call_hook(manifest, manifest.lifecycle.on_load)

                self._register_services(manifest)
                self._register_actions(manifest)
                self._register_tasks(manifest)

                self.loaded_packages[package_id] = manifest
                logger.info("Package %s loaded", package_id)
            except Exception as e:
                logger.error("Package %s load failed: %s", package_id, e)
                raise

    def _call_hook(self, manifest: PluginManifest, hook: str):
        try:
            module_path, func_name = hook.split(":")
            module = self._import_plugin_module(manifest, module_path)
            func = getattr(module, func_name)

            logger.info("Calling hook: %s", hook)
            func()
        except Exception as e:
            logger.warning("Hook call failed %s: %s", hook, e)

    def _normalize_module_parts(self, module_path: str) -> List[str]:
        normalized = module_path.replace("\\", "/")
        if normalized.endswith(".py"):
            normalized = normalized[:-3]
        if "/" in normalized:
            parts = normalized.split("/")
        else:
            parts = normalized.split(".")
        return [part for part in parts if part]

    def _ensure_package(self, name: str, path: Path):
        import importlib.machinery
        import sys
        import types

        if name in sys.modules:
            return
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        module.__package__ = name
        module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
        module.__spec__.submodule_search_locations = [str(path)]
        sys.modules[name] = module

    def _import_plugin_module(self, manifest: PluginManifest, module_path: str):
        import importlib.util
        import re
        import sys

        parts = self._normalize_module_parts(module_path)
        if not parts:
            raise ImportError(f"Invalid module path: {module_path!r}")

        canonical_id = manifest.package.canonical_id.lstrip("@")
        safe_id = re.sub(r"[^a-zA-Z0-9_]", "_", canonical_id)
        base_pkg = f"aura_pkg_{safe_id}"

        self._ensure_package(base_pkg, manifest.path)
        for idx in range(1, len(parts)):
            pkg_name = base_pkg + "." + ".".join(parts[:idx])
            pkg_path = manifest.path / Path(*parts[:idx])
            self._ensure_package(pkg_name, pkg_path)

        rel_path = Path(*parts)
        module_file = manifest.path / rel_path
        is_package = False
        if module_file.is_dir():
            module_file = module_file / "__init__.py"
            is_package = True
        if module_file.suffix != ".py":
            module_file = module_file.with_suffix(".py")

        if not module_file.exists():
            raise ImportError(f"Module file not found: {module_file}")

        full_module_name = base_pkg + "." + ".".join(parts)
        if full_module_name in sys.modules:
            return sys.modules[full_module_name]

        spec = importlib.util.spec_from_file_location(
            full_module_name,
            str(module_file),
            submodule_search_locations=[str(module_file.parent)] if is_package else None,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load module spec: {module_file}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[full_module_name] = module
        spec.loader.exec_module(module)
        return module

    def _register_services(self, manifest: PluginManifest):
        try:
            for service in manifest.exports.services:
                module_path, class_name = service.source.split(":")
                module = self._import_plugin_module(manifest, module_path)
                service_class = getattr(module, class_name)

                service_fqid = f"{manifest.package.canonical_id}/{service.name}"

                definition = ServiceDefinition(
                    alias=service.name,
                    fqid=service_fqid,
                    service_class=service_class,
                    plugin=manifest,
                    public=service.visibility == "public",
                )
                service_registry.register(definition)

                logger.info("  [OK] Register service: %s", service_fqid)
        except Exception as e:
            logger.error("Register service failed (package: %s): %s", manifest.package.canonical_id, e)
            raise

    def _register_actions(self, manifest: PluginManifest):
        import inspect

        try:
            for action in manifest.exports.actions:
                module_path, func_name = action.source.split(":")
                module = self._import_plugin_module(manifest, module_path)
                action_func = getattr(module, func_name)

                canonical_id = manifest.package.canonical_id.lstrip("@")
                parts = canonical_id.split("/")
                if len(parts) != 2:
                    logger.warning("Package canonical_id format is invalid; expected @author/package.")
                    action_fqid = f"{canonical_id}/{action.name}"
                else:
                    author, package_name = parts
                    action_fqid = f"{author}/{package_name}/{action.name}"

                service_deps = getattr(action_func, "_service_dependencies", {})

                definition = ActionDefinition(
                    func=action_func,
                    name=action.name,
                    read_only=False,
                    public=action.visibility == "public",
                    service_deps=service_deps,
                    plugin=manifest,
                    is_async=inspect.iscoroutinefunction(action_func),
                )
                ACTION_REGISTRY.register(definition)

                logger.info("  [OK] Register action: %s", action_fqid)
        except Exception as e:
            logger.error("Register action failed (package: %s): %s", manifest.package.canonical_id, e)
            raise

    def _register_tasks(self, manifest: PluginManifest):
        if manifest.exports.tasks:
            logger.info(
                "Manifest exports.tasks for %s are metadata only; runtime task index comes from TaskLoader/task_paths.",
                manifest.package.canonical_id,
            )
        for task in manifest.exports.tasks:
            logger.info("  [OK] Discover task: %s/%s", manifest.package.canonical_id, task.id)

    def get_package(self, package_id: str) -> Optional[PluginManifest]:
        return self.loaded_packages.get(package_id)

# packages/aura_core/service_registry.py

import inspect
import importlib.util
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Type, Optional
from dataclasses import dataclass, field
import threading

# 确保从正确的位置导入
from packages.aura_shared_utils.utils.logger import logger
from packages.aura_shared_utils.models.plugin_definition import PluginDefinition
from packages.aura_core.inheritance_proxy import InheritanceProxy


@dataclass
class ServiceDefinition:
    """【最终版】一个数据类，用于封装一个服务的所有元数据。"""
    short_name: str
    fqid: str
    service_class: Type
    source_path: Path
    plugin: PluginDefinition
    instance: Any = None
    status: str = "defined"
    is_extension: bool = False
    parent_fqid: Optional[str] = None


class ServiceRegistry:
    """【最终版】单例服务注册中心。"""

    def __init__(self):
        self._fqid_map: Dict[str, ServiceDefinition] = {}
        self._short_name_map: Dict[str, str] = {}
        self._instances: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._base_path = Path(__file__).resolve().parents[2]

    def clear(self):
        with self._lock:
            self._fqid_map.clear()
            self._short_name_map.clear()
            self._instances.clear()
            logger.info("服务注册中心已清空。")

    def scan_path(self, services_dir: Path, plugin_def: PluginDefinition):
        if not services_dir.is_dir():
            return
        for file_path in services_dir.glob("**/*_service.py"):
            try:
                short_name = file_path.stem.replace('_service', '')
                class_name = "".join(word.capitalize() for word in short_name.split('_')) + "Service"
                # 【关键】使用 plugin_def 来构建正确的 FQID
                fqid = f"{plugin_def.canonical_id}/{short_name}"
                module = self._load_module_from_path(file_path)
                if not module: continue
                service_class = getattr(module, class_name, None)
                if not service_class:
                    logger.warning(f"在 {file_path.name} 中找不到约定的类 '{class_name}'。")
                    continue
                # 【关键】将完整的 plugin_def 传递给 register
                self.register(short_name, fqid, service_class, file_path, plugin_def)
            except Exception as e:
                raise RuntimeError(f"加载服务 '{file_path.name}' 失败。") from e

    def register(self, short_name: str, fqid: str, service_class: Type, source_path: Path,
                 plugin_def: PluginDefinition):
        with self._lock:
            if fqid in self._fqid_map:
                raise RuntimeError(f"服务 FQID 冲突！'{fqid}' 已被注册。")

            # 【关键】创建 ServiceDefinition 时传入 plugin_def
            definition = ServiceDefinition(
                short_name=short_name, fqid=fqid, service_class=service_class,
                source_path=source_path, plugin=plugin_def
            )

            if short_name in self._short_name_map:
                existing_fqid = self._short_name_map[short_name]
                existing_plugin_id = self._fqid_map[existing_fqid].plugin.canonical_id

                is_extending = any(
                    ext.service == short_name and ext.from_plugin == existing_plugin_id for ext in plugin_def.extends)
                is_overriding = existing_fqid in plugin_def.overrides

                if is_extending and is_overriding:
                    raise RuntimeError(
                        f"插件 '{plugin_def.canonical_id}' 不能同时 extend 和 override 同一个服务 '{short_name}'。")

                if is_extending:
                    logger.info(f"服务继承: '{fqid}' 正在扩展 '{existing_fqid}'。")
                    definition.is_extension = True
                    definition.parent_fqid = existing_fqid
                    self._short_name_map[short_name] = fqid
                elif is_overriding:
                    logger.warning(f"服务覆盖: '{fqid}' 正在覆盖 '{existing_fqid}'。")
                    self._short_name_map[short_name] = fqid
                else:
                    raise RuntimeError(
                        f"服务名称冲突！插件 '{plugin_def.canonical_id}' 尝试定义服务 '{short_name}'，"
                        f"但该名称已被 '{existing_fqid}' 使用。\n"
                        f"如果你的意图是扩展或覆盖，请在 '{plugin_def.path / 'plugin.yaml'}' "
                        f"中使用 'extends' 或 'overrides' 字段明确声明。"
                    )
            else:
                self._short_name_map[short_name] = fqid

            self._fqid_map[fqid] = definition
            logger.debug(f"已定义服务: '{fqid}' (短名称: '{short_name}')")

    def get_service_instance(self, service_id: str, resolution_chain: Optional[List[str]] = None) -> Any:
        with self._lock:
            is_fqid_request = '/' in service_id
            if is_fqid_request:
                target_fqid = service_id
            else:
                target_fqid = self._short_name_map.get(service_id)
                if not target_fqid:
                    raise NameError(f"找不到短名称为 '{service_id}' 的服务。")

            if target_fqid in self._instances:
                return self._instances[target_fqid]

            return self._instantiate_service(target_fqid, resolution_chain or [])

    def _instantiate_service(self, fqid: str, resolution_chain: List[str]) -> Any:
        if fqid in resolution_chain:
            raise RecursionError(f"检测到服务间的循环依赖: {' -> '.join(resolution_chain)} -> {fqid}")
        resolution_chain.append(fqid)

        definition = self._fqid_map.get(fqid)
        if not definition:
            raise NameError(f"找不到请求的服务定义: '{fqid}'")

        if definition.status == "failed":
            raise RuntimeError(f"服务 '{fqid}' 在之前的尝试中加载失败。")
        if definition.status == "resolving":
            raise RuntimeError(f"服务 '{fqid}' 正在解析中，可能存在并发问题。")

        try:
            definition.status = "resolving"
            logger.debug(f"开始解析服务: '{fqid}'")
            instance: Any

            if not definition.is_extension:
                dependencies = self._resolve_constructor_dependencies(definition, resolution_chain)
                instance = definition.service_class(**dependencies)
            else:
                logger.debug(f"处理继承服务 '{fqid}'，父服务是 '{definition.parent_fqid}'")
                parent_instance = self._instantiate_service(definition.parent_fqid, resolution_chain)
                child_dependencies = self._resolve_constructor_dependencies(definition, resolution_chain)
                if 'parent_service' not in inspect.signature(definition.service_class.__init__).parameters:
                    raise TypeError(f"继承服务 '{fqid}' 的构造函数 __init__ 必须接受一个 'parent_service' 参数。")
                child_dependencies['parent_service'] = parent_instance
                child_instance = definition.service_class(**child_dependencies)
                instance = InheritanceProxy(parent_service=parent_instance, child_service=child_instance)

            self._instances[fqid] = instance
            definition.instance = instance
            definition.status = "resolved"
            logger.info(f"服务 '{fqid}' 已成功实例化。")
            return instance

        except Exception as e:
            definition.status = "failed"
            logger.error(f"实例化服务 '{fqid}' 失败: {e}", exc_info=True)
            raise
        finally:
            if fqid in resolution_chain:
                resolution_chain.pop()

    def _resolve_constructor_dependencies(self, definition: ServiceDefinition, resolution_chain: List[str]) -> Dict[
        str, Any]:
        dependencies = {}
        init_signature = inspect.signature(definition.service_class.__init__)

        for param_name, param in init_signature.parameters.items():
            if param_name in ['self', 'parent_service']:
                continue

            dependency_short_name = param_name
            dependencies[param_name] = self.get_service_instance(dependency_short_name, resolution_chain)

        return dependencies

    def get_all_service_definitions(self) -> List[ServiceDefinition]:
        with self._lock:
            return sorted(list(self._fqid_map.values()), key=lambda s: s.fqid)

    def _load_module_from_path(self, file_path: Path) -> Optional[Any]:
        try:
            relative_to_base = file_path.relative_to(self._base_path)
            module_dot_path = str(relative_to_base).replace(os.sep, '.').replace('.py', '')
            if module_dot_path in sys.modules: return sys.modules[module_dot_path]
            spec = importlib.util.spec_from_file_location(module_dot_path, file_path)
            if spec is None: return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_dot_path] = module
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            raise RuntimeError(f"从路径 '{file_path}' 加载模块失败。") from e


service_registry = ServiceRegistry()

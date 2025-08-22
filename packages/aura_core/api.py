import asyncio
import inspect
import textwrap
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Any, Dict, List, Optional, Type

from packages.aura_core.inheritance_proxy import InheritanceProxy
from packages.aura_core.plugin_definition import PluginDefinition
from packages.aura_core.logger import logger


@dataclass
class ActionDefinition:
    """
    【Async Refactor】增加了 is_async 标志。
    """
    func: Callable
    name: str
    read_only: bool
    public: bool
    service_deps: Dict[str, str]
    plugin: PluginDefinition
    is_async: bool = False  # 新增字段

    @property
    def signature(self) -> inspect.Signature:
        return inspect.signature(self.func)

    @property
    def docstring(self) -> str:
        doc = inspect.getdoc(self.func)
        return textwrap.dedent(doc).strip() if doc else "此行为没有提供文档说明。"

    @property
    def fqid(self) -> str:
        return f"{self.plugin.canonical_id}/{self.name}"


# ... (ActionRegistry, register_action, requires_services 保持不变) ...
class ActionRegistry:
    def __init__(self): self._actions: Dict[str, ActionDefinition] = {}

    def clear(self): self._actions.clear()

    def register(self, action_def: ActionDefinition):
        if action_def.name in self._actions:
            existing_fqid = self._actions[action_def.name].fqid
            logger.warning(
                f"行为名称冲突！'{action_def.name}' (来自 {action_def.fqid}) 覆盖了之前的定义 (来自 {existing_fqid})。")
        self._actions[action_def.name] = action_def
        logger.debug(f"已定义行为: '{action_def.fqid}' (公开: {action_def.public}, 异步: {action_def.is_async})")

    def get_all_action_definitions(self) -> List[ActionDefinition]: return sorted(list(self._actions.values()),
                                                                                  key=lambda a: a.fqid)

    def __len__(self) -> int: return len(self._actions)

    def get(self, name: str) -> Optional[ActionDefinition]: return self._actions.get(name)


ACTION_REGISTRY = ActionRegistry()


def register_action(name: str, read_only: bool = False, public: bool = False):
    def decorator(func: Callable) -> Callable:
        meta = {'name': name, 'read_only': read_only, 'public': public,
                'services': getattr(func, '_service_dependencies', {})}
        setattr(func, '_aura_action_meta', meta)
        return func

    return decorator


def requires_services(*args: str, **kwargs: str):
    def decorator(func: Callable) -> Callable:
        dependencies = {}
        for alias, service_id in kwargs.items(): dependencies[alias] = service_id
        for service_id in args:
            default_alias = service_id.split('/')[-1]
            if default_alias in dependencies: raise NameError(
                f"在 @requires_services for '{func.__name__}' 中检测到依赖别名冲突: '{default_alias}'。")
            dependencies[default_alias] = service_id
        setattr(func, '_service_dependencies', dependencies)
        return func

    return decorator


# ... (ServiceDefinition, ServiceRegistry, register_service 保持不变) ...
# ServiceRegistry is complex and deals with instantiation, which can be blocking.
# Keeping its internal lock as threading.RLock is safer and avoids a much deeper refactor.
# Its public methods are thread-safe and will work correctly when called from async code via run_in_executor
# or from other threads like the UI.
@dataclass
class ServiceDefinition:
    alias: str
    fqid: str
    service_class: Type
    plugin: Optional[PluginDefinition]
    public: bool
    instance: Any = None
    status: str = "defined"
    is_extension: bool = False
    parent_fqid: Optional[str] = None


class ServiceRegistry:
    # ... (内容不变) ...
    def __init__(self):
        self._fqid_map: Dict[str, ServiceDefinition] = {}
        self._short_name_map: Dict[str, str] = {}
        self._instances: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def clear(self):
        with self._lock:
            self._fqid_map.clear()
            self._short_name_map.clear()
            self._instances.clear()
            logger.info("服务注册中心已清空。")

    def register(self, definition: ServiceDefinition):
        # ... (内容不变) ...
        with self._lock:
            if definition.fqid in self._fqid_map: raise RuntimeError(f"服务 FQID 冲突！'{definition.fqid}' 已被注册。")
            short_name = definition.alias
            if short_name in self._short_name_map:
                existing_fqid = self._short_name_map[short_name]
                existing_plugin_id = self._fqid_map[existing_fqid].plugin.canonical_id
                is_extending = any(ext.service == short_name and ext.from_plugin == existing_plugin_id for ext in
                                   definition.plugin.extends)
                is_overriding = existing_fqid in definition.plugin.overrides
                if is_extending and is_overriding: raise RuntimeError(
                    f"插件 '{definition.plugin.canonical_id}' 不能同时 extend 和 override 同一个服务 '{short_name}'。")
                if is_extending:
                    logger.info(f"服务继承: '{definition.fqid}' 正在扩展 '{existing_fqid}'。")
                    definition.is_extension = True
                    definition.parent_fqid = existing_fqid
                    self._short_name_map[short_name] = definition.fqid
                elif is_overriding:
                    logger.warning(f"服务覆盖: '{definition.fqid}' 正在覆盖 '{existing_fqid}'。")
                    self._short_name_map[short_name] = definition.fqid
                else:
                    raise RuntimeError(
                        f"服务名称冲突！插件 '{definition.plugin.canonical_id}' 尝试定义服务 '{short_name}'，但该名称已被 '{existing_fqid}' 使用。\n如果你的意图是扩展或覆盖，请在 '{definition.plugin.path / 'plugin.yaml'}' 中使用 'extends' 或 'overrides' 字段明确声明。")
            else:
                self._short_name_map[short_name] = definition.fqid
            self._fqid_map[definition.fqid] = definition
            logger.debug(f"已定义服务: '{definition.fqid}' (别名: '{short_name}', 公开: {definition.public})")

    def register_instance(self, alias: str, instance: Any, fqid: Optional[str] = None, public: bool = False):
        # ... (内容不变) ...
        with self._lock:
            target_fqid = fqid or f"core/{alias}"
            if target_fqid in self._fqid_map: logger.warning(f"服务实例 '{target_fqid}' 正在被覆盖注册。")
            if alias in self._short_name_map and self._short_name_map[alias] != target_fqid:
                existing_fqid = self._short_name_map[alias]
                logger.warning(f"服务别名冲突！'{alias}' 已指向 '{existing_fqid}'。现在将其重新指向 '{target_fqid}'。")
            definition = ServiceDefinition(alias=alias, fqid=target_fqid, service_class=type(instance), plugin=None,
                                           public=public, instance=instance, status="resolved")
            self._fqid_map[target_fqid] = definition
            self._short_name_map[alias] = target_fqid
            self._instances[target_fqid] = instance
            logger.info(f"核心服务实例 '{target_fqid}' 已通过别名 '{alias}' 直接注册。")

    def get_service_instance(self, service_id: str, resolution_chain: Optional[List[str]] = None) -> Any:
        # ... (内容不变) ...
        with self._lock:
            is_fqid_request = '/' in service_id
            target_fqid = service_id if is_fqid_request else self._short_name_map.get(service_id)
            if not target_fqid: raise NameError(f"找不到别名为 '{service_id}' 的服务。")
            if target_fqid in self._instances: return self._instances[target_fqid]
            return self._instantiate_service(target_fqid, resolution_chain or [])

    def _instantiate_service(self, fqid: str, resolution_chain: List[str]) -> Any:
        # ... (内容不变) ...
        if fqid in resolution_chain: raise RecursionError(
            f"检测到服务间的循环依赖: {' -> '.join(resolution_chain)} -> {fqid}")
        resolution_chain.append(fqid)
        definition = self._fqid_map.get(fqid)
        if not definition: raise NameError(f"找不到请求的服务定义: '{fqid}'")
        if definition.status == "failed": raise RuntimeError(f"服务 '{fqid}' 在之前的尝试中加载失败。")
        if definition.status == "resolving": raise RuntimeError(f"服务 '{fqid}' 正在解析中，可能存在并发问题。")
        try:
            definition.status = "resolving"
            logger.debug(f"开始解析服务: '{fqid}'")
            instance: Any
            if not definition.is_extension:
                dependencies = self._resolve_constructor_dependencies(definition, resolution_chain)
                instance = definition.service_class(**dependencies)
            else:
                parent_instance = self._instantiate_service(definition.parent_fqid, resolution_chain)
                child_dependencies = self._resolve_constructor_dependencies(definition, resolution_chain)
                if 'parent_service' not in inspect.signature(
                        definition.service_class.__init__).parameters: raise TypeError(
                    f"继承服务 '{fqid}' 的构造函数 __init__ 必须接受一个 'parent_service' 参数。")
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
            if fqid in resolution_chain: resolution_chain.pop()

    def _resolve_constructor_dependencies(self, definition: ServiceDefinition, resolution_chain: List[str]) -> Dict[
        str, Any]:
        # ... (内容不变) ...
        dependencies = {}
        init_signature = inspect.signature(definition.service_class.__init__)
        type_to_fqid_map = {sd.service_class: sd.fqid for sd in self._fqid_map.values()}
        for param_name, param in init_signature.parameters.items():
            if param_name in ['self', 'parent_service']: continue
            dependency_fqid = None
            if param.annotation is not inspect.Parameter.empty and param.annotation in type_to_fqid_map:
                dependency_fqid = type_to_fqid_map[param.annotation]
            if dependency_fqid is None:
                dependency_alias = param_name
                dependency_fqid = self._short_name_map.get(dependency_alias)
                if not dependency_fqid: raise NameError(
                    f"为 '{definition.fqid}' 自动解析依赖 '{param_name}' 失败：无法通过类型注解或参数名找到对应的服务。")
            dependencies[param_name] = self.get_service_instance(dependency_fqid, resolution_chain)
        return dependencies

    def get_all_service_definitions(self) -> List[ServiceDefinition]:
        with self._lock:
            return sorted(list(self._fqid_map.values()), key=lambda s: s.fqid)

    def remove_services_by_prefix(self, prefix: str = "", exclude_prefix: Optional[str] = None):
        with self._lock:
            fqids_to_remove = [fqid for fqid in self._fqid_map if
                               fqid.startswith(prefix) and not (exclude_prefix and fqid.startswith(exclude_prefix))]
            if fqids_to_remove:
                logger.info(f"正在移除 {len(fqids_to_remove)} 个服务...")
                for fqid in fqids_to_remove:
                    definition = self._fqid_map.pop(fqid, None)
                    self._instances.pop(fqid, None)
                    if definition and definition.alias in self._short_name_map and self._short_name_map[
                        definition.alias] == fqid:
                        self._short_name_map.pop(definition.alias, None)
                    logger.debug(f"服务 '{fqid}' 已被移除。")


service_registry = ServiceRegistry()


def register_service(alias: str, public: bool = False):
    if not alias or not isinstance(alias, str): raise TypeError("服务别名(alias)必须是一个非空字符串。")

    def decorator(cls: Type) -> Type:
        setattr(cls, '_aura_service_meta', {'alias': alias, 'public': public})
        return cls

    return decorator


class HookManager:
    """
    【Async Refactor】事件钩子管理器，支持同步和异步钩子。
    """

    def __init__(self):
        self._hooks: Dict[str, List[Callable]] = defaultdict(list)

    def register(self, hook_name: str, func: Callable):
        logger.debug(f"注册钩子 '{hook_name}' -> {func.__module__}.{func.__name__}")
        self._hooks[hook_name].append(func)

    async def trigger(self, hook_name: str, *args, **kwargs):
        if hook_name not in self._hooks:
            return
        logger.trace(f"触发钩子: '{hook_name}'")

        tasks = [self._execute_hook(func, *args, **kwargs) for func in self._hooks[hook_name]]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_hook(self, func: Callable, *args, **kwargs):
        try:
            if asyncio.iscoroutinefunction(func):
                await func(*args, **kwargs)
            else:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: func(*args, **kwargs))
        except Exception as e:
            logger.error(f"执行钩子回调函数 '{func.__module__}.{func.__name__}' 时发生错误: {e}", exc_info=True)

    def clear(self):
        self._hooks.clear()
        logger.info("钩子管理器已清空。")


hook_manager = HookManager()


def register_hook(name: str):
    def decorator(func: Callable) -> Callable:
        setattr(func, '_aura_hook_name', name)
        return func

    return decorator

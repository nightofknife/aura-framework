# -*- coding: utf-8 -*-
"""Aura 框架的公共 API 定义模块。

此模块定义了用于创建和注册 Aura 框架核心组件的装饰器和注册表类。
开发者通过使用这些 API，可以将自己的代码集成到 Aura 的生态系统中。

核心组件:
- **Action**: 一个可执行的操作单元，是构成任务的基本步骤。
  使用 `@register_action` 装饰器来定义。
- **Service**: 一个可注入的、有状态的后台服务，为 Action 提供共享功能或资源。
  使用 `@register_service` 装饰器来定义，并使用 `@requires_services` 来注入。
- **Hook**: 一个在框架生命周期特定点触发的回调。
  使用 `@register_hook` 装饰器来定义。

全局注册表实例:
- `ACTION_REGISTRY`: `ActionRegistry` 的全局单例，存储所有已定义的 Action。
- `service_registry`: `ServiceRegistry` 的全局单例，管理所有 Service 的定义和实例化。
- `hook_manager`: `HookManager` 的全局单例，管理所有已注册的 Hook。
"""
import asyncio
import inspect
import textwrap
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Any, Dict, List, Optional, Type

from packages.aura_core.inheritance_proxy import InheritanceProxy
from packages.aura_core.logger import logger
from packages.aura_core.plugin_definition import PluginDefinition


@dataclass
class ActionDefinition:
    """封装一个已定义 Action 的所有元数据。

    Attributes:
        func (Callable): Action 对应的原始 Python 函数。
        name (str): Action 的名称，在 Plan 中通过此名称调用。
        read_only (bool): 标记此 Action 是否为只读。只读 Action 不应修改系统状态。
        public (bool): 标记此 Action 是否为公开 API，可被外部系统调用。
        service_deps (Dict[str, str]): 此 Action 依赖的服务及其别名。
        plugin (PluginDefinition): 定义此 Action 的插件。
        is_async (bool): 标记此 Action 的函数是否为异步 (`async def`)。
    """
    func: Callable
    name: str
    read_only: bool
    public: bool
    service_deps: Dict[str, str]
    plugin: PluginDefinition
    is_async: bool = False


    @property
    def signature(self) -> inspect.Signature:
        """获取 Action 原始函数的签名。"""
        return inspect.signature(self.func)

    @property
    def docstring(self) -> str:
        """获取并格式化 Action 原始函数的文档字符串。"""
        doc = inspect.getdoc(self.func)
        return textwrap.dedent(doc).strip() if doc else "此行为没有提供文档说明。"

    @property
    def fqid(self) -> str:
        """获取此 Action 的完全限定ID (Fully Qualified ID)。"""
        return f"{self.plugin.canonical_id}/{self.name}"


class ActionRegistry:
    """管理所有 Action 定义的注册表。

    这是一个线程安全的类，用于注册、查询和移除 Action 定义。
    """
    def __init__(self):
        """初始化 ActionRegistry。"""
        self._actions: Dict[str, ActionDefinition] = {}

    def clear(self):
        """清空注册表中的所有 Action 定义。"""
        self._actions.clear()

    def register(self, action_def: ActionDefinition):
        """注册一个新的 Action 定义。

        如果存在同名 Action，将会覆盖并打印警告。

        Args:
            action_def: 要注册的 Action 定义对象。
        """
        if action_def.name in self._actions:
            existing_fqid = self._actions[action_def.name].fqid
            logger.warning(
                f"行为名称冲突！'{action_def.name}' (来自 {action_def.fqid}) 覆盖了之前的定义 (来自 {existing_fqid})。")
        self._actions[action_def.name] = action_def
        logger.debug(f"已定义行为: '{action_def.fqid}' (公开: {action_def.public}, 异步: {action_def.is_async})")

    def get_all_action_definitions(self) -> List[ActionDefinition]:
        """获取所有已注册的 Action 定义列表，按 FQID 排序。

        Returns:
            一个包含所有 ActionDefinition 对象的列表。
        """
        return sorted(list(self._actions.values()), key=lambda a: a.fqid)

    def remove_actions_by_plugin(self, plugin_id: str):
        """移除所有属于特定插件的 Action 定义。

        在插件卸载或重载时使用。

        Args:
            plugin_id (str): 插件的规范ID (canonical_id)。
        """
        actions_to_remove = [name for name, action_def in self._actions.items() if
                             action_def.plugin.canonical_id == plugin_id]
        if actions_to_remove:
            logger.info(f"正在为插件 '{plugin_id}' 移除 {len(actions_to_remove)} 个 Action...")
            for name in actions_to_remove:
                del self._actions[name]

    def __len__(self) -> int:
        """返回已注册的 Action 数量。"""
        return len(self._actions)

    def get(self, name: str) -> Optional[ActionDefinition]:
        """根据名称获取一个 Action 定义。

        Args:
            name: Action 的名称。

        Returns:
            对应的 ActionDefinition 对象，如果不存在则返回 None。
        """
        return self._actions.get(name)


ACTION_REGISTRY = ActionRegistry()


def register_action(name: str, read_only: bool = False, public: bool = False):
    """装饰器工厂，用于将一个函数注册为 Aura Action。

    Args:
        name (str): Action 的唯一名称，在 Plan 中使用此名称调用。
        read_only (bool): 标记 Action 是否为只读。
        public (bool): 标记 Action 是否为公开 API。

    Returns:
        一个装饰器，可用于修饰函数。
    """
    def decorator(func: Callable) -> Callable:
        meta = {'name': name, 'read_only': read_only, 'public': public,
                'services': getattr(func, '_service_dependencies', {})}
        setattr(func, '_aura_action_meta', meta)
        return func

    return decorator


def requires_services(*args: str, **kwargs: str):
    """装饰器工厂，用于声明 Action 对一个或多个 Service 的依赖。

    被此装饰器修饰的函数在执行时，Aura 会自动将声明的 Service 实例
    注入到函数的对应参数中。

    用法:
        @requires_services('config', 'database')
        def my_action(config, database): ...

        @requires_services(cfg='config')
        def other_action(cfg): ...

    Args:
        *args: 服务别名列表。参数名将与服务别名相同。
        **kwargs: 服务别名到参数名的映射。

    Returns:
        一个装饰器，可用于修饰函数。
    """
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


@dataclass
class ServiceDefinition:
    """封装一个已定义 Service 的所有元数据。

    Attributes:
        alias (str): 服务的短别名，用于依赖注入和覆盖。
        fqid (str): 服务的完全限定ID。
        service_class (Type): 实现该服务的 Python 类。
        plugin (Optional[PluginDefinition]): 定义此服务的插件。核心服务此项为 None。
        public (bool): 标记此服务是否为公开，可被其他插件扩展或覆盖。
        instance (Any): 服务被实例化后的单例对象。
        status (str): 服务的当前状态 (e.g., "defined", "resolving", "resolved", "failed")。
        is_extension (bool): 标记此服务是否是另一个服务的扩展。
        parent_fqid (Optional[str]): 如果是扩展，则为父服务的 FQID。
    """
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
    """管理所有 Service 定义和实例的注册表。

    这是一个线程安全的类，负责处理服务的注册、依赖解析、实例化、
    继承（扩展）和覆盖逻辑。
    """
    def __init__(self):
        """初始化 ServiceRegistry。"""
        self._fqid_map: Dict[str, ServiceDefinition] = {}
        self._short_name_map: Dict[str, str] = {}
        self._instances: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def is_registered(self, fqid: str) -> bool:
        """检查一个服务 FQID 是否已被注册。

        Args:
            fqid: 要检查的服务的完全限定ID。

        Returns:
            如果已注册则返回 True，否则返回 False。
        """
        with self._lock:
            return fqid in self._fqid_map

    def clear(self):
        """清空注册表中的所有服务定义和实例。"""
        with self._lock:
            self._fqid_map.clear()
            self._short_name_map.clear()
            self._instances.clear()
            logger.info("服务注册中心已清空。")

    def register(self, definition: ServiceDefinition):
        """注册一个新的服务定义。

        此方法处理复杂的注册逻辑，包括名称冲突检查、扩展和覆盖。

        Args:
            definition: 要注册的服务定义对象。
        """
        with self._lock:
            if definition.fqid in self._fqid_map:
                logger.warning(f"服务 FQID '{definition.fqid}' 已被注册，跳过此次注册。")
                return

            short_name = definition.alias
            if short_name in self._short_name_map:
                existing_fqid = self._short_name_map[short_name]
                existing_definition = self._fqid_map[existing_fqid]

                if existing_definition.plugin is None:
                    logger.info(f"服务覆盖: '{definition.fqid}' 正在用插件实现覆盖核心服务 '{existing_fqid}'。")
                    self._short_name_map[short_name] = definition.fqid
                    del self._fqid_map[existing_fqid]

                else:
                    existing_plugin_id = existing_definition.plugin.canonical_id
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
        """直接注册一个已经实例化好的服务对象。

        通常用于在框架启动时注册核心服务。

        Args:
            alias: 服务的别名。
            instance: 已经实例化好的服务对象。
            fqid: (可选) 为此实例指定的 FQID。
            public: (可选) 是否将此服务标记为公开。
        """
        with self._lock:
            target_fqid = fqid or f"core/{alias}"
            if alias in self._short_name_map:
                existing_fqid = self._short_name_map[alias]
                if existing_fqid in self._fqid_map:
                    del self._fqid_map[existing_fqid]
                logger.info(f"核心服务实例 '{target_fqid}' 正在覆盖别名 '{alias}' (之前指向 '{existing_fqid}')。")

            definition = ServiceDefinition(alias=alias, fqid=target_fqid, service_class=type(instance), plugin=None,
                                           public=public, instance=instance, status="resolved")
            self._fqid_map[target_fqid] = definition
            self._short_name_map[alias] = target_fqid
            self._instances[target_fqid] = instance
            logger.info(f"核心服务实例 '{target_fqid}' 已通过别名 '{alias}' 直接注册。")

    def get_service_instance(self, service_id: str, resolution_chain: Optional[List[str]] = None) -> Any:
        """获取一个服务的单例。如果尚未实例化，则会触发实例化过程。

        此方法是依赖注入的核心。它会处理循环依赖检测。

        Args:
            service_id: 服务的别名或 FQID。
            resolution_chain: (内部使用) 用于检测循环依赖的解析链。

        Returns:
            请求的服务的单例对象。

        Raises:
            NameError: 如果找不到请求的服务。
            RecursionError: 如果检测到循环依赖。
        """
        with self._lock:
            is_fqid_request = '/' in service_id
            target_fqid = service_id if is_fqid_request else self._short_name_map.get(service_id)
            if not target_fqid: raise NameError(f"找不到别名为 '{service_id}' 的服务。")
            if target_fqid in self._instances: return self._instances[target_fqid]
            return self._instantiate_service(target_fqid, resolution_chain or [])

    def _instantiate_service(self, fqid: str, resolution_chain: List[str]) -> Any:
        """(私有) 实例化一个服务的内部逻辑。"""
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
        """(私有) 解析服务构造函数所需的依赖。"""
        dependencies = {}
        init_signature = inspect.signature(definition.service_class.__init__)
        type_to_fqid_map = {sd.service_class: sd.fqid for sd in self._fqid_map.values()}
        for param_name, param in init_signature.parameters.items():
            if param_name in ['self', 'parent_service']: continue
            dependency_fqid = None
            if param.annotation is not inspect.Parameter.empty and param.annotation in type_to_fqid_map: dependency_fqid = \
                type_to_fqid_map[param.annotation]
            if dependency_fqid is None:
                dependency_alias = param_name
                dependency_fqid = self._short_name_map.get(dependency_alias)
                if not dependency_fqid: raise NameError(
                    f"为 '{definition.fqid}' 自动解析依赖 '{param_name}' 失败：无法通过类型注解或参数名找到对应的服务。")
            dependencies[param_name] = self.get_service_instance(dependency_fqid, resolution_chain)
        return dependencies

    def get_all_service_definitions(self) -> List[ServiceDefinition]:
        """获取所有已注册的服务定义列表，按 FQID 排序。

        Returns:
            一个包含所有 ServiceDefinition 对象的列表。
        """
        with self._lock: return sorted(list(self._fqid_map.values()), key=lambda s: s.fqid)

    def get_all_services(self) -> Dict[str, Any]:
        """返回所有已实例化的服务的字典（FQID -> 实例）。

        返回的是一个副本，以确保内部状态的线程安全。

        Returns:
            一个包含所有已实例化服务的字典。
        """
        with self._lock:
            return dict(self._instances)


    def remove_services_by_prefix(self, prefix: str = "", exclude_prefix: Optional[str] = None):
        """根据 FQID 前缀移除服务。

        Args:
            prefix (str): 要移除的服务 FQID 的前缀。
            exclude_prefix (Optional[str]): (可选) 不应被移除的服务 FQID 的前缀。
        """
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
    """装饰器工厂，用于将一个类注册为 Aura Service。

    Args:
        alias (str): 服务的唯一别名，用于依赖注入和覆盖。
        public (bool): 标记服务是否为公开，允许其他插件扩展或覆盖。

    Returns:
        一个装饰器，可用于修饰类。
    """
    if not alias or not isinstance(alias, str): raise TypeError("服务别名(alias)必须是一个非空字符串。")

    def decorator(cls: Type) -> Type:
        setattr(cls, '_aura_service_meta', {'alias': alias, 'public': public})
        return cls

    return decorator


class HookManager:
    """管理框架中所有钩子（Hook）的注册与触发。

    这是一个异步的、线程安全的类，用于处理框架生命周期事件。
    """
    def __init__(self):
        """初始化 HookManager。"""
        self._hooks: Dict[str, List[Callable]] = defaultdict(list)

    def register(self, hook_name: str, func: Callable):
        """注册一个钩子回调函数。

        Args:
            hook_name: 钩子的名称。
            func: 要注册的回调函数。
        """
        logger.debug(f"注册钩子 '{hook_name}' -> {func.__module__}.{func.__name__}")
        self._hooks[hook_name].append(func)

    async def trigger(self, hook_name: str, *args, **kwargs):
        """异步地触发一个钩子，并执行所有已注册的回调函数。

        会并发执行所有回调，并忽略执行中的异常（仅记录日志）。

        Args:
            hook_name: 要触发的钩子的名称。
            *args: 传递给回调函数的位置参数。
            **kwargs: 传递给回调函数的关键字参数。
        """
        if hook_name not in self._hooks: return
        logger.trace(f"触发钩子: '{hook_name}'")
        tasks = [self._execute_hook(func, *args, **kwargs) for func in self._hooks[hook_name]]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_hook(self, func: Callable, *args, **kwargs):
        """(私有) 安全地执行单个钩子回调函数。"""
        try:
            if asyncio.iscoroutinefunction(func):
                await func(*args, **kwargs)
            else:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: func(*args, **kwargs))
        except Exception as e:
            logger.error(f"执行钩子回调函数 '{func.__module__}.{func.__name__}' 时发生错误: {e}", exc_info=True)

    def clear(self):
        """清空管理器中的所有钩子。"""
        self._hooks.clear()
        logger.info("钩子管理器已清空。")


hook_manager = HookManager()


def register_hook(name: str):
    """装饰器工厂，用于将一个函数注册为 Aura Hook。

    Args:
        name (str): 钩子的名称。

    Returns:
        一个装饰器，可用于修饰函数。
    """
    def decorator(func: Callable) -> Callable:
        setattr(func, '_aura_hook_name', name)
        return func

    return decorator

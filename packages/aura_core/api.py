# packages/aura_core/api.py [FIXED - Ultimate Null Check]
"""
定义了 Aura 框架的核心 API，包括所有全局注册表和用于扩展框架的装饰器。

该模块是框架插件化和解耦的核心。它提供了以下关键组件：

1.  **全局注册表 (Singletons)**:
    - `ACTION_REGISTRY`: `ActionRegistry` 的实例，用于存储所有已注册的 `Action` 定义。
    - `service_registry`: `ServiceRegistry` 的实例，负责管理所有 `Service` 的生命周期，包括定义、实例化和依赖注入。
    - `hook_manager`: `HookManager` 的实例，提供一个简单的事件发布/订阅机制，用于框架的生命周期钩子。

2.  **数据类定义**:
    - `ActionDefinition`: 结构化地表示一个已注册的 `Action`。
    - `ServiceDefinition`: 结构化地表示一个已注册的 `Service`。

3.  **装饰器**:
    - `@register_action`: 将一个函数标记为可由 `ExecutionEngine` 调用的 `Action`。
    - `@requires_services`: 为 `Action` 声明其服务依赖。
    - `@register_service`: 将一个类标记为可被注入的 `Service`。
    - `@register_hook`: 将一个函数注册为特定钩子事件的回调。

这些工具共同构成了一个统一的接口，使得插件能够以标准化的方式向 Aura 框架贡献功能。
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
    """
    一个数据类，用于封装关于单个已注册 Action 的所有信息。

    Attributes:
        func (Callable): Action 对应的原始 Python 函数。
        name (str): Action 的唯一名称，在任务定义中通过此名称调用。
        read_only (bool): 标记该 Action 是否会修改系统状态。
        public (bool): 标记该 Action 是否可通过外部 API 调用。
        service_deps (Dict[str, str]): 该 Action 的服务依赖，格式为 `{'参数名': '服务 FQID'}`。
        plugin (PluginDefinition): 定义此 Action 的插件。
        is_async (bool): 标记该 Action 是否为异步函数 (`async def`)。
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
        """返回 Action 函数的签名对象。"""
        return inspect.signature(self.func)

    @property
    def docstring(self) -> str:
        """返回 Action 函数的文档字符串，经过格式化处理。"""
        doc = inspect.getdoc(self.func)
        return textwrap.dedent(doc).strip() if doc else "此行为没有提供文档说明。"

    @property
    def fqid(self) -> str:
        """返回 Action 的完全限定ID (Fully Qualified ID)，格式为 'plugin_id/action_name'。"""
        return f"{self.plugin.canonical_id}/{self.name}"


class ActionRegistry:
    """
    全局注册表，用于存储和管理所有的 ActionDefinition。

    这是一个单例模式的实现（通过模块级实例 `ACTION_REGISTRY`），确保整个应用中只有一个 Action 注册中心。
    """
    def __init__(self):
        """初始化一个空的 Action 注册表。"""
        self._actions: Dict[str, ActionDefinition] = {}

    def clear(self):
        """清空所有已注册的 Action，主要用于测试。"""
        self._actions.clear()

    def register(self, action_def: ActionDefinition):
        """
        注册一个新的 Action。

        如果存在同名的 Action，将发出警告并覆盖旧的定义。

        Args:
            action_def (ActionDefinition): 要注册的 Action 的定义对象。
        """
        if action_def.name in self._actions:
            existing_fqid = self._actions[action_def.name].fqid
            logger.warning(
                f"行为名称冲突！'{action_def.name}' (来自 {action_def.fqid}) 覆盖了之前的定义 (来自 {existing_fqid})。")
        self._actions[action_def.name] = action_def
        logger.debug(f"已定义行为: '{action_def.fqid}' (公开: {action_def.public}, 异步: {action_def.is_async})")

    def get_all_action_definitions(self) -> List[ActionDefinition]:
        """返回所有已注册 Action 的定义列表，按 FQID 排序。"""
        return sorted(list(self._actions.values()), key=lambda a: a.fqid)

    def __len__(self) -> int:
        """返回已注册 Action 的数量。"""
        return len(self._actions)

    def get(self, name: str) -> Optional[ActionDefinition]:
        """
        通过名称查找并返回一个 Action 的定义。

        Args:
            name (str): Action 的名称。

        Returns:
            Optional[ActionDefinition]: 如果找到则返回 Action 定义对象，否则返回 None。
        """
        return self._actions.get(name)


ACTION_REGISTRY = ActionRegistry()
"""全局 Action 注册表实例。"""


def register_action(name: str, read_only: bool = False, public: bool = False):
    """
    一个装饰器，用于将一个函数注册为 Aura Action。

    示例:
        @register_action("my_plugin.do_something", public=True)
        @requires_services(config_service="core/config")
        def do_something(config_service: ConfigService):
            ...

    Args:
        name (str): Action 的唯一名称。
        read_only (bool): 指示该 Action 是否修改状态。
        public (bool): 指示该 Action 是否能通过外部 API 访问。

    Returns:
        Callable: 返回一个装饰器函数。
    """
    def decorator(func: Callable) -> Callable:
        meta = {'name': name, 'read_only': read_only, 'public': public,
                'services': getattr(func, '_service_dependencies', {})}
        setattr(func, '_aura_action_meta', meta)
        return func

    return decorator


def requires_services(*args: str, **kwargs: str):
    """
    一个装饰器，用于为 Action 声明其服务依赖。

    依赖的服务将在 Action 执行时由 `ActionInjector` 自动注入。

    示例:
        # 通过关键字参数为依赖指定别名
        @requires_services(my_config="core/config", db="my_plugin/database")
        def my_action(my_config, db): ...

        # 通过位置参数使用默认别名（服务 FQID 的最后一部分）
        @requires_services("core/config", "my_plugin/database")
        def my_action(config, database): ...

    Args:
        *args (str): 服务的 FQID 列表，将使用默认别名。
        **kwargs (str): 服务依赖，格式为 `参数名=服务FQID`。

    Returns:
        Callable: 返回一个装饰器函数。

    Raises:
        NameError: 如果在使用 `*args` 时出现别名冲突。
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
    """
    一个数据类，用于封装关于单个已注册 Service 的所有信息。

    Attributes:
        alias (str): 服务的短别名，用于在注册表和依赖注入中快速查找。
        fqid (str): 服务的完全限定ID，格式为 `plugin_id/service_alias`。
        service_class (Type): 实现该服务的 Python 类。
        plugin (Optional[PluginDefinition]): 定义此服务的插件，如果是核心服务则为 None。
        public (bool): 标记该服务是否可被其他插件访问。
        instance (Any): 服务被实例化后的单例对象。
        status (str): 服务的当前状态 ("defined", "resolving", "resolved", "failed")。
        is_extension (bool): 标记该服务是否继承自另一个服务。
        parent_fqid (Optional[str]): 如果是继承服务，则为父服务的 FQID。
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
    """
    全局服务注册表，负责管理所有服务的生命周期。

    这是一个线程安全的类，处理服务的定义、依赖解析、实例化、继承和覆盖。
    它使用单例模式（通过模块级实例 `service_registry`）来确保全局唯一性。
    """
    def __init__(self):
        """初始化服务注册表，包括内部映射和线程锁。"""
        self._fqid_map: Dict[str, ServiceDefinition] = {}
        self._short_name_map: Dict[str, str] = {}
        self._instances: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def is_registered(self, fqid: str) -> bool:
        """检查具有给定 FQID 的服务是否已被注册。"""
        with self._lock:
            return fqid in self._fqid_map

    def clear(self):
        """清空所有已注册的服务定义和实例，主要用于测试。"""
        with self._lock:
            self._fqid_map.clear()
            self._short_name_map.clear()
            self._instances.clear()
            logger.info("服务注册中心已清空。")

    def register(self, definition: ServiceDefinition):
        """
        注册一个新的服务定义。

        这个方法包含了处理服务覆盖、继承和冲突的核心逻辑。

        Args:
            definition (ServiceDefinition): 要注册的服务的定义对象。

        Raises:
            RuntimeError: 如果插件试图定义一个已存在的服务而没有明确声明覆盖或继承，
                          或者同时声明了覆盖和继承。
        """
        with self._lock:
            if definition.fqid in self._fqid_map:
                # 在构建期间，由于模块可能被多次导入，轻微的重复注册是可以接受的，但要发出警告
                logger.warning(f"服务 FQID '{definition.fqid}' 已被注册，跳过此次注册。")
                return

            short_name = definition.alias
            if short_name in self._short_name_map:
                existing_fqid = self._short_name_map[short_name]
                existing_definition = self._fqid_map[existing_fqid]

                # 【【【核心修复】】】
                # 检查已存在的服务是否是无插件的 "核心服务"。
                if existing_definition.plugin is None:
                    # 如果是，这通常意味着构建器正在注册一个由插件提供的、将要覆盖核心实例的服务。
                    # 这是一个合法的操作（例如，aura_base 提供了 config 服务的最终实现）。
                    # 我们允许这次注册，并用新的、带插件信息的定义覆盖旧的。
                    logger.info(f"服务覆盖: '{definition.fqid}' 正在用插件实现覆盖核心服务 '{existing_fqid}'。")
                    self._short_name_map[short_name] = definition.fqid
                    # 删除旧的无插件定义，稍后会被新的定义取代
                    del self._fqid_map[existing_fqid]

                else:
                    # 如果已存在的服务也是来自一个插件，则执行正常的 extend/override 检查。
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
        """
        直接注册一个已经实例化的对象作为服务。

        这对于集成外部库或注册框架启动时就需要准备好的核心服务非常有用。

        Args:
            alias (str): 服务的别名。
            instance (Any): 要注册的服务实例。
            fqid (Optional[str]): 服务的 FQID，如果未提供则默认为 `core/{alias}`。
            public (bool): 该服务实例是否对其他插件可见。
        """
        with self._lock:
            target_fqid = fqid or f"core/{alias}"
            # 【修复】在注册实例时，如果别名已存在，也应该覆盖而不是只警告
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
        """
        获取一个服务的实例。

        如果服务尚未实例化，此方法将触发实例化过程。

        Args:
            service_id (str): 服务的别名或 FQID。
            resolution_chain (Optional[List[str]]): 用于检测循环依赖的解析链。

        Returns:
            Any: 请求的服务的单例实例。

        Raises:
            NameError: 如果找不到指定的服务。
        """
        with self._lock:
            is_fqid_request = '/' in service_id
            target_fqid = service_id if is_fqid_request else self._short_name_map.get(service_id)
            if not target_fqid: raise NameError(f"找不到别名为 '{service_id}' 的服务。")
            if target_fqid in self._instances: return self._instances[target_fqid]
            return self._instantiate_service(target_fqid, resolution_chain or [])

    def _instantiate_service(self, fqid: str, resolution_chain: List[str]) -> Any:
        """
        实例化一个服务及其所有依赖项（私有方法）。

        Args:
            fqid (str): 要实例化的服务的 FQID。
            resolution_chain (List[str]): 当前的解析链，用于检测循环依赖。

        Returns:
            Any: 新创建的服务实例。

        Raises:
            RecursionError: 如果检测到循环依赖。
            RuntimeError: 如果服务实例化失败或存在并发问题。
            NameError: 如果找不到服务定义。
            TypeError: 如果继承服务的构造函数缺少 `parent_service` 参数。
        """
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
        """
        解析服务构造函数的所有依赖项（私有方法）。

        它通过检查 `__init__` 方法的参数名和类型注解来自动推断依赖。

        Args:
            definition (ServiceDefinition): 正在解析其依赖的服务定义。
            resolution_chain (List[str]): 当前的解析链。

        Returns:
            Dict[str, Any]: 一个包含已实例化依赖的字典，可用于构造函数调用。

        Raises:
            NameError: 如果无法通过参数名或类型注解找到某个依赖。
        """
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
        """返回所有服务定义的列表，按 FQID 排序。"""
        with self._lock: return sorted(list(self._fqid_map.values()), key=lambda s: s.fqid)

    def get_all_services(self) -> Dict[str, Any]:
        """
        返回所有已实例化的服务的字典。

        返回的是一个副本，以确保内部状态的线程安全。

        Returns:
            Dict[str, Any]: 一个从服务 FQID 映射到服务实例的字典。
        """
        with self._lock:
            # 返回 self._instances 的一个浅拷贝
            return dict(self._instances)


    def remove_services_by_prefix(self, prefix: str = "", exclude_prefix: Optional[str] = None):
        """
        根据 FQID 前缀移除一批服务。

        这在动态卸载插件时非常有用。

        Args:
            prefix (str): 需要移除的服务的 FQID 前缀。
            exclude_prefix (Optional[str]): 一个可选的前缀，用于排除某些服务不被移除。
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
"""全局服务注册表实例。"""


def register_service(alias: str, public: bool = False):
    """
    一个装饰器，用于将一个类注册为 Aura Service。

    示例:
        @register_service("my_config", public=True)
        class MyConfigService:
            ...

    Args:
        alias (str): 服务的唯一别名。
        public (bool): 指示该服务是否能被其他插件注入。

    Returns:
        Callable: 返回一个装饰器函数。

    Raises:
        TypeError: 如果别名不是一个非空字符串。
    """
    if not alias or not isinstance(alias, str): raise TypeError("服务别名(alias)必须是一个非空字符串。")

    def decorator(cls: Type) -> Type:
        setattr(cls, '_aura_service_meta', {'alias': alias, 'public': public})
        return cls

    return decorator


class HookManager:
    """
    一个简单的事件发布/订阅管理器。

    它允许在框架的关键生命周期点触发已注册的回调函数（钩子）。
    这是一个单例模式的实现（通过模块级实例 `hook_manager`）。
    """
    def __init__(self):
        """初始化一个空的钩子管理器。"""
        self._hooks: Dict[str, List[Callable]] = defaultdict(list)

    def register(self, hook_name: str, func: Callable):
        """
        注册一个回调函数到一个指定的钩子事件。

        Args:
            hook_name (str): 钩子的名称。
            func (Callable): 当钩子被触发时要执行的回调函数。
        """
        logger.debug(f"注册钩子 '{hook_name}' -> {func.__module__}.{func.__name__}")
        self._hooks[hook_name].append(func)

    async def trigger(self, hook_name: str, *args, **kwargs):
        """
        触发一个钩子，异步执行所有已注册的回调函数。

        它会并发执行所有回调，并等待它们全部完成。
        同步的回调函数将在线程池中执行，以避免阻塞事件循环。

        Args:
            hook_name (str): 要触发的钩子的名称。
            *args: 传递给回调函数的位置参数。
            **kwargs: 传递给回调函数的关键字参数。
        """
        if hook_name not in self._hooks: return
        logger.trace(f"触发钩子: '{hook_name}'")
        tasks = [self._execute_hook(func, *args, **kwargs) for func in self._hooks[hook_name]]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_hook(self, func: Callable, *args, **kwargs):
        """
        安全地执行单个钩子回调（私有方法）。

        捕获并记录执行期间的任何异常。
        """
        try:
            if asyncio.iscoroutinefunction(func):
                await func(*args, **kwargs)
            else:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: func(*args, **kwargs))
        except Exception as e:
            logger.error(f"执行钩子回调函数 '{func.__module__}.{func.__name__}' 时发生错误: {e}", exc_info=True)

    def clear(self):
        """清空所有已注册的钩子，主要用于测试。"""
        self._hooks.clear()
        logger.info("钩子管理器已清空。")


hook_manager = HookManager()
"""全局钩子管理器实例。"""


def register_hook(name: str):
    """
    一个装饰器，用于将一个函数注册为钩子回调。

    示例:
        @register_hook("core.on_start")
        async def my_startup_logic():
            ...

    Args:
        name (str): 钩子的名称。

    Returns:
        Callable: 返回一个装饰器函数。
    """
    def decorator(func: Callable) -> Callable:
        setattr(func, '_aura_hook_name', name)
        return func

    return decorator

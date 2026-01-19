# -*- coding: utf-8 -*-
"""Aura 框架的注册表类。

此模块包含用于管理 Actions、Services 和 Hooks 的注册表类。
"""
import asyncio
import inspect
import threading
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

from .definitions import ActionDefinition, ServiceDefinition, HookResult
from ..utils.inheritance_proxy import InheritanceProxy
from packages.aura_core.observability.logging.core_logger import logger


class ActionRegistry:
    """管理所有 Action 定义的注册表。

    这是一个线程安全的类,用于注册、查询和移除 Action 定义。

    ✅ 修复：支持FQID索引,防止不同包的同名Action冲突。
    """
    def __init__(self):
        """初始化 ActionRegistry。"""
        self._actions_by_fqid: Dict[str, ActionDefinition] = {}  # FQID -> ActionDefinition
        self._actions_by_name: Dict[str, ActionDefinition] = {}  # 简单名称 -> ActionDefinition(向后兼容)
        self._lock = threading.RLock()  # ✅ 添加线程锁

    def clear(self):
        """清空注册表中的所有 Action 定义。"""
        with self._lock:
            self._actions_by_fqid.clear()
            self._actions_by_name.clear()

    def register(self, action_def: ActionDefinition):
        """注册一个新的 Action 定义。

        ✅ 修复：使用FQID作为主键,禁止包内同名Action。

        Args:
            action_def: 要注册的 Action 定义对象。

        Raises:
            RuntimeError: 如果FQID已存在(同一包内定义了同名Action)。
        """
        with self._lock:
            # ✅ 检查FQID是否已存在(严格禁止包内同名)
            if action_def.fqid in self._actions_by_fqid:
                existing = self._actions_by_fqid[action_def.fqid]
                raise RuntimeError(
                    f"Action FQID冲突！'{action_def.fqid}' 已被注册。\n"
                    f"同一个包不能定义多个同名Action。\n"
                    f"已存在: {existing.func.__module__}.{existing.func.__name__}\n"
                    f"尝试注册: {action_def.func.__module__}.{action_def.func.__name__}"
                )

            # ✅ 注册到FQID索引
            self._actions_by_fqid[action_def.fqid] = action_def

            # ✅ 注册到简单名称索引(向后兼容,但会警告冲突)
            if action_def.name in self._actions_by_name:
                existing_fqid = self._actions_by_name[action_def.name].fqid
                logger.warning(
                    f"Action简单名称冲突！'{action_def.name}' 已被 '{existing_fqid}' 注册。\n"
                    f"新注册的 '{action_def.fqid}' 将覆盖简单名称索引。\n"
                    f"建议：调用外部包的Action时请使用完整FQID: '{action_def.fqid}'"
                )

            self._actions_by_name[action_def.name] = action_def

            logger.debug(
                f"已注册Action: '{action_def.fqid}' (公开: {action_def.public}, 异步: {action_def.is_async})"
            )

    def get_all_action_definitions(self) -> List[ActionDefinition]:
        """获取所有已注册的 Action 定义列表,按 FQID 排序。

        Returns:
            一个包含所有 ActionDefinition 对象的列表。
        """
        with self._lock:
            return sorted(list(self._actions_by_fqid.values()), key=lambda a: a.fqid)

    def remove_actions_by_plugin(self, plugin_id: str):
        """移除所有属于特定插件的 Action 定义。

        在插件卸载或重载时使用。

        Args:
            plugin_id (str): 插件的规范ID (canonical_id)。
        """
        with self._lock:
            # ✅ 遍历FQID索引
            fqids_to_remove = []
            for fqid, action_def in self._actions_by_fqid.items():
                # ✅ 统一使用新系统获取plugin_id
                current_plugin_id = action_def.plugin.package.canonical_id

                if current_plugin_id == plugin_id:
                    fqids_to_remove.append(fqid)

            if fqids_to_remove:
                logger.info(f"正在为插件 '{plugin_id}' 移除 {len(fqids_to_remove)} 个 Action...")
                for fqid in fqids_to_remove:
                    action_def = self._actions_by_fqid.pop(fqid)
                    # 同时从简单名称索引中移除
                    if self._actions_by_name.get(action_def.name) == action_def:
                        del self._actions_by_name[action_def.name]

    def __len__(self) -> int:
        """返回已注册的 Action 数量。"""
        with self._lock:
            return len(self._actions_by_fqid)

    def get(self, name_or_fqid: str) -> Optional[ActionDefinition]:
        """根据名称或FQID获取一个 Action 定义。

        ✅ 修复：优先使用FQID查找,支持完整的命名空间隔离。

        Args:
            name_or_fqid: Action 的简单名称或完整FQID。

        Returns:
            对应的 ActionDefinition 对象,如果不存在则返回 None。
        """
        with self._lock:
            # ✅ 优先查找FQID(包含'/'表示是FQID)
            if '/' in name_or_fqid:
                return self._actions_by_fqid.get(name_or_fqid)

            # 再查找简单名称(向后兼容)
            return self._actions_by_name.get(name_or_fqid)


class ServiceRegistry:
    """管理所有 Service 定义和实例的注册表。

    这是一个线程安全的类,负责处理服务的注册、依赖解析、实例化、
    继承(扩展)和覆盖逻辑。
    """
    def __init__(self):
        """初始化 ServiceRegistry。"""
        self._fqid_map: Dict[str, ServiceDefinition] = {}
        self._short_name_map: Dict[str, str] = {}
        self._instances: Dict[str, Any] = {}
        self._lock = threading.RLock()
        # ✅ 新增：正在注册的服务集合,用于防止并发注册同一服务
        self._registering: set = set()

    def is_registered(self, fqid: str) -> bool:
        """检查一个服务 FQID 是否已被注册。

        Args:
            fqid: 要检查的服务的完全限定ID。

        Returns:
            如果已注册则返回 True,否则返回 False。
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

        此方法处理复杂的注册逻辑,包括名称冲突检查、扩展和覆盖。

        ✅ 修复：添加并发注册保护,确保同一服务不会被多线程同时注册。

        Args:
            definition: 要注册的服务定义对象。
        """
        with self._lock:
            # ✅ 防止并发注册同一服务
            if definition.fqid in self._registering:
                logger.warning(f"服务 '{definition.fqid}' 正在被另一个线程注册,等待完成...")
                # 等待其他线程完成注册(最多等待5秒)
                import time
                for _ in range(50):
                    time.sleep(0.1)
                    if definition.fqid in self._fqid_map:
                        logger.info(f"服务 '{definition.fqid}' 已由其他线程完成注册")
                        return
                logger.error(f"等待服务 '{definition.fqid}' 注册超时")
                return

            # 检查FQID是否已存在
            if definition.fqid in self._fqid_map:
                existing = self._fqid_map[definition.fqid]
                # ✅ 如果alias也相同,才真正跳过
                if existing.alias == definition.alias:
                    logger.warning(f"服务 '{definition.fqid}' 已注册,跳过")
                    return
                else:
                    # ✅ alias不同,需要更新映射
                    logger.warning(
                        f"服务 '{definition.fqid}' 更新alias: {existing.alias} -> {definition.alias}"
                    )
                    # 移除旧的alias映射
                    if self._short_name_map.get(existing.alias) == definition.fqid:
                        del self._short_name_map[existing.alias]

            # ✅ 标记正在注册
            self._registering.add(definition.fqid)

            try:
                short_name = definition.alias
                if short_name in self._short_name_map:
                    existing_fqid = self._short_name_map[short_name]
                    existing_definition = self._fqid_map[existing_fqid]

                    if existing_definition.plugin is None:
                        logger.info(f"服务覆盖: '{definition.fqid}' 正在用插件实现覆盖核心服务 '{existing_fqid}'。")
                        self._short_name_map[short_name] = definition.fqid
                        del self._fqid_map[existing_fqid]

                    else:
                        # ✅ 获取 canonical_id(统一使用新系统)
                        existing_plugin_id = existing_definition.plugin.package.canonical_id

                        # ✅ 检查extends(新manifest系统)
                        is_extending = any(
                            ext.service == short_name and ext.from_plugin == existing_plugin_id
                            for ext in definition.plugin.extends
                        )

                        # ✅ 检查overrides(新manifest系统)
                        is_overriding = existing_fqid in definition.plugin.overrides

                        if is_extending and is_overriding:
                            raise RuntimeError(
                                f"插件 '{definition.plugin}' 不能同时 extend 和 override 同一个服务 '{short_name}'。"
                            )
                        if is_extending:
                            logger.info(f"服务继承: '{definition.fqid}' 正在扩展 '{existing_fqid}'。")
                            definition.is_extension = True
                            definition.parent_fqid = existing_fqid
                            self._short_name_map[short_name] = definition.fqid
                        elif is_overriding:
                            logger.warning(f"服务覆盖: '{definition.fqid}' 正在覆盖 '{existing_fqid}'。")
                            self._short_name_map[short_name] = definition.fqid
                        else:
                            # ✅ 修复：获取manifest路径时兼容新系统
                            if hasattr(definition.plugin, 'path'):
                                manifest_path = definition.plugin.path / 'manifest.yaml'
                            else:
                                manifest_path = 'manifest.yaml'

                            raise RuntimeError(
                                f"服务名称冲突！插件 '{definition.plugin}' 尝试定义服务 '{short_name}',"
                                f"但该名称已被 '{existing_fqid}' 使用。\n"
                                f"如果你的意图是扩展或覆盖,请在 '{manifest_path}' 中使用 'extends' 或 'overrides' 字段明确声明。"
                            )
                else:
                    self._short_name_map[short_name] = definition.fqid

                self._fqid_map[definition.fqid] = definition
                logger.debug(f"已定义服务: '{definition.fqid}' (别名: '{short_name}', 公开: {definition.public})")

            finally:
                # ✅ 注册完成,移除标记
                self._registering.discard(definition.fqid)

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
        """获取一个服务的单例。如果尚未实例化,则会触发实例化过程。

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
            result = self._instantiate_service(target_fqid, resolution_chain or [])
            return result

    def _instantiate_service(self, fqid: str, resolution_chain: List[str]) -> Any:
        """(私有) 实例化一个服务的内部逻辑。"""
        if fqid in resolution_chain: raise RecursionError(
            f"检测到服务间的循环依赖: {' -> '.join(resolution_chain)} -> {fqid}")
        resolution_chain.append(fqid)
        definition = self._fqid_map.get(fqid)
        if not definition: raise NameError(f"找不到请求的服务定义: '{fqid}'")
        if definition.status == "failed": raise RuntimeError(f"服务 '{fqid}' 在之前的尝试中加载失败。")
        if definition.status == "resolving": raise RuntimeError(f"服务 '{fqid}' 正在解析中,可能存在并发问题。")
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
        """获取所有已注册的服务定义列表,按 FQID 排序。

        Returns:
            一个包含所有 ServiceDefinition 对象的列表。
        """
        with self._lock: return sorted(list(self._fqid_map.values()), key=lambda s: s.fqid)

    def get_all_services(self) -> Dict[str, Any]:
        """返回所有已实例化的服务的字典(FQID -> 实例)。

        返回的是一个副本,以确保内部状态的线程安全。

        Returns:
            一个包含所有已实例化服务的字典。
        """
        with self._lock:
            return dict(self._instances)

    def validate_no_circular_dependencies(self):
        """验证所有服务依赖不存在循环。

        ✅ 新增：在所有服务注册完成后调用,提前检测循环依赖。

        Raises:
            ValueError: 如果检测到循环依赖。
        """
        with self._lock:
            from graphlib import TopologicalSorter

            logger.info("正在验证服务依赖关系...")

            # 构建依赖图
            graph = {}
            for fqid, definition in self._fqid_map.items():
                if definition.status == "resolved":
                    # 已实例化的服务跳过
                    continue

                deps = []

                # 解析构造函数依赖
                init_signature = inspect.signature(definition.service_class.__init__)
                type_to_fqid_map = {sd.service_class: sd.fqid for sd in self._fqid_map.values()}

                for param_name, param in init_signature.parameters.items():
                    if param_name in ['self', 'parent_service']:
                        continue

                    dependency_fqid = None

                    # 通过类型注解查找
                    if param.annotation is not inspect.Parameter.empty and param.annotation in type_to_fqid_map:
                        dependency_fqid = type_to_fqid_map[param.annotation]
                    # 通过参数名查找
                    elif param_name in self._short_name_map:
                        dependency_fqid = self._short_name_map[param_name]

                    if dependency_fqid:
                        deps.append(dependency_fqid)

                # 如果是扩展服务,也依赖父服务
                if definition.is_extension and definition.parent_fqid:
                    deps.append(definition.parent_fqid)

                graph[fqid] = deps

            # 使用拓扑排序检测循环
            try:
                sorter = TopologicalSorter(graph)
                sorter.prepare()
                logger.info(f"✓ 服务依赖验证通过,共 {len(graph)} 个服务")
            except Exception as e:
                # 尝试找出循环路径
                error_msg = f"检测到服务循环依赖: {e}\n\n依赖关系图:\n"
                for service_fqid, service_deps in graph.items():
                    if service_deps:
                        error_msg += f"  {service_fqid} -> {service_deps}\n"

                logger.error(error_msg)
                raise ValueError(error_msg)


    def remove_services_by_prefix(self, prefix: str = "", exclude_prefix: Optional[str] = None):
        """根据 FQID 前缀移除服务。

        ✅ 修复：调用服务的shutdown钩子,防止资源泄漏。

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
                    instance = self._instances.pop(fqid, None)

                    # ✅ 调用shutdown钩子
                    if instance and hasattr(instance, 'shutdown'):
                        try:
                            logger.debug(f"调用服务 '{fqid}' 的 shutdown 钩子")
                            instance.shutdown()
                        except Exception as e:
                            logger.error(f"服务 '{fqid}' shutdown失败: {e}", exc_info=True)

                    if definition and definition.alias in self._short_name_map and self._short_name_map[
                        definition.alias] == fqid:
                        self._short_name_map.pop(definition.alias, None)
                    logger.debug(f"服务 '{fqid}' 已被移除。")


class HookManager:
    """管理框架中所有钩子(Hook)的注册与触发。

    这是一个异步的、线程安全的类,用于处理框架生命周期事件。
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
        """异步地触发一个钩子,并执行所有已注册的回调函数。

        会并发执行所有回调,并忽略执行中的异常(仅记录日志)。

        Args:
            hook_name: 要触发的钩子的名称。
            *args: 传递给回调函数的位置参数。
            **kwargs: 传递给回调函数的关键字参数。
        """
        if hook_name not in self._hooks: return
        logger.trace(f"触发钩子: '{hook_name}'")
        tasks = [self._execute_hook(func, *args, **kwargs) for func in self._hooks[hook_name]]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def trigger_with_results(self, hook_name: str, *args,
                                   stop_on_false: bool = False,
                                   raise_on_error: bool = False,
                                   **kwargs) -> List[HookResult]:
        """触发钩子并收集结果,可选择在返回 False 或异常时中止。"""
        if hook_name not in self._hooks:
            return []
        results: List[HookResult] = []
        for func in self._hooks[hook_name]:
            try:
                result = await self._execute_hook_with_result(func, *args, **kwargs)
                results.append(HookResult(func=func, ok=True, result=result))
                if stop_on_false and result is False:
                    break
            except Exception as e:
                logger.error(
                    "执行钩子回调函数 '%s.%s' 时发生错误: %s",
                    func.__module__,
                    func.__name__,
                    e,
                    exc_info=True,
                )
                results.append(HookResult(func=func, ok=False, error=str(e)))
                if raise_on_error:
                    raise
        return results

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

    async def _execute_hook_with_result(self, func: Callable, *args, **kwargs) -> Any:
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    def clear(self):
        """清空管理器中的所有钩子。"""
        self._hooks.clear()
        logger.info("钩子管理器已清空。")


# 全局注册表实例
ACTION_REGISTRY = ActionRegistry()
service_registry = ServiceRegistry()
hook_manager = HookManager()

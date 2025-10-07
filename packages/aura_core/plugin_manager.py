"""
定义了 `PluginManager`，这是 Aura 框架中负责插件生命周期管理的核心组件。

`PluginManager` 负责在应用启动时执行一个三阶段的加载流程：
1.  **发现与解析**: 扫描指定的插件目录（`packages` 和 `plans`），查找
    所有 `plugin.yaml` 清单文件，并将它们解析成 `PluginDefinition` 对象。
2.  **依赖解析与排序**: 使用 `resolvelib` 库验证插件间的依赖关系，并利用
    `graphlib.TopologicalSorter` 计算出无环的、正确的加载顺序。
3.  **加载**: 按照计算出的顺序，逐一加载每个插件。加载过程包括注册服务
    （Services）、行为（Actions）和钩子（Hooks）。如果插件没有预编译的
    `api.yaml` 文件，它会先调用 `builder` 模块来生成一个。

它的核心职责是填充全局的服务和行为注册表，为框架的其他部分提供可用的功能。
"""
import asyncio
import importlib.util
import inspect
import sys
from graphlib import TopologicalSorter, CycleError
from pathlib import Path
from typing import Dict, Any, List, Optional

import yaml
from resolvelib import Resolver, BaseReporter

from .api import service_registry, ServiceDefinition, ACTION_REGISTRY, ActionDefinition, hook_manager
from .builder import build_package_from_source, clear_build_cache, API_FILE_NAME
from .plugin_definition import PluginDefinition
from .logger import logger
from .plugin_provider import PluginProvider


class PluginManager:
    """
    负责发现、解析、加载和管理 Aura 框架中的所有插件。

    它的核心职责是填充全局的 `ServiceRegistry` 和 `ACTION_REGISTRY`，
    为框架的其余部分准备好所有可用的功能。
    """

    def __init__(self, base_path: Path):
        """
        初始化插件管理器。

        Args:
            base_path (Path): 扫描插件的基础目录路径。
        """
        self.base_path = base_path
        self.plugin_registry: Dict[str, PluginDefinition] = {}

    def load_all_plugins(self):
        """
        同步执行完整的插件加载流程。

        此方法应在应用启动时调用，它会按顺序完成插件的发现、依赖解析和加载。
        这是一个编排方法，调用了多个私有辅助函数来完成工作。
        """
        logger.info("======= PluginManager: 开始加载所有插件 =======")
        try:
            self._clear_plugin_registries()
            self._discover_and_parse_plugins()
            load_order = self._resolve_dependencies_and_sort()

            logger.info("--- 插件加载顺序已确定 ---")
            for i, plugin_id in enumerate(load_order):
                logger.info(f"  {i + 1}. {plugin_id}")

            self._load_plugins_in_order(load_order)
            logger.info("======= PluginManager: 所有插件加载完毕 =======")
        except Exception as e:
            logger.critical(f"插件加载过程中发生致命错误: {e}", exc_info=True)
            raise

    def _clear_plugin_registries(self):
        """清空所有与插件相关的注册表，为重新加载做准备。"""
        logger.info("正在清理插件相关的注册表...")
        service_registry.remove_services_by_prefix(exclude_prefix="core/")
        ACTION_REGISTRY.clear()
        hook_manager.clear()
        clear_build_cache()
        self.plugin_registry.clear()
        logger.info("插件注册表清理完毕。")

    def _discover_and_parse_plugins(self):
        """
        阶段一：发现并解析所有插件定义。

        此方法会扫描 `plans` 和 `packages` 目录，查找所有 `plugin.yaml` 文件，
        并将它们解析成 `PluginDefinition` 对象，存入 `plugin_registry`。
        """
        logger.info("--- 阶段1: 发现并解析所有插件定义 (plugin.yaml) ---")
        plugin_paths_to_scan = [self.base_path / 'plans', self.base_path / 'packages']
        for root_path in plugin_paths_to_scan:
            if not root_path.is_dir(): continue
            for plugin_yaml_path in root_path.glob('**/plugin.yaml'):
                plugin_dir = plugin_yaml_path.parent
                try:
                    with open(plugin_yaml_path, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)
                    relative_path = plugin_dir.relative_to(self.base_path)
                    plugin_type = 'plan' if relative_path.parts[0] == 'plans' else 'core'
                    plugin_def = PluginDefinition.from_yaml(data, plugin_dir, plugin_type)
                    if plugin_def.canonical_id in self.plugin_registry:
                        raise RuntimeError(f"插件身份冲突: '{plugin_def.canonical_id}'")
                    self.plugin_registry[plugin_def.canonical_id] = plugin_def
                except Exception as e:
                    logger.error(f"解析 '{plugin_yaml_path}' 失败: {e}")
                    raise

    def _resolve_dependencies_and_sort(self) -> List[str]:
        """
        阶段二：使用 resolvelib 验证依赖，并使用 graphlib 进行拓扑排序。

        Returns:
            List[str]: 一个包含插件规范ID的列表，表示正确的加载顺序。

        Raises:
            RuntimeError: 如果检测到循环依赖或依赖解析失败。
        """
        logger.info("--- 阶段2: 解析依赖关系并确定加载顺序 ---")
        provider = PluginProvider(self.plugin_registry)
        reporter = BaseReporter()
        resolver = Resolver(provider, reporter)
        try:
            # 步骤 1: 使用 resolvelib 进行复杂的依赖验证
            resolver.resolve(self.plugin_registry.keys())

            # 步骤 2: 构建一个简单的图用于拓扑排序
            graph = {pid: set(pdef.dependencies.keys()) for pid, pdef in self.plugin_registry.items()}

            # 步骤 3: 使用标准库进行拓扑排序
            ts = TopologicalSorter(graph)
            return list(ts.static_order())
        except CycleError as e:
            cycle_path = " -> ".join(e.args[1])
            raise RuntimeError(f"检测到插件间的循环依赖，无法启动: {cycle_path}") from e
        except Exception as e:
            logger.error(f"依赖解析失败: {e}", exc_info=True)
            raise RuntimeError("依赖解析失败，无法启动。") from e

    def _load_plugins_in_order(self, load_order: List[str]):
        """
        阶段三：按照已确定的顺序加载所有插件。

        Args:
            load_order (List[str]): 由 `_resolve_dependencies_and_sort` 生成的插件ID列表。
        """
        logger.info("--- 阶段3: 按顺序加载/构建所有包 ---")
        for plugin_id in load_order:
            plugin_def = self.plugin_registry.get(plugin_id)
            if not plugin_def: continue

            api_file_path = plugin_def.path / API_FILE_NAME
            if not api_file_path.exists():
                build_package_from_source(plugin_def)

            self._load_package_from_api_file(plugin_def, api_file_path)
            self._load_hooks_for_package(plugin_def)

    def _load_package_from_api_file(self, plugin_def: PluginDefinition, api_file_path: Path):
        """从插件的 api.yaml 文件中加载其服务和行为。"""
        with open(api_file_path, 'r', encoding='utf-8') as f:
            api_data = yaml.safe_load(f)

        # 加载服务
        for service_info in api_data.get("exports", {}).get("services", []):
            try:
                module = self._lazy_load_module(plugin_def.path / service_info['source_file'])
                service_class = getattr(module, service_info['class_name'])
                definition = ServiceDefinition(
                    alias=service_info['alias'],
                    fqid=f"{plugin_def.canonical_id}/{service_info['alias']}",
                    service_class=service_class,
                    plugin=plugin_def,
                    public=True
                )
                service_registry.register(definition)
            except (ImportError, AttributeError, KeyError) as e:
                logger.error(f"加载服务 '{service_info.get('alias')}' 从 '{plugin_def.canonical_id}' 失败: {e}")

        # 加载行为
        for action_info in api_data.get("exports", {}).get("actions", []):
            try:
                module = self._lazy_load_module(plugin_def.path / action_info['source_file'])
                action_func = getattr(module, action_info['function_name'])
                is_async_action = asyncio.iscoroutinefunction(action_func)

                action_meta = getattr(action_func, '_aura_action_meta', {})

                definition = ActionDefinition(
                    func=action_func,
                    name=action_meta.get('name', action_info['name']),
                    read_only=action_meta.get('read_only', False),
                    public=action_meta.get('public', True),
                    service_deps=action_meta.get('services', {}),
                    plugin=plugin_def,
                    is_async=is_async_action
                )
                ACTION_REGISTRY.register(definition)
            except (ImportError, AttributeError, KeyError) as e:
                logger.error(f"加载行为 '{action_info.get('name')}' 从 '{plugin_def.canonical_id}' 失败: {e}")

        logger.debug(f"包 '{plugin_def.canonical_id}' 已从 API 文件成功加载。")

    def _load_hooks_for_package(self, plugin_def: PluginDefinition):
        """为指定的插件加载其定义的钩子。"""
        hooks_file = plugin_def.path / 'hooks.py'
        if hooks_file.is_file():
            logger.debug(f"在包 '{plugin_def.canonical_id}' 中发现钩子文件，正在加载...")
            try:
                module = self._lazy_load_module(hooks_file)
                for _, func in inspect.getmembers(module, inspect.isfunction):
                    if hasattr(func, '_aura_hook_name'):
                        hook_name = getattr(func, '_aura_hook_name')
                        hook_manager.register(hook_name, func)
            except Exception as e:
                logger.error(f"加载钩子文件 '{hooks_file}' 失败: {e}", exc_info=True)

    def _lazy_load_module(self, file_path: Path) -> Any:
        """
        根据文件路径延迟加载一个 Python 模块。

        如果模块已经加载，则直接从 `sys.modules` 返回。
        否则，使用 `importlib` 从文件动态加载。

        Args:
            file_path (Path): 要加载的 .py 文件的路径。

        Returns:
            Any: 加载的模块对象。
        """
        try:
            relative_path = file_path.relative_to(self.base_path)
            module_name = str(relative_path).replace('/', '.').replace('\\', '.').removesuffix('.py')

            if module_name in sys.modules:
                return sys.modules[module_name]

            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None: raise ImportError(f"无法为模块创建规范: {file_path}")

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            logger.error(f"延迟加载模块 '{file_path}' 失败: {e}", exc_info=True)
            raise

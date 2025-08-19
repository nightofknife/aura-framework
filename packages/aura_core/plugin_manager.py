import asyncio
import importlib.util
import inspect
import sys
from graphlib import TopologicalSorter, CycleError
from pathlib import Path
from typing import Dict, Any, List, Optional

import yaml
from resolvelib import Resolver, BaseReporter

from packages.aura_core.api import service_registry, ServiceDefinition, ACTION_REGISTRY, ActionDefinition, hook_manager
from packages.aura_core.builder import build_package_from_source, clear_build_cache, API_FILE_NAME
from packages.aura_shared_utils.models.plugin_definition import PluginDefinition
from packages.aura_shared_utils.utils.logger import logger
from .orchestrator import Orchestrator
from .plugin_provider import PluginProvider


class PluginManager:
    """
    负责发现、解析、加载和管理 Aura 框架中的所有插件。
    【Async Refactor】增加了对异步 Action 的检测。
    """

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.plugin_registry: Dict[str, PluginDefinition] = {}
        self.plans: Dict[str, 'Orchestrator'] = {}

    def load_all_plugins(self, pause_event: asyncio.Event):
        """
        【Async Refactor】接收 asyncio.Event。
        """
        logger.info("======= PluginManager: 开始加载所有插件 =======")
        try:
            self._clear_plugin_registries()
            self._discover_and_parse_plugins()
            load_order = self._resolve_dependencies_and_sort()

            logger.info("--- 插件加载顺序已确定 ---")
            for i, plugin_id in enumerate(load_order):
                logger.info(f"  {i + 1}. {plugin_id}")

            self._load_plugins_in_order(load_order, pause_event)
            logger.info("======= PluginManager: 所有插件加载完毕 =======")
        except Exception as e:
            logger.critical(f"插件加载过程中发生致命错误: {e}", exc_info=True)
            raise

    # ... (_clear_plugin_registries, _discover_and_parse_plugins, _resolve_dependencies_and_sort 不变) ...
    def _clear_plugin_registries(self):
        logger.info("正在清理插件相关的注册表...")
        service_registry.remove_services_by_prefix(exclude_prefix="core/")
        ACTION_REGISTRY.clear()
        hook_manager.clear()
        clear_build_cache()
        self.plans.clear()
        self.plugin_registry.clear()
        logger.info("插件注册表清理完毕。")

    def _discover_and_parse_plugins(self):
        logger.info("--- 阶段1: 发现并解析所有插件定义 (plugin.yaml) ---")
        # ... (内容不变) ...
        plugin_paths_to_scan = [self.base_path / 'plans', self.base_path / 'packages']

        for root_path in plugin_paths_to_scan:
            if not root_path.is_dir():
                logger.warning(f"插件扫描目录不存在: {root_path}")
                continue
            for plugin_yaml_path in root_path.glob('**/plugin.yaml'):
                plugin_dir = plugin_yaml_path.parent
                try:
                    with open(plugin_yaml_path, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)

                    relative_path = plugin_dir.relative_to(self.base_path)
                    top_level_dir = relative_path.parts[0]
                    plugin_type = 'plan' if top_level_dir == 'plans' else 'core'

                    plugin_def = PluginDefinition.from_yaml(data, plugin_dir, plugin_type)
                    if plugin_def.canonical_id in self.plugin_registry:
                        raise RuntimeError(f"插件身份冲突！插件 '{plugin_def.path}' 和 "
                                           f"'{self.plugin_registry[plugin_def.canonical_id].path}' "
                                           f"都声明了相同的身份 '{plugin_def.canonical_id}'。")
                    self.plugin_registry[plugin_def.canonical_id] = plugin_def
                    logger.debug(f"成功解析插件: {plugin_def.canonical_id} (类型: {plugin_type}, 位于: {plugin_dir})")
                except Exception as e:
                    logger.error(f"解析 '{plugin_yaml_path}' 失败: {e}")
                    raise RuntimeError(f"无法解析插件定义文件 '{plugin_yaml_path}'。") from e

    def _resolve_dependencies_and_sort(self) -> List[str]:
        logger.info("--- 阶段2: 解析依赖关系并确定加载顺序 ---")
        # ... (内容不变) ...
        provider = PluginProvider(self.plugin_registry)
        reporter = BaseReporter()
        resolver = Resolver(provider, reporter)
        try:
            resolver.resolve(self.plugin_registry.keys())
        except Exception as e:
            logger.error("依赖解析失败！请检查插件的 `dependencies` 是否正确。")
            for line in str(e).splitlines():
                logger.error(f"  {line}")
            raise RuntimeError("依赖解析失败，无法启动。") from e
        graph = {pid: set(pdef.dependencies.keys()) for pid, pdef in self.plugin_registry.items()}
        try:
            ts = TopologicalSorter(graph)
            return list(ts.static_order())
        except CycleError as e:
            cycle_path = " -> ".join(e.args[1])
            raise RuntimeError(f"检测到插件间的循环依赖，无法启动: {cycle_path}")

    def _load_plugins_in_order(self, load_order: List[str], pause_event: asyncio.Event):
        logger.info("--- 阶段3: 按顺序加载/构建所有包 ---")
        for plugin_id in load_order:
            plugin_def = self.plugin_registry.get(plugin_id)
            if not plugin_def:
                logger.error(f"加载插件 '{plugin_id}' 失败：在注册表中找不到定义。")
                continue

            # API 文件加载或源码构建的逻辑保持不变
            api_file_path = plugin_def.path / API_FILE_NAME
            if not api_file_path.exists():
                build_package_from_source(plugin_def)

            self._load_package_from_api_file(plugin_def, api_file_path)

            self._load_hooks_for_package(plugin_def)
            if plugin_def.plugin_type == 'plan':
                plan_name = plugin_def.path.name
                if plan_name not in self.plans:
                    logger.info(f"为方案包 '{plan_name}' 创建Orchestrator实例")
                    self.plans[plan_name] = Orchestrator(
                        base_dir=str(self.base_path),
                        plan_name=plan_name,
                        pause_event=pause_event
                    )

    def _load_hooks_for_package(self, plugin_def: PluginDefinition):
        # ... (此方法内容不变) ...
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

    def _load_package_from_api_file(self, plugin_def: PluginDefinition, api_file_path: Path):
        with open(api_file_path, 'r', encoding='utf-8') as f:
            api_data = yaml.safe_load(f)

        # 加载服务
        for service_info in api_data.get("exports", {}).get("services", []):
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

        # 加载行为
        for action_info in api_data.get("exports", {}).get("actions", []):
            module = self._lazy_load_module(plugin_def.path / action_info['source_file'])
            action_func = getattr(module, action_info['function_name'])

            # 【核心修改】检测 Action 是否为异步函数
            is_async_action = asyncio.iscoroutinefunction(action_func)

            definition = ActionDefinition(
                func=action_func,
                name=action_info['name'],
                read_only=getattr(action_func, '_aura_action_meta', {}).get('read_only', False),
                public=True,
                service_deps=action_info.get('required_services', {}),
                plugin=plugin_def,
                is_async=is_async_action  # 存储异步标志
            )
            ACTION_REGISTRY.register(definition)

        logger.debug(f"包 '{plugin_def.canonical_id}' 已从 API 文件成功加载。")

    def _lazy_load_module(self, file_path: Path) -> Optional[Any]:
        # ... (此方法内容不变) ...
        try:
            relative_path = file_path.relative_to(self.base_path)
            module_name = str(relative_path).replace('/', '.').replace('\\', '.').removesuffix('.py')

            if module_name in sys.modules:
                return sys.modules[module_name]

            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None: return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            logger.error(f"延迟加载模块 '{file_path}' 失败: {e}", exc_info=True)
            return None

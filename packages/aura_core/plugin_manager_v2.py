"""
新版插件管理器

基于 manifest.yaml 的插件加载和管理
"""

from pathlib import Path
from typing import Dict, List
from graphlib import TopologicalSorter
import logging

from .plugin_manifest import PluginManifest
from .manifest_parser import ManifestParser

logger = logging.getLogger(__name__)


class PluginManagerV2:
    """新版插件管理器（基于 manifest.yaml）"""

    def __init__(self, plugins_dir: Path):
        self.plugins_dir = plugins_dir
        self.loaded_plugins: Dict[str, PluginManifest] = {}

    def load_all_plugins(self):
        """加载所有插件"""
        logger.info("======= PluginManagerV2: 开始加载所有插件 =======")

        # 1. 发现插件
        manifests = self._discover_plugins()

        # 2. 验证清单
        self._validate_manifests(manifests)

        # 3. 解析依赖并排序
        load_order = self._resolve_dependencies(manifests)

        # 4. 按顺序加载
        self._load_in_order(load_order, manifests)

        logger.info(f"======= 已加载 {len(self.loaded_plugins)} 个插件 =======")

    def _discover_plugins(self) -> Dict[str, PluginManifest]:
        """发现所有插件"""
        manifests = {}

        for manifest_path in self.plugins_dir.rglob("manifest.yaml"):
            try:
                manifest = ManifestParser.parse(manifest_path)
                manifests[manifest.package.canonical_id] = manifest
                logger.info(f"发现插件: {manifest.package.canonical_id} v{manifest.package.version}")
            except Exception as e:
                logger.error(f"解析 {manifest_path} 失败: {e}")

        return manifests

    def _validate_manifests(self, manifests: Dict[str, PluginManifest]):
        """验证所有插件清单"""
        for plugin_id, manifest in manifests.items():
            errors = ManifestParser.validate(manifest)
            if errors:
                logger.error(f"插件 {plugin_id} 验证失败:")
                for error in errors:
                    logger.error(f"  - {error}")
                raise ValueError(f"Plugin {plugin_id} has invalid manifest")

    def _resolve_dependencies(self, manifests: Dict[str, PluginManifest]) -> List[str]:
        """解析依赖并返回加载顺序"""
        graph = {}

        for plugin_id, manifest in manifests.items():
            deps = [
                dep.name.lstrip("@")
                for dep in manifest.dependencies.values()
                if not dep.optional
            ]
            graph[plugin_id] = deps

        sorter = TopologicalSorter(graph)
        try:
            return list(sorter.static_order())
        except Exception as e:
            logger.error(f"依赖解析失败（可能存在循环依赖）: {e}")
            raise

    def _load_in_order(self, load_order: List[str], manifests: Dict[str, PluginManifest]):
        """按顺序加载插件"""
        for plugin_id in load_order:
            if plugin_id not in manifests:
                continue

            manifest = manifests[plugin_id]
            logger.info(f"正在加载插件: {plugin_id}")

            try:
                # 调用 on_load 钩子
                if manifest.lifecycle.on_load:
                    self._call_hook(manifest, manifest.lifecycle.on_load)

                # 注册服务、动作、任务
                self._register_exports(manifest)

                self.loaded_plugins[plugin_id] = manifest
                logger.info(f"✓ 插件 {plugin_id} 加载成功")

            except Exception as e:
                logger.error(f"✗ 插件 {plugin_id} 加载失败: {e}")

    def _call_hook(self, manifest: PluginManifest, hook: str):
        """调用生命周期钩子"""
        try:
            # 解析钩子路径: module:function
            module_path, func_name = hook.split(':')

            # 构建完整的模块路径
            full_module_path = f"{manifest.path.name}.src.{module_path.replace('/', '.')}"

            # 动态导入模块
            import importlib
            import sys

            # 临时添加插件目录到 sys.path
            plugin_src_path = str(manifest.path / "src")
            if plugin_src_path not in sys.path:
                sys.path.insert(0, plugin_src_path)

            try:
                # 尝试直接导入（相对于 src 目录）
                module = importlib.import_module(module_path.replace('/', '.'))
                func = getattr(module, func_name)

                # 调用钩子函数
                logger.info(f"调用钩子: {hook}")
                func()

            finally:
                # 清理 sys.path
                if plugin_src_path in sys.path:
                    sys.path.remove(plugin_src_path)

        except Exception as e:
            logger.warning(f"调用钩子 {hook} 失败: {e}")

    def _register_exports(self, manifest: PluginManifest):
        """注册导出的服务、动作、任务

        注意：这是基于 manifest.yaml 的新插件系统与现有 plugin.yaml 系统的桥接层。
        当前实现提供了基本的日志记录和框架，需要与现有系统集成。
        """
        try:
            # 注册服务到 service_registry
            for service in manifest.exports.services:
                logger.info(f"发现服务导出: {manifest.package.canonical_id}.{service.name}")
                # TODO: 与现有 service_registry 集成
                # 需要实现:
                # 1. 动态导入服务类
                # 2. 创建 ServiceDefinition
                # 3. 调用 service_registry.register()
                #
                # 示例代码（需要适配）:
                # from packages.aura_core.api import service_registry, ServiceDefinition
                # module_path, class_name = service.source.split(':')
                # module = importlib.import_module(f"{manifest.path.name}.src.{module_path}")
                # service_class = getattr(module, class_name)
                # definition = ServiceDefinition(...)
                # service_registry.register(definition)

            # 注册动作到 ACTION_REGISTRY
            for action in manifest.exports.actions:
                logger.info(f"发现动作导出: {manifest.package.canonical_id}.{action.name}")
                # TODO: 与现有 ACTION_REGISTRY 集成
                # 需要实现:
                # 1. 动态导入动作函数
                # 2. 创建 ActionDefinition
                # 3. 调用 ACTION_REGISTRY.register()
                #
                # 示例代码（需要适配）:
                # from packages.aura_core.api import ACTION_REGISTRY, ActionDefinition
                # module_path, func_name = action.source.split(':')
                # module = importlib.import_module(f"{manifest.path.name}.src.{module_path}")
                # action_func = getattr(module, func_name)
                # definition = ActionDefinition(...)
                # ACTION_REGISTRY.register(definition)

            # 任务注册
            for task in manifest.exports.tasks:
                logger.info(f"发现任务导出: {manifest.package.canonical_id}.{task.id}")
                # TODO: 与现有任务系统集成
                # 注意: Aura 现有的任务系统基于文件系统（Orchestrator/PlanManager）
                # 而不是注册表模式。可能的集成方式：
                # 1. 在插件目录下创建标准的任务定义文件
                # 2. 或者扩展 PlanManager 支持从 manifest 加载任务
                # 3. 或者创建一个新的任务注册表来管理 manifest 导出的任务

            # 记录成功
            total_exports = len(manifest.exports.services) + len(manifest.exports.actions) + len(manifest.exports.tasks)
            if total_exports > 0:
                logger.info(f"插件 {manifest.package.canonical_id} 导出: "
                          f"{len(manifest.exports.services)} 服务, "
                          f"{len(manifest.exports.actions)} 动作, "
                          f"{len(manifest.exports.tasks)} 任务")

        except Exception as e:
            logger.error(f"注册导出失败: {e}", exc_info=True)

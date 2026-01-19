# -*- coding: utf-8 -*-
"""
包管理器（基于 manifest.yaml）

替代 PluginManager，从 manifest.yaml 加载包
"""

from pathlib import Path
from typing import Dict, List
from graphlib import TopologicalSorter
import logging

from ..manifest import ManifestParser, PluginManifest
from ...api import service_registry, ACTION_REGISTRY, ActionDefinition, ServiceDefinition

logger = logging.getLogger(__name__)


class PackageManager:
    """
    新版包管理器（基于 manifest.yaml）

    职责：
    1. 从 packages/ 和 plans/ 目录加载所有包
    2. 解析依赖关系并按拓扑排序
    3. 注册 Services、Actions、Tasks 到运行时注册表
    4. 验证 FQID 调用的合法性
    """

    def __init__(self, packages_dir: Path, plans_dir: Path):
        self.packages_dir = packages_dir
        self.plans_dir = plans_dir
        self.loaded_packages: Dict[str, PluginManifest] = {}

    def load_all_packages(self):
        """加载所有包"""
        logger.info("======= PackageManager: 开始加载所有包 =======")

        # 1. 发现所有包
        manifests = self._discover_packages()

        # 2. 验证清单
        self._validate_manifests(manifests)

        # 3. 解析依赖并排序
        load_order = self._resolve_dependencies(manifests)

        # 4. 按顺序加载
        self._load_in_order(load_order, manifests)

        # ✅ 5. 验证服务循环依赖
        from ...api import service_registry
        try:
            service_registry.validate_no_circular_dependencies()
        except ValueError as e:
            logger.error(f"服务依赖验证失败: {e}")
            raise

        logger.info(f"======= 已加载 {len(self.loaded_packages)} 个包 =======")

    def _discover_packages(self) -> Dict[str, PluginManifest]:
        """发现所有包"""
        manifests = {}

        # 扫描 packages/ 和 plans/
        for base_dir in [self.packages_dir, self.plans_dir]:
            if not base_dir.exists():
                continue

            for manifest_path in base_dir.rglob("manifest.yaml"):
                try:
                    manifest = ManifestParser.parse(manifest_path)
                    manifests[manifest.package.canonical_id] = manifest
                    logger.info(f"发现包: {manifest.package.canonical_id} v{manifest.package.version}")
                except Exception as e:
                    logger.error(f"解析 {manifest_path} 失败: {e}")

        return manifests

    def _validate_manifests(self, manifests: Dict[str, PluginManifest]):
        """验证所有清单"""
        for package_id, manifest in manifests.items():
            errors = ManifestParser.validate(manifest)
            if errors:
                logger.error(f"包 {package_id} 验证失败:")
                for error in errors:
                    logger.error(f"  - {error}")
                raise ValueError(f"Package {package_id} has invalid manifest")

    def _resolve_dependencies(self, manifests: Dict[str, PluginManifest]) -> List[str]:
        """解析依赖并返回加载顺序。

        ✅ 修复：
        1. 验证必需依赖是否存在
        2. 可选依赖也加入加载顺序（如果存在）
        3. 提供清晰的错误信息

        Args:
            manifests: 所有已发现的包清单

        Returns:
            按依赖关系排序后的包ID列表

        Raises:
            ValueError: 如果存在缺失的必需依赖或循环依赖
        """
        graph = {}
        missing_deps = {}  # 记录缺失的依赖

        for package_id, manifest in manifests.items():
            deps = []

            for dep_spec in manifest.dependencies.values():
                dep_id = dep_spec.name.lstrip("@")

                # ✅ 验证必需依赖是否存在
                if not dep_spec.optional and dep_id not in manifests:
                    if package_id not in missing_deps:
                        missing_deps[package_id] = []
                    missing_deps[package_id].append((dep_id, dep_spec))
                    continue  # 继续收集其他缺失的依赖

                # ✅ 可选依赖也加入图（如果存在）
                if dep_id in manifests:
                    deps.append(dep_id)
                    logger.debug(
                        f"包 '{package_id}' 依赖 '{dep_id}' "
                        f"({'必需' if not dep_spec.optional else '可选'})"
                    )

            graph[package_id] = deps

        # ✅ 如果有缺失的必需依赖，抛出详细错误
        if missing_deps:
            error_lines = ["检测到缺失的包依赖:"]
            for pkg_id, deps in missing_deps.items():
                error_lines.append(f"\n包 '{pkg_id}' 缺失以下必需依赖:")
                for dep_id, dep_spec in deps:
                    error_lines.append(
                        f"  - {dep_spec.name} (版本: {dep_spec.version}, 来源: {dep_spec.source})"
                    )

            error_lines.append("\n请确保:")
            error_lines.append("1. 依赖包已放置在正确的目录 (packages/ 或 plans/)")
            error_lines.append("2. 依赖包的 manifest.yaml 格式正确")
            error_lines.append("3. 依赖包的 canonical_id 与依赖声明匹配")

            raise ValueError("\n".join(error_lines))

        # ✅ 拓扑排序
        sorter = TopologicalSorter(graph)
        try:
            load_order = list(sorter.static_order())
            logger.info(f"依赖解析完成，加载顺序: {' -> '.join(load_order)}")
            return load_order
        except Exception as e:
            logger.error(f"依赖解析失败（可能存在循环依赖）: {e}")
            # ✅ 提供更详细的循环依赖信息
            logger.error("依赖关系图:")
            for pkg_id, deps in graph.items():
                logger.error(f"  {pkg_id} -> {deps}")
            raise ValueError(f"包依赖存在循环引用，无法加载。详情: {e}")

    def _load_in_order(self, load_order: List[str], manifests: Dict[str, PluginManifest]):
        """按顺序加载包"""
        for package_id in load_order:
            if package_id not in manifests:
                continue

            manifest = manifests[package_id]
            logger.info(f"正在加载包: {package_id}")

            try:
                # 调用 on_load 钩子
                if manifest.lifecycle.on_load:
                    self._call_hook(manifest, manifest.lifecycle.on_load)

                # 注册 Services、Actions、Tasks
                self._register_services(manifest)
                self._register_actions(manifest)
                self._register_tasks(manifest)

                self.loaded_packages[package_id] = manifest
                logger.info(f"✓ 包 {package_id} 加载成功")

            except Exception as e:
                logger.error(f"✗ 包 {package_id} 加载失败: {e}")
                raise

    def _call_hook(self, manifest: PluginManifest, hook: str):
        """调用生命周期钩子"""
        try:
            module_path, func_name = hook.split(':')

            # 动态导入
            import importlib
            import sys

            plugin_src_path = str(manifest.path / "src")
            if plugin_src_path not in sys.path:
                sys.path.insert(0, plugin_src_path)

            try:
                module = importlib.import_module(module_path.replace('/', '.'))
                func = getattr(module, func_name)

                logger.info(f"调用钩子: {hook}")
                func()

            finally:
                if plugin_src_path in sys.path:
                    sys.path.remove(plugin_src_path)

        except Exception as e:
            logger.warning(f"调用钩子 {hook} 失败: {e}")

    def _register_services(self, manifest: PluginManifest):
        """注册服务

        ✅ 修复：确保sys.path在异常时也能正确清理
        """
        import importlib
        import sys

        # 添加包路径（不是src路径）到sys.path
        plugin_path = str(manifest.path)
        path_added = False  # ✅ 标记是否添加了路径

        try:
            if plugin_path not in sys.path:
                sys.path.insert(0, plugin_path)
                path_added = True  # ✅ 记录我们添加了路径

            for service in manifest.exports.services:
                module_path, class_name = service.source.split(':')

                # 导入模块（source格式: src/services/config_service）
                # 转换为完整的导入路径
                full_module_path = module_path.replace('/', '.')

                module = importlib.import_module(full_module_path)
                service_class = getattr(module, class_name)

                # 构建 FQID
                service_fqid = f"{manifest.package.canonical_id}/{service.name}"

                # 注册到运行时注册表
                definition = ServiceDefinition(
                    alias=service.name,
                    fqid=service_fqid,
                    service_class=service_class,
                    plugin=manifest,
                    public=service.visibility == "public"
                )
                service_registry.register(definition)

                logger.info(f"  [OK] 注册服务: {service_fqid}")

        except Exception as e:
            logger.error(f"注册服务失败 (包: {manifest.package.canonical_id}): {e}")
            raise  # ✅ 重新抛出异常，让调用者处理

        finally:
            # ✅ 确保清理：只移除我们添加的路径
            if path_added and plugin_path in sys.path:
                try:
                    sys.path.remove(plugin_path)
                    logger.debug(f"已从 sys.path 移除: {plugin_path}")
                except ValueError:
                    # 已被其他代码移除，忽略
                    pass

    def _register_actions(self, manifest: PluginManifest):
        """注册动作

        ✅ 修复：确保sys.path在异常时也能正确清理
        """
        import importlib
        import sys
        import inspect

        # 添加包路径到sys.path
        plugin_path = str(manifest.path)
        path_added = False  # ✅ 标记是否添加了路径

        try:
            if plugin_path not in sys.path:
                sys.path.insert(0, plugin_path)
                path_added = True  # ✅ 记录我们添加了路径

            for action in manifest.exports.actions:
                module_path, func_name = action.source.split(':')

                # 导入模块（source格式: src/actions/atomic_actions）
                full_module_path = module_path.replace('/', '.')

                module = importlib.import_module(full_module_path)
                action_func = getattr(module, func_name)

                # ✅ 构建三段式 FQID: author/package/action
                # 将 canonical_id (@Aura-Project/base) 拆分为 author/package
                canonical_id = manifest.package.canonical_id.lstrip('@')
                parts = canonical_id.split('/')
                if len(parts) != 2:
                    logger.warning(
                        f"包 '{canonical_id}' 的 canonical_id 格式不标准，"
                        f"应为 '@author/package'，action FQID可能不正确"
                    )
                    # 兼容处理：如果不是两段，直接使用
                    action_fqid = f"{canonical_id}/{action.name}"
                else:
                    author, package_name = parts
                    action_fqid = f"{author}/{package_name}/{action.name}"  # 三段式

                # 提取服务依赖（从装饰器元数据）
                service_deps = getattr(action_func, '_service_dependencies', {})

                # 注册到运行时注册表
                definition = ActionDefinition(
                    func=action_func,
                    name=action.name,
                    read_only=False,  # 可从 action 扩展字段获取
                    public=action.visibility == "public",
                    service_deps=service_deps,
                    plugin=manifest,
                    is_async=inspect.iscoroutinefunction(action_func)
                )
                ACTION_REGISTRY.register(definition)

                logger.info(f"  [OK] 注册动作: {action_fqid}")

        except Exception as e:
            logger.error(f"注册动作失败 (包: {manifest.package.canonical_id}): {e}")
            raise  # ✅ 重新抛出异常

        finally:
            # ✅ 确保清理：只移除我们添加的路径
            if path_added and plugin_path in sys.path:
                try:
                    sys.path.remove(plugin_path)
                    logger.debug(f"已从 sys.path 移除: {plugin_path}")
                except ValueError:
                    pass

    def _register_tasks(self, manifest: PluginManifest):
        """注册任务"""
        for task in manifest.exports.tasks:
            # 任务不需要注册到注册表
            # Orchestrator 会直接从文件系统加载
            logger.info(f"  ✓ 发现任务: {manifest.package.canonical_id}/{task.id}")

    def get_package(self, package_id: str) -> PluginManifest:
        """获取已加载的包"""
        return self.loaded_packages.get(package_id)

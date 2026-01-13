"""
Manifest.yaml 解析器

负责解析和验证 manifest.yaml 文件
"""

import yaml
from pathlib import Path
from typing import List
from packaging.version import Version

from .plugin_manifest import (
    PluginManifest, PackageInfo, DependencySpec,
    Exports, ExportedService, ExportedAction, ExportedTask,
    LifecycleHooks, BuildConfig, TrustInfo,
    ConfigurationSpec, ResourceMapping
)


class ManifestParser:
    """manifest.yaml 解析器"""

    @staticmethod
    def parse(manifest_path: Path) -> PluginManifest:
        """解析 manifest.yaml 文件"""
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # 解析 package
        package = PackageInfo(**data["package"])

        # 解析依赖
        dependencies = {}
        for name, spec in data.get("dependencies", {}).items():
            if isinstance(spec, dict):
                # 转换 path 为 Path 对象
                if 'path' in spec and spec['path']:
                    spec['path'] = Path(spec['path'])
                dependencies[name] = DependencySpec(name=name, **spec)
            else:
                # 简写形式：仅版本字符串
                dependencies[name] = DependencySpec(
                    name=name,
                    version=spec,
                    source="local"
                )

        # 解析导出
        exports_data = data.get("exports", {})
        exports = Exports(
            services=[ExportedService(**s) for s in exports_data.get("services", [])],
            actions=[ExportedAction(**a) for a in exports_data.get("actions", [])],
            tasks=[ExportedTask(**t) for t in exports_data.get("tasks", [])]
        )

        # 解析生命周期钩子
        lifecycle = LifecycleHooks(**data.get("lifecycle", {}))

        # 解析配置规范
        configuration = ConfigurationSpec(**data.get("configuration", {}))

        # 解析资源映射
        resources = ResourceMapping(**data.get("resources", {}))

        # 解析构建配置
        build = BuildConfig(**data.get("build", {}))

        # 解析信任信息
        trust = TrustInfo(**data.get("trust", {}))

        return PluginManifest(
            package=package,
            requires=data.get("requires", {}),
            dependencies=dependencies,
            pypi_dependencies=data.get("pypi-dependencies", {}),
            exports=exports,
            extends=data.get("extends", []),
            overrides=data.get("overrides", []),
            lifecycle=lifecycle,
            configuration=configuration,
            resources=resources,
            build=build,
            trust=trust,
            metadata=data.get("metadata", {}),
            path=manifest_path.parent
        )

    @staticmethod
    def validate(manifest: PluginManifest) -> List[str]:
        """验证 manifest 的有效性，返回错误列表"""
        errors = []

        # 检查必填字段
        if not manifest.package.name:
            errors.append("package.name is required")
        if not manifest.package.version:
            errors.append("package.version is required")

        # 检查版本格式
        try:
            Version(manifest.package.version)
        except Exception:
            errors.append(f"Invalid version: {manifest.package.version}")

        # 检查依赖
        for dep_name, dep in manifest.dependencies.items():
            if dep.source == "local" and not dep.path:
                errors.append(f"Dependency {dep_name}: local source requires 'path'")
            if dep.source == "git" and not dep.git_url:
                errors.append(f"Dependency {dep_name}: git source requires 'git_url'")

        return errors

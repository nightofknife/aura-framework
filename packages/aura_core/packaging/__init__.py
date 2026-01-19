# -*- coding: utf-8 -*-
"""Aura 框架的包和插件系统。

此模块提供完整的包管理、Manifest系统和开发工具。

模块组织:
- core: 核心管理（PackageManager, PlanManager, TaskLoader等）
- manifest: Manifest系统（数据类、解析器、生成器）
- tools: 开发工具（安装器、打包器、脚手架）

常用导入:
    from packages.aura_core.packaging import PackageManager, PlanManager
    from packages.aura_core.packaging.manifest import PluginManifest
    from packages.aura_core.packaging.tools import PluginScaffold
"""

# 导出核心管理类（最常用）
from .core import (
    PackageManager,
    PlanManager,
    PlanRegistry,
    TaskLoader,
    DependencyManager,
)

# 导出Manifest系统（常用）
from .manifest import (
    PluginManifest,
    PackageInfo,
    ManifestParser,
)

# 工具类不在顶层导出，需要时显式导入
# from .tools import PluginInstaller, PluginPacker, PluginScaffold

__all__ = [
    # 核心管理
    'PackageManager',
    'PlanManager',
    'PlanRegistry',
    'TaskLoader',
    'DependencyManager',
    # Manifest系统
    'PluginManifest',
    'PackageInfo',
    'ManifestParser',
]

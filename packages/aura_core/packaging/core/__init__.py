# -*- coding: utf-8 -*-
"""Aura 框架的包和计划核心管理模块。

此模块提供包发现、加载、注册和计划管理的核心功能。

核心组件:
- PackageManager: 包发现、依赖解析、Services/Actions注册
- PlanManager: Plan加载、Orchestrator创建
- PlanRegistry: Plan查询接口
- TaskLoader: 任务YAML加载和缓存
- DependencyManager: Python依赖管理
"""

from .package_manager import PackageManager
from .plan_manager import PlanManager
from .plan_registry import PlanRegistry
from .task_loader import TaskLoader
from .dependency_manager import DependencyManager

__all__ = [
    'PackageManager',
    'PlanManager',
    'PlanRegistry',
    'TaskLoader',
    'DependencyManager',
]

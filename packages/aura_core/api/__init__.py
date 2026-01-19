# -*- coding: utf-8 -*-
"""Aura 框架的公共 API 定义模块。

此模块定义了用于创建和注册 Aura 框架核心组件的装饰器和注册表类。
开发者通过使用这些 API,可以将自己的代码集成到 Aura 的生态系统中。

核心组件:
- **Action**: 一个可执行的操作单元,是构成任务的基本步骤。
  使用 `@register_action` 装饰器来定义。
- **Service**: 一个可注入的、有状态的后台服务,为 Action 提供共享功能或资源。
  使用 `@register_service` 装饰器来定义,并使用 `@requires_services` 来注入。
- **Hook**: 一个在框架生命周期特定点触发的回调。
  使用 `@register_hook` 装饰器来定义。

全局注册表实例:
- `ACTION_REGISTRY`: `ActionRegistry` 的全局单例,存储所有已定义的 Action。
- `service_registry`: `ServiceRegistry` 的全局单例,管理所有 Service 的定义和实例化。
- `hook_manager`: `HookManager` 的全局单例,管理所有已注册的 Hook。
"""

# 导入数据类定义
from .definitions import (
    ActionDefinition,
    ServiceDefinition,
    HookResult,
)

# 导入注册表类和全局实例
from .registries import (
    ActionRegistry,
    ServiceRegistry,
    HookManager,
    ACTION_REGISTRY,
    service_registry,
    hook_manager,
)

# 导入装饰器
from .decorators import (
    register_action,
    requires_services,
    register_service,
    register_hook,
)

# 导出所有公共 API
__all__ = [
    # 数据类
    'ActionDefinition',
    'ServiceDefinition',
    'HookResult',
    # 注册表类
    'ActionRegistry',
    'ServiceRegistry',
    'HookManager',
    # 全局实例
    'ACTION_REGISTRY',
    'service_registry',
    'hook_manager',
    # 装饰器
    'register_action',
    'requires_services',
    'register_service',
    'register_hook',
]

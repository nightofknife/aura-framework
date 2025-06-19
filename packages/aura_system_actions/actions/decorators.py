# src/notifier_actions/decorators.py

import inspect
from typing import Callable, Any, Dict, List, Optional
import textwrap
from functools import wraps

from packages.aura_shared_utils.models.plugin_definition import PluginDefinition
from packages.aura_shared_utils.utils.logger import logger


class ActionDefinition:
    """【升级版】封装了Action函数及其元数据，现在包含插件信息。"""

    def __init__(self, func: Callable, name: str, read_only: bool, service_deps: Dict[str, str],
                 plugin_def: PluginDefinition):
        self.func = func
        self.name = name
        self.read_only = read_only
        self.signature = inspect.signature(func)
        doc = inspect.getdoc(func)
        self.docstring = textwrap.dedent(doc).strip() if doc else "此行为没有提供文档说明。"
        self.service_dependencies: Dict[str, str] = service_deps or {}
        self.plugin = plugin_def
        self.fqid = f"{plugin_def.canonical_id}/{name}"


class ActionRegistry:
    def __init__(self):
        self._actions: Dict[str, ActionDefinition] = {}

    def clear(self):
        self._actions.clear()

    def register(self, action_def: ActionDefinition):
        if action_def.name in self._actions:
            existing_fqid = self._actions[action_def.name].fqid
            logger.warning(
                f"行为名称冲突！'{action_def.name}' (来自 {action_def.fqid}) 覆盖了之前的定义 (来自 {existing_fqid})。")
        self._actions[action_def.name] = action_def
        logger.debug(f"已注册行为: '{action_def.fqid}'")

    def get_all_action_definitions(self) -> List[ActionDefinition]:
        return sorted(list(self._actions.values()), key=lambda a: a.fqid)

    def __len__(self) -> int:
        return len(self._actions)

    def get(self, name: str) -> Optional[ActionDefinition]:
        return self._actions.get(name)


ACTION_REGISTRY = ActionRegistry()


def requires_services(*args: str, **kwargs: str):
    """【保持不变】"""

    def decorator(func: Callable) -> Callable:
        dependencies = {}
        for alias, service_id in kwargs.items():
            dependencies[alias] = service_id
        for service_id in args:
            default_alias = service_id.split('/')[-1]
            if default_alias in dependencies:
                raise NameError(f"在 @requires_services for '{func.__name__}' 中检测到依赖别名冲突: '{default_alias}'。")
            dependencies[default_alias] = service_id
        setattr(func, '_service_dependencies', dependencies)
        return func

    return decorator


def register_action(name: str, read_only: bool = False):
    """【核心修改】装饰器现在只“标记”函数，不再立即注册。"""

    def decorator(func: Callable) -> Callable:
        meta = {
            'name': name,
            'read_only': read_only,
            'services': getattr(func, '_service_dependencies', {})
        }
        setattr(func, '_aura_action_meta', meta)
        return func

    return decorator

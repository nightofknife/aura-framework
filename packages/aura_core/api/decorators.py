# -*- coding: utf-8 -*-
"""Aura 框架的装饰器和辅助函数。

此模块包含用于注册 Actions、Services 和 Hooks 的装饰器。
"""
import inspect
from typing import Any, Callable, Dict

from packages.aura_core.observability.logging.core_logger import logger


def register_action(
    name: str,
    read_only: bool = False,
    public: bool = False,
    description: str = None,
    visibility: str = "public",
    timeout: int = None
):
    """装饰器工厂,用于将一个函数注册为 Aura Action。

    Args:
        name (str): Action 的唯一名称,在 Plan 中使用此名称调用。
        read_only (bool): 标记 Action 是否为只读。
        public (bool): 标记 Action 是否为公开 API。
        description (str): 动作描述(可选,未提供则从 docstring 提取)
        visibility (str): 可见性(public/private)
        timeout (int): 超时时间(秒,可选)

    Returns:
        一个装饰器,可用于修饰函数。
    """
    def decorator(func: Callable) -> Callable:
        # 自动提取描述
        if description is None:
            desc = inspect.getdoc(func) or ""
            # 提取第一段(直到第一个空行或 Args:)
            desc = desc.split('\n\n')[0].split('Args:')[0].strip()
        else:
            desc = description

        # 自动提取参数信息
        sig = inspect.signature(func)
        parameters = []
        for param_name, param in sig.parameters.items():
            # 跳过注入参数
            if param_name in ['context', 'engine']:
                continue
            # 跳过服务依赖参数(类名以 Service 结尾)
            if param.annotation != inspect.Parameter.empty:
                type_name = getattr(param.annotation, '__name__', str(param.annotation))
                if isinstance(type_name, str) and type_name.endswith('Service'):
                    continue

            param_info = {
                "name": param_name,
                "type": _get_type_string(param.annotation),
                "required": param.default == inspect.Parameter.empty,
                "default": param.default if param.default != inspect.Parameter.empty else None
            }

            # 尝试从 docstring 提取参数描述
            param_desc = _extract_param_description(func, param_name)
            if param_desc:
                param_info["description"] = param_desc

            parameters.append(param_info)

        # 提取服务依赖
        service_deps = getattr(func, '_service_dependencies', {})

        # 存储增强的元数据
        meta = {
            'name': name,
            'read_only': read_only,
            'public': public,
            'services': service_deps,
            'description': desc,
            'visibility': visibility,
            'timeout': timeout,
            'parameters': parameters,
            'service_deps': list(service_deps.values()),
            'is_async': inspect.iscoroutinefunction(func),
            'source_file': inspect.getfile(func),
            'source_function': func.__name__
        }

        # 保持旧的元数据格式兼容性
        setattr(func, '_aura_action_meta', meta)
        # 新增：为 manifest 生成器提供的元数据
        setattr(func, '__aura_action__', meta)

        return func

    return decorator


def requires_services(*args: str, **kwargs: str):
    """装饰器工厂,用于声明 Action 对一个或多个 Service 的依赖。

    被此装饰器修饰的函数在执行时,Aura 会自动将声明的 Service 实例
    注入到函数的对应参数中。

    用法:
        @requires_services('config', 'database')
        def my_action(config, database): ...

        @requires_services(cfg='config')
        def other_action(cfg): ...

    Args:
        *args: 服务别名列表。参数名将与服务别名相同。
        **kwargs: 服务别名到参数名的映射。

    Returns:
        一个装饰器,可用于修饰函数。
    """
    def decorator(func: Callable) -> Callable:
        dependencies = {}
        for alias, service_id in kwargs.items(): dependencies[alias] = service_id
        for service_id in args:
            default_alias = service_id.split('/')[-1]
            if default_alias in dependencies: raise NameError(
                f"在 @requires_services for '{func.__name__}' 中检测到依赖别名冲突: '{default_alias}'。")
            dependencies[default_alias] = service_id
        setattr(func, '_service_dependencies', dependencies)
        return func

    return decorator


def register_service(
    alias: str,
    public: bool = False,
    description: str = None,
    visibility: str = "public",
    singleton: bool = True,
    config_schema: Dict[str, Any] = None
):
    """装饰器工厂,用于将一个类注册为 Aura Service。

    Args:
        alias (str): 服务的唯一别名,用于依赖注入和覆盖。
        public (bool): 标记服务是否为公开,允许其他插件扩展或覆盖。
        description (str): 服务描述(可选,未提供则从 docstring 提取)
        visibility (str): 可见性(public/private)
        singleton (bool): 是否单例(默认 True)
        config_schema (Dict[str, Any]): 配置模式(可选)

    Returns:
        一个装饰器,可用于修饰类。
    """
    if not alias or not isinstance(alias, str):
        raise TypeError("服务别名(alias)必须是一个非空字符串。")

    def decorator(cls: type) -> type:
        # 自动提取 docstring
        if description is None:
            desc = inspect.getdoc(cls) or ""
            desc = desc.split('\n')[0]  # 取第一行
        else:
            desc = description

        # 存储增强的元数据
        meta = {
            'alias': alias,
            'public': public,
            'description': desc,
            'visibility': visibility,
            'singleton': singleton,
            'config_schema': config_schema,
            'source_file': inspect.getfile(cls),
            'source_class': cls.__name__
        }

        # 保持旧的元数据格式兼容性
        setattr(cls, '_aura_service_meta', meta)
        # 新增：为 manifest 生成器提供的元数据
        setattr(cls, '__aura_service__', meta)

        return cls

    return decorator


def register_hook(name: str):
    """装饰器工厂,用于将一个函数注册为 Aura Hook。

    Args:
        name (str): 钩子的名称。

    Returns:
        一个装饰器,可用于修饰函数。
    """
    def decorator(func: Callable) -> Callable:
        setattr(func, '_aura_hook_name', name)
        return func

    return decorator


# ========== 装饰器辅助函数 ==========

def _get_type_string(annotation) -> str:
    """将类型注解转换为字符串"""
    if annotation == inspect.Parameter.empty:
        return "Any"
    if hasattr(annotation, '__name__'):
        return annotation.__name__
    return str(annotation)


def _extract_param_description(func, param_name: str) -> str:
    """从 docstring 提取参数描述"""
    docstring = inspect.getdoc(func)
    if not docstring:
        return ""

    # 简单解析 Google/NumPy 风格的 docstring
    lines = docstring.split('\n')
    in_args_section = False
    for i, line in enumerate(lines):
        if 'Args:' in line or 'Parameters:' in line:
            in_args_section = True
            continue

        if in_args_section:
            if line.strip().startswith(f"{param_name}:"):
                # 提取描述部分
                desc = line.split(':', 1)[1].strip()
                # 可能跨多行,继续读取缩进的行
                j = i + 1
                while j < len(lines) and lines[j].startswith('        '):
                    desc += ' ' + lines[j].strip()
                    j += 1
                return desc

            # 遇到新的 section,停止
            if line.strip() and not line.startswith(' '):
                break

    return ""

# packages/aura_core/action_injector.py (全新文件)

import inspect
from ast import literal_eval
from typing import Any, Dict

from jinja2 import Environment, BaseLoader, UndefinedError

from packages.aura_shared_utils.utils.logger import logger
from .api import service_registry, ACTION_REGISTRY, ActionDefinition
from .context import Context
from .middleware import middleware_manager

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .engine import ExecutionEngine

class ActionInjector:
    """
    行为注入器。
    一个高度专业化的工具，负责正确地调用一个 Action。其职责包括：
    1. 使用 Jinja2 渲染 action 的参数。
    2. 准备依赖（注入服务、上下文等）。
    3. 通过中间件系统执行 action。
    4. 返回 action 的执行结果。
    """

    def __init__(self, context: Context, engine: 'ExecutionEngine'):
        self.context = context
        self.engine = engine  # 某些 action 可能需要 engine 实例
        # 每个注入器实例都有自己的 Jinja 环境，以保证线程安全
        self.jinja_env = Environment(loader=BaseLoader())
        self._initialize_jinja_globals()

    def _initialize_jinja_globals(self):
        """为 Jinja 环境设置全局函数，如 config()。"""
        try:
            config_service = service_registry.get_service_instance('config')
            # 使用 lambda 确保每次调用都获取最新的配置
            self.jinja_env.globals['config'] = lambda key, default=None: config_service.get(key, default)
        except Exception as e:
            logger.warning(f"无法获取ConfigService，Jinja2中的 'config()' 函数将不可用: {e}")
            self.jinja_env.globals['config'] = lambda key, default=None: default

    def execute(self, action_name: str, raw_params: Dict[str, Any]) -> Any:
        """
        执行一个 Action 的主入口。
        :param action_name: 要执行的 action 的名称。
        :param raw_params: 从 YAML 文件中读取的原始、未渲染的参数。
        :return: action 的执行结果。
        """
        action_name_lower = action_name.lower()
        action_def = ACTION_REGISTRY.get(action_name_lower)
        if not action_def:
            raise NameError(f"错误：找不到名为 '{action_name}' 的行为。")

        # 1. 渲染参数
        rendered_params = self._render_params(raw_params)

        # 2. 通过中间件处理链执行
        #    最终会调用 _final_action_executor
        return middleware_manager.process(
            action_def=action_def,
            context=self.context,
            params=rendered_params,
            final_handler=self._final_action_executor
        )

    def _final_action_executor(self, action_def: ActionDefinition, context: Context, params: Dict[str, Any]) -> Any:
        """
        中间件链的最终处理器，负责准备依赖并调用 action 函数。
        """
        # 3. 准备依赖注入的参数
        call_args = self._prepare_action_arguments(action_def, params)

        # 4. 最终调用
        return action_def.func(**call_args)

    def _prepare_action_arguments(self, action_def: ActionDefinition, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据 Action 的函数签名，准备所有需要注入的参数。
        """
        sig = action_def.signature
        call_args = {}
        service_deps = action_def.service_deps

        for param_name, param_spec in sig.parameters.items():
            # 跳过 *args 和 **kwargs
            if param_spec.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue

            # 优先注入框架保留字和依赖的服务
            if param_name in service_deps:
                fqsn = service_deps[param_name]
                try:
                    call_args[param_name] = service_registry.get_service_instance(fqsn)
                    continue
                except Exception as e:
                    raise RuntimeError(f"为Action '{action_def.name}' 注入服务 '{fqsn}' 失败: {e}") from e
            elif param_name == 'context':
                call_args[param_name] = self.context
                continue
            elif param_name == 'persistent_context':
                call_args[param_name] = self.context.get('persistent_context')
                continue
            elif param_name == 'engine':
                call_args[param_name] = self.engine
                continue

            # 然后从渲染后的参数中取值
            if param_name in params:
                call_args[param_name] = params[param_name]
                continue

            # 再次尝试从上下文中注入（用于未在 params 中显式传递的变量）
            injected_value = self.context.get(param_name)
            if injected_value is not None:
                call_args[param_name] = injected_value
                continue

            # 最后使用默认值
            if param_spec.default is not inspect.Parameter.empty:
                call_args[param_name] = param_spec.default
                continue

            # 如果都没有，则抛出错误
            raise ValueError(f"执行行为 '{action_def.name}' 时缺少必要参数: '{param_name}'")

        return call_args

    def _render_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        递归渲染参数字典中的所有值。
        """
        rendered_params = {}
        # 渲染时使用当前上下文的所有数据
        context_data = self.context._data.copy()
        for key, value in params.items():
            rendered_params[key] = self._render_value(value, context_data)
        return rendered_params

    def _render_value(self, value: Any, context_data: Dict[str, Any]) -> Any:
        """
        【修正版】渲染单个值。
        当遇到 UndefinedError 时，返回 None，以确保在 'if' 条件中被评估为 False。
        """
        if isinstance(value, str):
            if "{{" not in value and "{%" not in value:
                return value

            is_pure_expression = value.startswith("{{") and value.endswith("}}")

            try:
                template = self.jinja_env.from_string(value)
                rendered_string = template.render(context_data)

                if is_pure_expression:
                    try:
                        # 尝试将 "True", "False", "None" 等字符串正确转换为布尔/None
                        if rendered_string.lower() in ('true', 'false', 'none'):
                             return literal_eval(rendered_string.capitalize())
                        return literal_eval(rendered_string)
                    except (ValueError, SyntaxError, MemoryError, TypeError):
                        return rendered_string
                else:
                    return rendered_string
            except UndefinedError as e:
                # 【修正】当变量未定义时，返回 None 而不是原始字符串
                logger.warning(f"渲染模板 '{value}' 时出错: {e.message}。返回 None。")
                return None
            except Exception as e:
                logger.error(f"渲染Jinja2模板 '{value}' 时发生严重错误: {e}")
                return None

        elif isinstance(value, dict):
            return {k: self._render_value(v, context_data) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._render_value(item, context_data) for item in value]
        else:
            return value
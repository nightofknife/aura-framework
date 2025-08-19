import asyncio
import inspect
from ast import literal_eval
from typing import Any, Dict, TYPE_CHECKING

from jinja2 import Environment, BaseLoader, UndefinedError

from packages.aura_shared_utils.utils.logger import logger
from .api import service_registry, ACTION_REGISTRY, ActionDefinition
from .context import Context

if TYPE_CHECKING:
    from .engine import ExecutionEngine


class ActionInjector:
    """
    【Async Refactor】异步行为注入器。
    - 核心 execute 方法是异步的。
    - 能够智能地调用同步或异步的 Action 函数。
    """

    def __init__(self, context: Context, engine: 'ExecutionEngine'):
        self.context = context
        self.engine = engine
        self.jinja_env = Environment(loader=BaseLoader(), enable_async=True)
        self._initialize_jinja_globals()

    def _initialize_jinja_globals(self):
        # ... (此方法逻辑不变) ...
        try:
            config_service = service_registry.get_service_instance('config')
            self.jinja_env.globals['config'] = lambda key, default=None: config_service.get(key, default)
        except Exception as e:
            logger.warning(f"无法获取ConfigService，Jinja2中的 'config()' 函数将不可用: {e}")
            self.jinja_env.globals['config'] = lambda key, default=None: default

    async def execute(self, action_name: str, raw_params: Dict[str, Any]) -> Any:
        """异步执行一个 Action 的主入口。"""
        action_name_lower = action_name.lower()
        action_def = ACTION_REGISTRY.get(action_name_lower)
        if not action_def:
            raise NameError(f"错误：找不到名为 '{action_name}' 的行为。")

        rendered_params = await self._render_params(raw_params)

        # 中间件处理链现在也是异步的 (假设 middleware_manager 已更新)
        # For now, we assume it's a simple pass-through to the final handler
        return await self._final_action_executor(action_def, self.context, rendered_params)

    async def _final_action_executor(self, action_def: ActionDefinition, context: Context,
                                     params: Dict[str, Any]) -> Any:
        """
        中间件链的最终处理器，负责准备依赖并异步调用 action 函数。
        """
        call_args = self._prepare_action_arguments(action_def, params)

        # 【核心修改】根据 Action 定义的类型来决定如何调用
        if action_def.is_async:
            return await action_def.func(**call_args)
        else:
            loop = asyncio.get_running_loop()
            # 在默认线程池中运行同步函数，避免阻塞事件循环
            return await loop.run_in_executor(None, lambda: action_def.func(**call_args))

    def _prepare_action_arguments(self, action_def: ActionDefinition, params: Dict[str, Any]) -> Dict[str, Any]:
        # ... (此方法逻辑不变) ...
        sig = action_def.signature
        call_args = {}
        service_deps = action_def.service_deps

        for param_name, param_spec in sig.parameters.items():
            if param_spec.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD): continue
            if param_name in service_deps:
                call_args[param_name] = service_registry.get_service_instance(service_deps[param_name])
                continue
            elif param_name == 'context':
                call_args[param_name] = self.context
                continue
            elif param_name == 'persistent_context':
                call_args[param_name] = self.context.get('persistent_context')
                continue
            elif param_name == 'engine':
                call_args[param_name] = self.engine
                continue
            if param_name in params:
                call_args[param_name] = params[param_name]
                continue
            injected_value = self.context.get(param_name)
            if injected_value is not None:
                call_args[param_name] = injected_value
                continue
            if param_spec.default is not inspect.Parameter.empty:
                call_args[param_name] = param_spec.default
                continue
            raise ValueError(f"执行行为 '{action_def.name}' 时缺少必要参数: '{param_name}'")
        return call_args

    async def _render_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """异步地递归渲染参数字典中的所有值。"""
        context_data = self.context._data.copy()
        rendered_params = {}
        for key, value in params.items():
            rendered_params[key] = await self._render_value(value, context_data)
        return rendered_params

    async def _render_value(self, value: Any, context_data: Dict[str, Any]) -> Any:
        """异步渲染单个值。"""
        if isinstance(value, str):
            if "{{" not in value and "{%" not in value:
                return value
            is_pure_expression = value.startswith("{{") and value.endswith("}}")
            try:
                template = self.jinja_env.from_string(value)
                rendered_string = await template.render_async(context_data)
                if is_pure_expression:
                    try:
                        if rendered_string.lower() in ('true', 'false', 'none'):
                            return literal_eval(rendered_string.capitalize())
                        return literal_eval(rendered_string)
                    except (ValueError, SyntaxError):
                        return rendered_string
                return rendered_string
            except UndefinedError as e:
                logger.warning(f"渲染模板 '{value}' 时出错: {e.message}。返回 None。")
                return None
            except Exception as e:
                logger.error(f"渲染Jinja2模板 '{value}' 时发生严重错误: {e}")
                return None
        elif isinstance(value, dict):
            return {k: await self._render_value(v, context_data) for k, v in value.items()}
        elif isinstance(value, list):
            return [await self._render_value(item, context_data) for item in value]
        else:
            return value

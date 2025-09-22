import asyncio
import inspect
import contextvars
from functools import partial
from typing import Any, Dict, TYPE_CHECKING

from jinja2 import Environment, BaseLoader, UndefinedError
from pydantic import BaseModel, ValidationError

from packages.aura_core.logger import logger
from .api import service_registry, ACTION_REGISTRY, ActionDefinition
from .context import Context

if TYPE_CHECKING:
    from .engine import ExecutionEngine


class ActionInjector:
    """
    【Refactored】负责解析和执行单个 Action。
    - 修正了参数渲染和注入逻辑。
    - 简化了模板渲染，移除了不安全的 literal_eval。
    - 明确了参数解析的优先级。
    """

    def __init__(self, context: Context, engine: 'ExecutionEngine'):
        self.context = context
        self.engine = engine
        self.jinja_env = Environment(loader=BaseLoader(), enable_async=True)
        self._initialize_jinja_globals()

    def _initialize_jinja_globals(self):
        """初始化 Jinja2 环境中的全局函数。"""

        # 定义一个异步的 config 函数
        async def get_config(key: str, default: Any = None) -> Any:
            try:
                config_service = service_registry.get_service_instance('config')
                return config_service.get(key, default)
            except Exception as e:
                logger.warning(f"Jinja2 'config()' 函数无法获取ConfigService: {e}")
                return default

        self.jinja_env.globals['config'] = get_config

    async def execute(self, action_name: str, raw_params: Dict[str, Any]) -> Any:
        """
        核心执行入口：获取 Action 定义，渲染参数，并调用执行器。
        """
        action_def = ACTION_REGISTRY.get(action_name.lower())
        if not action_def:
            raise NameError(f"错误：找不到名为 '{action_name}' 的行为。")

        # 1. 渲染用户在 YAML 中提供的原始参数
        rendered_params = await self._render_params(raw_params)

        # 2. 准备最终的调用参数，并执行 Action
        return await self._final_action_executor(action_def, rendered_params)

    async def _final_action_executor(self, action_def: ActionDefinition, params: Dict[str, Any]) -> Any:
        """
        准备参数并以正确的方式（同步/异步）执行 Action 函数。
        """
        call_args = self._prepare_action_arguments(action_def, params)

        if action_def.is_async:
            return await action_def.func(**call_args)

        loop = asyncio.get_running_loop()
        cv_context = contextvars.copy_context()

        def thread_wrapper():
            # 保持 ContextVar，并执行同步 Action
            return cv_context.run(lambda: action_def.func(**call_args))

        return await loop.run_in_executor(None, thread_wrapper)

    def _prepare_action_arguments(self, action_def: ActionDefinition, rendered_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        【Refactored】准备 Action 的最终调用参数。
        """
        sig = action_def.signature
        call_args = {}
        params_consumed_by_model = False

        pydantic_param_name = None
        pydantic_model_class = None
        for name, param_spec in sig.parameters.items():
            if inspect.isclass(param_spec.annotation) and issubclass(param_spec.annotation, BaseModel):
                pydantic_param_name = name
                pydantic_model_class = param_spec.annotation
                break

        if pydantic_param_name and pydantic_model_class:
            try:
                call_args[pydantic_param_name] = pydantic_model_class(**rendered_params)
                params_consumed_by_model = True
            except ValidationError as e:
                error_msg = (
                    f"执行行为 '{action_def.name}' 时参数验证失败。\n"
                    f"YAML中的参数无法匹配 '{pydantic_model_class.__name__}' 模型。\n"
                    f"详情:\n{e}"
                )
                logger.error(error_msg)
                raise ValueError(error_msg) from e

        for param_name, param_spec in sig.parameters.items():
            if param_name == pydantic_param_name:
                continue
            if param_spec.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if param_name in action_def.service_deps:
                call_args[param_name] = service_registry.get_service_instance(action_def.service_deps[param_name])
                continue
            if param_name == 'context':
                call_args[param_name] = self.context
                continue
            if param_name == 'persistent_context':
                call_args[param_name] = self.context.get('persistent_context')
                continue
            if param_name == 'engine':
                call_args[param_name] = self.engine
                continue
            if not params_consumed_by_model and param_name in rendered_params:
                call_args[param_name] = rendered_params[param_name]
                continue
            context_value = self.context.get(param_name)
            if context_value is not None:
                call_args[param_name] = context_value
                continue
            if param_spec.default is not inspect.Parameter.empty:
                continue
            raise ValueError(f"执行行为 '{action_def.name}' 时缺少必要参数: '{param_name}'")

        return call_args

    async def _render_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        context_data = self.context._data
        return {key: await self._render_value(value, context_data) for key, value in params.items()}

    async def _render_value(self, value: Any, context_data: Dict[str, Any]) -> Any:
        if isinstance(value, str):
            if "{{" not in value and "{%" not in value:
                return value
            try:
                template = self.jinja_env.from_string(value)
                return await template.render_async(context_data)
            except UndefinedError as e:
                logger.warning(f"渲染模板 '{value}' 时出错: {e.message}。返回 None。")
                return None
            except Exception as e:
                logger.error(f"渲染模板 '{value}' 时发生错误: {e}")
                return None
        if isinstance(value, dict):
            return {k: await self._render_value(v, context_data) for k, v in value.items()}
        if isinstance(value, list):
            return [await self._render_value(item, context_data) for item in value]
        return value

    async def render_return_value(self, template_value: Any) -> Any:
        rendered_value = await self._render_value(template_value, self.context._data)
        if isinstance(rendered_value, str):
            import ast
            try:
                return ast.literal_eval(rendered_value)
            except (ValueError, SyntaxError, TypeError):
                return rendered_value
        return rendered_value

# packages/aura_core/action_injector.py

import asyncio
import inspect
import contextvars
from typing import Any, Dict, TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from packages.aura_core.logger import logger
from .api import service_registry, ACTION_REGISTRY, ActionDefinition
from .context import ExecutionContext
from .template_renderer import TemplateRenderer

if TYPE_CHECKING:
    from .engine import ExecutionEngine


class ActionInjector:
    """
    [REWRITTEN] 负责解析和执行单个Action。
    - 使用传入的TemplateRenderer进行参数渲染。
    - 从ExecutionContext注入依赖。
    """

    def __init__(self, context: ExecutionContext, engine: 'ExecutionEngine', renderer: TemplateRenderer):
        self.context = context
        self.engine = engine
        self.renderer = renderer

    async def execute(self, action_name: str, raw_params: Dict[str, Any]) -> Any:
        """
        核心执行入口：获取Action定义，渲染参数，并调用执行器。
        """
        action_def = ACTION_REGISTRY.get(action_name.lower())
        if not action_def:
            raise NameError(f"错误：找不到名为 '{action_name}' 的行为。")

        # 1. 使用新的渲染器渲染参数
        rendered_params = await self.renderer.render(raw_params)

        # 2. 准备最终的调用参数，并执行Action
        return await self._final_action_executor(action_def, rendered_params)

    async def _final_action_executor(self, action_def: ActionDefinition, params: Dict[str, Any]) -> Any:
        """
        准备参数并以正确的方式（同步/异步）执行Action函数。
        """
        call_args = self._prepare_action_arguments(action_def, params)

        if action_def.is_async:
            return await action_def.func(**call_args)

        loop = asyncio.get_running_loop()
        cv_context = contextvars.copy_context()

        # 使用lambda来捕获正确的call_args
        return await loop.run_in_executor(None, lambda: cv_context.run(action_def.func, **call_args))

    def _prepare_action_arguments(self, action_def: ActionDefinition, rendered_params: Dict[str, Any]) -> Dict[
        str, Any]:
        """
        [MODIFIED] 准备Action的最终调用参数，不再从旧context中获取。
        """
        sig = action_def.signature
        call_args = {}

        # Pydantic模型参数处理 (不变)
        pydantic_param_name = None
        pydantic_model_class = None
        for name, param_spec in sig.parameters.items():
            if inspect.isclass(param_spec.annotation) and issubclass(param_spec.annotation, BaseModel):
                pydantic_param_name = name
                pydantic_model_class = param_spec.annotation
                break

        if pydantic_param_name and pydantic_model_class:
            try:
                # Pydantic模型使用渲染后的参数进行实例化
                call_args[pydantic_param_name] = pydantic_model_class(**rendered_params)
                # 将所有参数视为已被模型消耗
                rendered_params = {}
            except ValidationError as e:
                error_msg = f"执行行为 '{action_def.name}' 时参数验证失败: {e}"
                logger.error(error_msg)
                raise ValueError(error_msg) from e

        # 注入其他依赖
        for param_name, param_spec in sig.parameters.items():
            if param_name in call_args:
                continue
            if param_spec.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue

            # 注入服务
            if param_name in action_def.service_deps:
                call_args[param_name] = service_registry.get_service_instance(action_def.service_deps[param_name])
                continue

            # 注入ExecutionContext
            if param_name == 'context' or param_spec.annotation is ExecutionContext:
                call_args[param_name] = self.context
                continue

            # 注入引擎
            if param_name == 'engine':
                call_args[param_name] = self.engine
                continue

            # 从渲染后的参数中获取值
            if param_name in rendered_params:
                call_args[param_name] = rendered_params[param_name]
                continue

            # 检查是否有默认值
            if param_spec.default is not inspect.Parameter.empty:
                continue

            # 如果都没有，则缺少必要参数
            raise ValueError(f"执行行为 '{action_def.name}' 时缺少必要参数: '{param_name}'")

        return call_args


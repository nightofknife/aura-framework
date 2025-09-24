# packages/aura_core/action_injector.py (FINAL CLEANED VERSION)

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
    负责解析和执行单个Action。
    - 使用传入的TemplateRenderer进行参数渲染。
    - 从ExecutionContext和预置服务中注入依赖。
    """

    def __init__(self, context: ExecutionContext, engine: 'ExecutionEngine', renderer: TemplateRenderer, services: Dict[str, Any]):
        self.context = context
        self.engine = engine
        self.renderer = renderer
        self.services = services

    async def execute(self, action_name: str, raw_params: Dict[str, Any]) -> Any:
        """
        执行一个Action的核心入口。
        1. 查找Action定义。
        2. 使用缓存的作用域渲染参数。
        3. 准备所有调用参数（包括服务注入）。
        4. 根据Action是同步还是异步，选择正确的执行方式。
        """
        action_def = ACTION_REGISTRY.get(action_name)
        if not action_def:
            raise ValueError(f"Action '{action_name}' not found.")

        # 步骤 2: 渲染参数
        render_scope = await self.renderer.get_render_scope()
        rendered_params = await self.renderer.render(raw_params, scope=render_scope)

        # 步骤 3: 准备最终调用参数
        call_args = self._prepare_action_arguments(action_def, rendered_params)

        loop = asyncio.get_running_loop()

        # 步骤 4: 执行
        if action_def.is_async:
            # 对于异步函数，直接在当前（正确的）上下文中执行
            return await action_def.func(**call_args)
        else:
            # 对于同步函数，使用标准模式将其放入线程池执行，并传递上下文
            context_snapshot = contextvars.copy_context()
            return await loop.run_in_executor(
                None,
                lambda: context_snapshot.run(action_def.func, **call_args)
            )

    def _prepare_action_arguments(self, action_def: ActionDefinition, rendered_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        准备Action的最终调用参数，注入服务和框架对象。
        """
        sig = action_def.signature
        call_args = {}

        # Pydantic模型参数处理
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

            # 注入服务，使用 self.services
            if param_name in action_def.service_deps:
                service_fqid = action_def.service_deps[param_name]

                # 优先从已经实例化的 services 字典中获取
                # 注意：这里的 service_fqid 实际上是别名，因为 service_deps 的 key 是参数名（别名）
                # 我们需要检查 self.services 中是否有这个别名
                if service_fqid in self.services:
                    call_args[param_name] = self.services[service_fqid]
                else:
                    # 如果服务不在已实例化的字典中，尝试从注册表动态获取
                    logger.warning(f"服务 '{service_fqid}' 未在启动时预实例化，尝试动态获取。")
                    service_instance = service_registry.get_service_instance(service_fqid)
                    self.services[service_fqid] = service_instance  # 缓存起来供后续使用
                    call_args[param_name] = service_instance
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

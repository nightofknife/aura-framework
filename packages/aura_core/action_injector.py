# -*- coding: utf-8 -*-
"""Action 注入器，负责解析和执行单个 Action。

该模块的核心是 `ActionInjector` 类，它处理 Action 执行的整个生命周期：
1.  **依赖注入**: 根据 Action 函数签名，自动注入所需的服务、执行上下文（ExecutionContext）
    以及执行引擎（ExecutionEngine）实例。
2.  **参数渲染**: 使用模板引擎（TemplateRenderer）渲染 Action 的输入参数，
    允许在参数中使用动态变量。
3.  **参数校验**: 如果 Action 的参数是 Pydantic 模型，会自动进行数据校验。
4.  **同步/异步执行**: 智能地处理同步和异步 Action，将同步函数放入线程池中
    执行以避免阻塞事件循环。
5.  **子任务执行**: 特殊处理 `aura.run_task` 这一内建 Action，以实现任务的嵌套调用。
"""
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
    """负责解析和执行单个 Action。

    此类在执行引擎（ExecutionEngine）的上下文中为每个 Action 实例化。
    它封装了执行一个 Action 所需的所有逻辑，包括参数渲染、依赖注入和
    对同步/异步函数的正确调用。

    Attributes:
        context (ExecutionContext): 当前任务的执行上下文。
        engine (ExecutionEngine): 父执行引擎实例。
        renderer (TemplateRenderer): 用于渲染参数的模板渲染器。
        services (Dict[str, Any]): 一个包含了已实例化服务的字典，用于依赖注入。
    """

    def __init__(self, context: ExecutionContext, engine: 'ExecutionEngine', renderer: TemplateRenderer, services: Dict[str, Any]):
        """初始化 ActionInjector。

        Args:
            context: 当前任务的执行上下文。
            engine: 父执行引擎实例。
            renderer: 用于渲染参数的模板渲染器。
            services: 已实例化的服务依赖字典。
        """
        self.context = context
        self.engine = engine
        self.renderer = renderer
        self.services = services

    async def execute(self, action_name: str, raw_params: Dict[str, Any]) -> Any:
        """执行一个 Action 的核心入口。

        此方法按以下步骤执行一个 Action：
        1. 查找 Action 的定义。
        2. 使用模板渲染器和当前作用域渲染输入参数。
        3. 准备所有调用参数，包括注入服务和框架对象。
        4. 根据 Action 是同步还是异步，选择正确的执行方式。

        Args:
            action_name: 要执行的 Action 的名称 (FQID)。
            raw_params: 从 Plan 文件中读取的原始、未经渲染的参数字典。

        Returns:
            Action 函数的返回值。

        Raises:
            ValueError: 如果找不到 Action 定义或缺少必要参数。
            TypeError: 如果 `aura.run_task` 的 `inputs` 参数类型不正确。
        """
        if action_name == "aura.run_task":
            return await self._execute_run_task(raw_params)

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

    async def _execute_run_task(self, raw_params: Dict[str, Any]) -> Any:
        """专门处理内建的 `aura.run_task` Action。

        此方法通过调用 Orchestrator 来执行一个子任务，是实现多节点循环和
        任务复用的核心机制。

        Args:
            raw_params: `aura.run_task` Action 的原始参数。

        Returns:
            子任务执行完毕后的框架数据 (`framework_data`)。

        Raises:
            ValueError: 如果缺少 `task_name` 参数。
            TypeError: 如果 `inputs` 参数不是一个字典。
            Exception: 如果子任务执行失败，则重新抛出异常。
        """
        logger.info(f"Executing sub-task via aura.run_task...")

        # 步骤 1: 渲染参数
        render_scope = await self.renderer.get_render_scope()
        rendered_params = await self.renderer.render(raw_params, scope=render_scope)

        # 步骤 2: 验证和提取参数
        task_name = rendered_params.get('task_name')
        if not task_name:
            raise ValueError("aura.run_task action requires a 'task_name' parameter.")

        sub_task_inputs = rendered_params.get('inputs', {})
        if not isinstance(sub_task_inputs, dict):
            raise TypeError(f"aura.run_task 'inputs' parameter must be a dictionary.")

        # 步骤 3: 获取 Orchestrator 实例
        orchestrator = self.engine.orchestrator

        # 步骤 4: 调用 Orchestrator 执行子任务
        tfr = await orchestrator.execute_task(
            task_name_in_plan=task_name,
            inputs=sub_task_inputs
        )

        # 步骤 5: 处理子任务结果
        if tfr.get('status') in ('FAILED', 'ERROR'):
            error_info = tfr.get('error', {'message': 'Unknown error in sub-task.'})
            raise Exception(f"Sub-task '{task_name}' failed. Reason: {error_info}")

        # 返回子任务的完整框架数据，允许父任务访问其内部状态
        return tfr.get('framework_data')

    def _prepare_action_arguments(self, action_def: ActionDefinition, rendered_params: Dict[str, Any]) -> Dict[str, Any]:
        """准备 Action 的最终调用参数，处理依赖注入和参数映射。

        此方法负责：
        - 如果 Action 期望一个 Pydantic 模型，则用渲染后的参数实例化该模型。
        - 注入 `service` 依赖。
        - 注入 `ExecutionContext` 和 `ExecutionEngine` 实例。
        - 从 `rendered_params` 中匹配常规参数。

        Args:
            action_def: 要执行的 Action 的定义。
            rendered_params: 已经过模板渲染的参数字典。

        Returns:
            一个字典，包含了调用 Action 函数所需的所有参数名和值。

        Raises:
            ValueError: 如果参数校验失败或缺少必要参数。
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

                if service_fqid in self.services:
                    call_args[param_name] = self.services[service_fqid]
                else:
                    logger.warning(f"服务 '{service_fqid}' 未在启动时预实例化，尝试动态获取。")
                    service_instance = service_registry.get_service_instance(service_fqid)
                    self.services[service_fqid] = service_instance
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

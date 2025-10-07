# packages/aura_core/action_injector.py (FINAL CLEANED VERSION)
"""
定义了 ActionInjector 类，负责最终执行单个 Action。

该模块是 Aura 框架中行为（Action）执行的核心环节。`ActionInjector` 的主要职责包括：
1.  **参数渲染**: 使用 `TemplateRenderer` 对从任务定义中传入的原始参数进行渲染，解析如 `{{ nodes.xxx.output }}` 这样的模板。
2.  **依赖注入**: 自动将已注册的服务（Services）、当前的 `ExecutionContext`、以及父级 `ExecutionEngine` 注入到 Action 函数的对应参数中。
3.  **Pydantic 模型验证**: 如果 Action 的参数被定义为一个 Pydantic 模型，`ActionInjector` 会用渲染后的参数实例化该模型，从而实现自动类型转换和验证。
4.  **同步/异步执行**: 透明地处理同步和异步 Action，将同步函数安全地在线程池中执行，避免阻塞事件循环。
5.  **特殊任务处理**: 内置对 `aura.run_task` 这一特殊 Action 的处理逻辑，通过 `Orchestrator` 实现子任务的调用，这是实现循环和任务复用的关键。
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
    """
    负责解析和执行单个 Action。

    该类是 Action 执行的最终处理器。它整合了参数渲染、依赖注入和实际的函数调用逻辑。
    每个 `ExecutionEngine` 在执行一个步骤（Step）时，都会创建一个 `ActionInjector` 实例。

    Attributes:
        context (ExecutionContext): 当前任务的执行上下文。
        engine (ExecutionEngine): 创建此注入器的父级执行引擎。
        renderer (TemplateRenderer): 用于渲染 Action 参数的模板渲染器。
        services (Dict[str, Any]): 一个包含预实例化服务的字典，用于依赖注入。
    """

    def __init__(self, context: ExecutionContext, engine: 'ExecutionEngine', renderer: TemplateRenderer, services: Dict[str, Any]):
        """
        初始化 ActionInjector。

        Args:
            context (ExecutionContext): 当前任务的执行上下文。
            engine (ExecutionEngine): 父级执行引擎实例。
            renderer (TemplateRenderer): 用于参数渲染的渲染器实例。
            services (Dict[str, Any]): 预实例化的服务依赖字典。
        """
        self.context = context
        self.engine = engine
        self.renderer = renderer
        self.services = services

    async def execute(self, action_name: str, raw_params: Dict[str, Any]) -> Any:
        """
        执行一个 Action 的核心入口。

        此方法按顺序执行以下操作：
        1. 查找 Action 的定义。
        2. 如果是特殊的 `aura.run_task`，则委托给 `_execute_run_task` 处理。
        3. 使用 `TemplateRenderer` 渲染参数。
        4. 调用 `_prepare_action_arguments` 准备最终的调用参数，完成依赖注入。
        5. 检查 Action 是同步还是异步，并以适当的方式执行它（异步直接 await，同步在线程池中运行）。

        Args:
            action_name (str): 要执行的 Action 的完全限定名。
            raw_params (Dict[str, Any]): 来自任务定义的原始、未渲染的参数。

        Returns:
            Any: Action 函数的返回值。

        Raises:
            ValueError: 如果 Action 未在注册表中找到，或者参数准备过程中缺少必要参数。
            Exception: 如果执行 `aura.run_task` 的子任务失败，则重新引发子任务的异常。
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
        """
        使用 orchestrator 执行一个子任务。这是实现多节点循环和任务复用的核心。

        Args:
            raw_params (Dict[str, Any]): `aura.run_task` Action 的原始参数。

        Returns:
            Any: 子任务执行结果中的 `framework_data` 部分。

        Raises:
            ValueError: 如果 `task_name` 参数缺失。
            TypeError: 如果 `inputs` 参数不是一个字典。
            Exception: 如果子任务执行失败，则将失败原因包装成异常抛出。
        """
        logger.info(f"Executing sub-task via aura.run_task...")

        # 步骤 1: 渲染参数
        # 子任务的参数也需要渲染，因为它可能包含来自父任务的变量
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
        # 这是安全访问顶层服务的正确路径
        orchestrator = self.engine.orchestrator

        # 步骤 4: 调用 Orchestrator 执行子任务
        # 这是上下文传递的关键点：将计算好的 sub_task_inputs 传递给新任务
        tfr = await orchestrator.execute_task(
            task_name_in_plan=task_name,
            inputs=sub_task_inputs
        )

        # 步骤 5: 处理子任务结果
        # 如果子任务失败，则当前 action 也失败，并将错误信息向上传播
        if tfr.get('status') in ('FAILED', 'ERROR'):
            error_info = tfr.get('error', {'message': 'Unknown error in sub-task.'})
            raise Exception(f"Sub-task '{task_name}' failed. Reason: {error_info}")

        # 如果成功，将子任务的完整执行结果作为此 action 的返回值
        # 这使得父任务可以访问子任务的内部状态，例如：
        # {{ nodes.my_loop_node.output[0].nodes.sub_task_node.output }}
        return tfr.get('framework_data')

    def _prepare_action_arguments(self, action_def: ActionDefinition, rendered_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        准备 Action 的最终调用参数，注入服务和框架对象。

        此方法负责将渲染后的参数、服务依赖和框架内部对象（如 context）
        整合成一个字典，用于最终调用 Action 函数。

        Args:
            action_def (ActionDefinition): 要调用 Action 的定义对象。
            rendered_params (Dict[str, Any]): 已经过模板渲染的参数字典。

        Returns:
            Dict[str, Any]: 一个可以直接用于 `**` 解包调用的参数字典。

        Raises:
            ValueError: 如果 Pydantic 模型验证失败，或缺少必要的非默认参数。
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

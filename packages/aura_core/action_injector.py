# packages/aura_core/action_injector.py (Refactored)
import asyncio
import inspect
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
                # 假设 config_service.get 未来可能是异步的
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
        # JumpSignal 异常会自然地向上传播到 engine 层被捕获
        return await self._final_action_executor(action_def, rendered_params)

    async def _final_action_executor(self, action_def: ActionDefinition, params: Dict[str, Any]) -> Any:
        """
        准备参数并以正确的方式（同步/异步）执行 Action 函数。
        """
        # 准备最终传递给 action 函数的参数字典
        call_args = self._prepare_action_arguments(action_def, params)

        if action_def.is_async:
            return await action_def.func(**call_args)
        else:
            # 在线程池中执行同步函数，避免阻塞事件循环
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: action_def.func(**call_args))

    def _prepare_action_arguments(self, action_def: ActionDefinition, rendered_params: Dict[str, Any]) -> Dict[
        str, Any]:
        """
        【Refactored】准备 Action 的最终调用参数。
        此方法实现了清晰的参数解析优先级，并支持 Pydantic 模型注入。
        """
        sig = action_def.signature
        call_args = {}
        params_consumed_by_model = False

        # 检查是否有 Pydantic 模型参数
        pydantic_param_name = None
        pydantic_model_class = None
        for name, param_spec in sig.parameters.items():
            if inspect.isclass(param_spec.annotation) and issubclass(param_spec.annotation, BaseModel):
                pydantic_param_name = name
                pydantic_model_class = param_spec.annotation
                break

        # 如果存在 Pydantic 模型，则优先用它来消费所有渲染后的参数
        if pydantic_param_name and pydantic_model_class:
            try:
                call_args[pydantic_param_name] = pydantic_model_class(**rendered_params)
                params_consumed_by_model = True
            except ValidationError as e:
                error_msg = f"执行行为 '{action_def.name}' 时参数验证失败。\n" \
                            f"YAML中提供的参数无法匹配 '{pydantic_model_class.__name__}' 模型的定义。\n" \
                            f"错误详情:\n{e}"
                logger.error(error_msg)
                raise ValueError(error_msg) from e

        # 遍历函数签名中的所有参数，按优先级填充
        for param_name, param_spec in sig.parameters.items():
            # 如果已被 Pydantic 模型处理，则跳过
            if param_name == pydantic_param_name:
                continue

            # 忽略可变参数
            if param_spec.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue

            # 优先级 1: 服务依赖注入 (@requires_services)
            if param_name in action_def.service_deps:
                call_args[param_name] = service_registry.get_service_instance(action_def.service_deps[param_name])
                continue

            # 优先级 2: 框架核心对象注入
            if param_name == 'context':
                call_args[param_name] = self.context
                continue
            if param_name == 'persistent_context':
                call_args[param_name] = self.context.get('persistent_context')
                continue
            if param_name == 'engine':
                call_args[param_name] = self.engine
                continue

            # 优先级 3: 用户在 YAML `params` 中提供的值 (仅当未被Pydantic模型消费时)
            if not params_consumed_by_model and param_name in rendered_params:
                call_args[param_name] = rendered_params[param_name]
                continue

            # 优先级 4: 从当前上下文中查找同名变量
            context_value = self.context.get(param_name)
            if context_value is not None:
                call_args[param_name] = context_value
                continue

            # 优先级 5: 函数定义的默认值
            if param_spec.default is not inspect.Parameter.empty:
                # 这里不需要操作，因为 Python 调用时会自动处理
                continue

            # 如果到这里参数还未被赋值，说明缺少必要参数
            if param_name not in call_args:
                raise ValueError(f"执行行为 '{action_def.name}' 时缺少必要参数: '{param_name}'")

        return call_args

    async def _render_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """递归地渲染参数字典中的所有值。"""
        # 传递给 Jinja 的上下文数据
        context_data = self.context._data
        return {key: await self._render_value(value, context_data) for key, value in params.items()}

    async def _render_value(self, value: Any, context_data: Dict[str, Any]) -> Any:
        """
        【Refactored】渲染单个值。
        - 移除了 literal_eval，渲染结果忠于模板输出。
        - 简化了逻辑，只处理字符串、字典和列表。
        """
        if isinstance(value, str):
            # 仅当包含模板标记时才进行渲染
            if "{{" not in value and "{%" not in value:
                return value
            try:
                template = self.jinja_env.from_string(value)
                return await template.render_async(context_data)
            except UndefinedError as e:
                logger.warning(f"渲染模板 '{value}' 时出错: {e.message}。将返回 None。")
                return None
            except Exception as e:
                logger.error(f"渲染Jinja2模板 '{value}' 时发生严重错误: {e}")
                return None  # 返回 None 作为安全的默认值
        elif isinstance(value, dict):
            return {k: await self._render_value(v, context_data) for k, v in value.items()}
        elif isinstance(value, list):
            return [await self._render_value(item, context_data) for item in value]
        else:
            # 对于非字符串、字典、列表类型，直接返回值
            return value


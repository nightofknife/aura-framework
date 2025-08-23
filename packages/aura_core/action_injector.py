# packages/aura_core/action_injector.py (Stage 1 Refactor)
import asyncio
import inspect
from ast import literal_eval
from typing import Any, Dict, TYPE_CHECKING

from jinja2 import Environment, BaseLoader, UndefinedError
from pydantic import BaseModel, ValidationError

from packages.aura_core.logger import logger
from .api import service_registry, ACTION_REGISTRY, ActionDefinition, register_action
from .context import Context
from .engine import JumpSignal  # Import JumpSignal

if TYPE_CHECKING:
    from .engine import ExecutionEngine


# --- Built-in Flow Control Actions ---
# In a larger system, this could be in its own file and imported.

@register_action(name="flow.go_task", read_only=True)
def go_task(task_name: str):
    """
    A built-in action that immediately stops the current task and jumps to another.
    This action works by raising a special JumpSignal exception.
    The 'task_name' parameter should be the full task ID (e.g., 'plan_name/task_path/task_key').
    """
    if not task_name or not isinstance(task_name, str):
        raise ValueError("flow.go_task requires a non-empty string for the 'task_name' parameter.")
    raise JumpSignal(jump_type='go_task', target=task_name)


# --- ActionInjector Class ---

class ActionInjector:
    def __init__(self, context: Context, engine: 'ExecutionEngine'):
        self.context = context
        self.engine = engine
        self.jinja_env = Environment(loader=BaseLoader(), enable_async=True)
        self._initialize_jinja_globals()

    def _initialize_jinja_globals(self):
        try:
            config_service = service_registry.get_service_instance('config')
            self.jinja_env.globals['config'] = lambda key, default=None: config_service.get(key, default)
        except Exception as e:
            logger.warning(f"无法获取ConfigService，Jinja2中的 'config()' 函数将不可用: {e}")
            self.jinja_env.globals['config'] = lambda key, default=None: default

    async def execute(self, action_name: str, raw_params: Dict[str, Any]) -> Any:
        action_name_lower = action_name.lower()
        action_def = ACTION_REGISTRY.get(action_name_lower)
        if not action_def:
            raise NameError(f"错误：找不到名为 '{action_name}' 的行为。")

        rendered_params = await self._render_params(raw_params)

        # The JumpSignal must be caught at a higher level (Orchestrator).
        # The injector's job is just to execute it.
        return await self._final_action_executor(action_def, self.context, rendered_params)

    async def _final_action_executor(self, action_def: ActionDefinition, context: Context,
                                     params: Dict[str, Any]) -> Any:
        call_args = self._prepare_action_arguments(action_def, params)
        if action_def.is_async:
            return await action_def.func(**call_args)
        else:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: action_def.func(**call_args))

    def _prepare_action_arguments(self, action_def: ActionDefinition, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        【Pydantic Refactor】
        Prepares arguments for an action call.
        - NEW: If a parameter is type-hinted as a Pydantic BaseModel, it will be automatically
          instantiated and validated from the incoming `params` dictionary.
        - RETAINED: Continues to support service injection and individual parameter injection
          for backward compatibility.
        """
        sig = action_def.signature
        call_args = {}
        service_deps = action_def.service_deps

        # A flag to track if params have been consumed by a Pydantic model
        params_consumed = False

        for param_name, param_spec in sig.parameters.items():
            # --- Pydantic Model Injection Logic ---
            annotation = param_spec.annotation
            if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
                try:
                    # Instantiate the Pydantic model with the entire params dict
                    # This performs validation, type casting, and default value assignment.
                    call_args[param_name] = annotation(**params)
                    params_consumed = True
                    continue  # Move to the next parameter
                except ValidationError as e:
                    # Provide a developer-friendly error message
                    error_msg = f"执行行为 '{action_def.name}' 时参数验证失败。\n" \
                                f"YAML中提供的参数无法匹配 '{annotation.__name__}' 模型的定义。\n" \
                                f"错误详情:\n{e}"
                    logger.error(error_msg)
                    raise ValueError(error_msg) from e

            # --- Existing Injection Logic (Services, Context, etc.) ---
            if param_spec.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue

            if param_name in service_deps:
                call_args[param_name] = service_registry.get_service_instance(service_deps[param_name])
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

            # --- Individual Parameter Injection (only if not consumed by Pydantic) ---
            if not params_consumed:
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

            # If we are here, a required parameter is missing
            # But if a Pydantic model consumed the params, we shouldn't raise for individual ones
            if not params_consumed:
                raise ValueError(f"执行行为 '{action_def.name}' 时缺少必要参数: '{param_name}'")

        return call_args

    async def _render_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        context_data = self.context._data.copy()
        rendered_params = {}
        for key, value in params.items():
            rendered_params[key] = await self._render_value(value, context_data)
        return rendered_params

    async def _render_value(self, value: Any, context_data: Dict[str, Any]) -> Any:
        if isinstance(value, str):
            if "{{" not in value and "{%" not in value:
                return value
            is_pure_expression = value.startswith("{{") and value.endswith("}}")
            try:
                template = self.jinja_env.from_string(value)
                rendered_string = await template.render_async(context_data)
                if is_pure_expression:
                    try:
                        # Safely evaluate common Python literals
                        if rendered_string.lower() in ('true', 'false', 'none'):
                            return literal_eval(rendered_string.capitalize())
                        return literal_eval(rendered_string)
                    except (ValueError, SyntaxError):
                        # Not a literal, return the rendered string itself
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


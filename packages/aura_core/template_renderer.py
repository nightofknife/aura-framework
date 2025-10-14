# packages/aura_core/template_renderer.py

from typing import Any, Dict, Optional

from jinja2 import BaseLoader, UndefinedError
from jinja2.nativetypes import NativeEnvironment

from packages.aura_core.context import ExecutionContext
from packages.aura_core.logger import logger
from packages.aura_core.state_store_service import StateStoreService


class TemplateRenderer:
    """
    负责使用新的多层上下文模型渲染Jinja2模板。
    """

    def __init__(self, execution_context: ExecutionContext, state_store: StateStoreService):
        self.execution_context = execution_context
        self.state_store = state_store
        self.jinja_env = NativeEnvironment(loader=BaseLoader(), enable_async=True)

    async def get_render_scope(self) -> Dict[str, Any]:
        """
        构建用于Jinja2渲染的完整数据作用域。
        """
        state_data = {}
        if self.state_store:
            if not getattr(self.state_store, '_initialized', False):
                await self.state_store.initialize()
            state_data = await self.state_store.get_all_data()

        exec_data = self.execution_context.data

        # [MODIFIED] 将 inputs 和 loop 添加到渲染作用域
        return {
            "state": state_data,
            "initial": exec_data.get("initial", {}),
            "inputs": exec_data.get("inputs", {}),
            "loop": exec_data.get("loop", {}),
            "nodes": exec_data.get("nodes", {})
        }

    async def render(self, value: Any, scope: Optional[Dict[str, Any]] = None) -> Any:
        """
        递归地渲染一个值（字符串、字典、列表）。
        如果提供了 scope，则直接使用；否则，动态构建一次。
        """
        if scope is None:
            try:
                scope = await self.get_render_scope()
            except Exception as e:
                logger.error(f"构建渲染作用域时失败: {e}", exc_info=True)
                scope = {}

        return await self._render_recursive(value, scope)

    async def _render_recursive(self, value: Any, scope: Dict[str, Any]) -> Any:
        if isinstance(value, str):
            if "{{" not in value and "{%" not in value:
                return value
            try:
                template = self.jinja_env.from_string(value)
                return await template.render_async(scope)
            except UndefinedError as e:
                logger.warning(f"渲染模板 '{value}' 时出错: 变量或属性未定义 - {e.message}。返回 None。")
                return None
            except Exception as e:
                logger.error(f"渲染模板'{value}'时发生未知错误: {e}", exc_info=True)
                return value

        if isinstance(value, dict):
            return {k: await self._render_recursive(v, scope) for k, v in value.items()}

        if isinstance(value, list):
            return [await self._render_recursive(item, scope) for item in value]

        return value

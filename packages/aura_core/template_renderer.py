# packages/aura_core/template_renderer.py

from typing import Any, Dict

from jinja2 import Environment, BaseLoader, UndefinedError

from packages.aura_core.context import ExecutionContext
from packages.aura_core.logger import logger
from packages.aura_core.state_store_service import StateStoreService


class TemplateRenderer:
    """
    负责使用新的双层上下文模型渲染Jinja2模板。
    """

    def __init__(self, execution_context: ExecutionContext, state_store: StateStoreService):
        self.execution_context = execution_context
        self.state_store = state_store
        self.jinja_env = Environment(loader=BaseLoader(), enable_async=True)
        # 可以在这里添加全局函数，如 config()

    async def _get_render_scope(self) -> Dict[str, Any]:
        """构建用于Jinja2渲染的完整数据作用域。"""
        state_data = await self.state_store.get_all_data()
        exec_data = self.execution_context.data

        # 顶层命名空间: 'context', 'initial', 'nodes'
        return {
            "context": state_data,
            "initial": exec_data.get("initial", {}),
            "nodes": exec_data.get("nodes", {})
        }

    async def render(self, value: Any) -> Any:
        """
        递归地渲染一个值（字符串、字典、列表）。
        """
        scope = await self._get_render_scope()
        return await self._render_recursive(value, scope)

    async def _render_recursive(self, value: Any, scope: Dict[str, Any]) -> Any:
        if isinstance(value, str):
            if "{{" not in value and "{%" not in value:
                return value
            try:
                template = self.jinja_env.from_string(value)
                return await template.render_async(scope)
            except UndefinedError as e:
                logger.warning(f"渲染模板'{value}'时出错: {e.message}。返回None。")
                return None
            except Exception as e:
                logger.error(f"渲染模板'{value}'时发生未知错误: {e}", exc_info=True)
                return value  # 返回原始值以防万一

        if isinstance(value, dict):
            return {k: await self._render_recursive(v, scope) for k, v in value.items()}

        if isinstance(value, list):
            return [await self._render_recursive(item, scope) for item in value]

        return value


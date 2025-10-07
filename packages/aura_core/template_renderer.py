"""
定义了 `TemplateRenderer`，一个负责渲染 Jinja2 模板的异步组件。

该模块的核心是 `TemplateRenderer` 类，它能够利用多层次的上下文数据
（包括全局状态、任务初始数据、任务输入、循环变量和所有节点结果）来
异步地渲染字符串、字典或列表中的 Jinja2 模板。这是实现 Aura 框架
动态参数和数据流的核心。
"""
from typing import Any, Dict, Optional

from jinja2 import Environment, BaseLoader, UndefinedError

from packages.aura_core.context import ExecutionContext
from packages.aura_core.logger import logger
from packages.aura_core.state_store_service import StateStoreService


class TemplateRenderer:
    """
    负责使用多层上下文模型异步渲染 Jinja2 模板。
    """

    def __init__(self, execution_context: ExecutionContext, state_store: StateStoreService):
        """
        初始化模板渲染器。

        Args:
            execution_context (ExecutionContext): 当前任务的执行上下文，
                提供了 `initial`, `inputs`, `loop`, `nodes` 等数据源。
            state_store (StateStoreService): 全局状态存储服务，
                提供了 `state` 数据源。
        """
        self.execution_context = execution_context
        self.state_store = state_store
        self.jinja_env = Environment(loader=BaseLoader(), enable_async=True)

    async def get_render_scope(self) -> Dict[str, Any]:
        """
        构建用于 Jinja2 渲染的完整数据作用域。

        它会聚合来自 `StateStoreService` 的全局状态和来自 `ExecutionContext` 的
        所有层级的数据，形成一个统一的字典，作为模板渲染的上下文。

        Returns:
            Dict[str, Any]: 一个包含了所有可用数据的渲染作用域字典。
        """
        state_data = {}
        if self.state_store:
            # 确保状态存储已初始化
            if not getattr(self.state_store, '_initialized', False):
                await self.state_store.initialize()
            state_data = await self.state_store.get_all_data()

        exec_data = self.execution_context.data

        # 将所有数据源组合成一个作用域
        return {
            "state": state_data,
            "initial": exec_data.get("initial", {}),
            "inputs": exec_data.get("inputs", {}),
            "loop": exec_data.get("loop", {}),
            "nodes": exec_data.get("nodes", {})
        }

    async def render(self, value: Any, scope: Optional[Dict[str, Any]] = None) -> Any:
        """
        异步地、递归地渲染一个值（字符串、字典、列表）。

        如果提供了 `scope` 参数，则直接使用它进行渲染。否则，会先调用
        `get_render_scope` 方法动态构建一次作用域。

        Args:
            value (Any): 需要被渲染的值。
            scope (Optional[Dict[str, Any]]): 可选的、预先构建好的渲染作用域。

        Returns:
            Any: 渲染后的值。
        """
        if scope is None:
            try:
                scope = await self.get_render_scope()
            except Exception as e:
                logger.error(f"构建渲染作用域时失败: {e}", exc_info=True)
                scope = {}

        return await self._render_recursive(value, scope)

    async def _render_recursive(self, value: Any, scope: Dict[str, Any]) -> Any:
        """
        内部递归函数，用于深度渲染数据结构。

        - 如果值是字符串，则尝试作为 Jinja2 模板进行渲染。
        - 如果值是字典，则递归渲染其所有值。
        - 如果值是列表，则递归渲染其所有元素。
        - 其他类型的值将原样返回。

        Args:
            value (Any): 当前要渲染的值。
            scope (Dict[str, Any]): 渲染作用域。

        Returns:
            Any: 渲染后的值。
        """
        if isinstance(value, str):
            # 快速路径：如果字符串中不含模板标记，直接返回
            if "{{" not in value and "{%" not in value:
                return value
            try:
                template = self.jinja_env.from_string(value)
                return await template.render_async(scope)
            except UndefinedError as e:
                logger.warning(f"渲染模板 '{value}' 时出错: 变量或属性未定义 - {e.message}。将返回 None。")
                return None
            except Exception as e:
                logger.error(f"渲染模板 '{value}' 时发生未知错误: {e}", exc_info=True)
                return value  # 在未知错误时返回原始值

        if isinstance(value, dict):
            return {k: await self._render_recursive(v, scope) for k, v in value.items()}

        if isinstance(value, list):
            return [await self._render_recursive(item, scope) for item in value]

        return value

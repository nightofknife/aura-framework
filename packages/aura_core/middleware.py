"""
定义了 Aura 框架的中间件系统。

该模块提供了 `Middleware` 基类和一个 `MiddlewareManager`，共同实现了一个
“洋葱模型”的请求处理管道。这允许在核心行为（Action）执行之前和之后
注入可插拔的、可重用的逻辑，例如日志记录、性能监控、权限检查、数据转换等。

主要特性:
- **异步设计**: 完全兼容 `asyncio`，可以处理异步中间件。
- **向后兼容**: 能够透明地在线程池中运行旧的同步中间件，确保平滑过渡。
- **洋葱模型**: 请求从外层中间件依次传递到内层，响应再反向传出，
  每个中间件都有机会在请求处理前后执行代码。
- **全局单例**: 提供一个全局的 `middleware_manager` 实例，方便在整个应用中注册中间件。
"""
import asyncio
from functools import partial
from typing import Callable, List, Any, Dict, Awaitable

from packages.aura_core.api import ActionDefinition
from packages.aura_core.context import ExecutionContext
from packages.aura_core.logger import logger


class Middleware:
    """
    所有中间件的异步基类。

    开发者应该继承这个类并重写 `handle` 方法来实现自定义的中间件逻辑。
    """

    async def handle(self, action_def: ActionDefinition, context: ExecutionContext, params: Dict[str, Any],
                     next_handler: Callable[..., Awaitable[Any]]) -> Any:
        """
        处理一个 Action 的执行请求。

        这是一个模板方法，子类应该重写它。在方法实现中，开发者可以
        在调用 `next_handler` 之前执行前置逻辑（例如修改参数），在调用之后
        执行后置逻辑（例如格式化返回值）。

        Args:
            action_def (ActionDefinition): 正在执行的 Action 的定义。
            context (ExecutionContext): 当前的执行上下文。
            params (Dict[str, Any]): 传递给 Action 的参数。
            next_handler (Callable[..., Awaitable[Any]]): 一个可等待的调用，
                它代表了中间件链中的下一个处理器（可能是另一个中间件，也可能是
                最终的 Action 执行器）。必须使用 `await next_handler(...)` 来
                将控制权传递下去。

        Returns:
            Any: Action 的最终执行结果，可能已被中间件修改。
        """
        # 默认实现是直接调用并等待下一个处理器
        return await next_handler(action_def, context, params)


class MiddlewareManager:
    """
    管理和执行异步中间件链。

    它维护一个中间件列表，并负责按照“洋葱模型”将它们串联起来执行。
    这是一个全局单例，通过 `middleware_manager` 实例访问。
    """

    def __init__(self):
        """初始化一个空的中间件管理器。"""
        self._middlewares: List[Middleware] = []

    def add(self, middleware: Middleware):
        """
        添加一个中间件到链的末尾。

        Args:
            middleware (Middleware): 要添加的中间件实例。
        """
        self._middlewares.append(middleware)

    async def process(self, action_def: ActionDefinition, context: ExecutionContext, params: Dict[str, Any],
                      final_handler: Callable[..., Awaitable[Any]]) -> Any:
        """
        异步处理一个 Action 请求，让它依次通过所有已注册的中间件。

        此方法会从最后一个注册的中间件开始，反向构建一个嵌套的调用链。
        当最外层的处理器被调用时，请求会逐层向内传递，直到最终的
        `final_handler` 被执行，然后结果再逐层向外返回。

        它还特殊处理了同步的旧版中间件，将它们安全地在线程池中执行，
        以避免阻塞事件循环。

        Args:
            action_def (ActionDefinition): 正在执行的 Action 的定义。
            context (ExecutionContext): 当前的执行上下文。
            params (Dict[str, Any]): 传递给 Action 的参数。
            final_handler (Callable[..., Awaitable[Any]]): 位于中间件链
                最内层的最终处理器，通常是 `ActionInjector` 的执行方法。

        Returns:
            Any: 经过整个中间件链处理后的最终结果。
        """
        if not self._middlewares:
            return await final_handler(action_def, context, params)

        # 构建异步的调用链
        handler = final_handler
        for middleware in reversed(self._middlewares):
            # 将下一个处理器（无论是另一个中间件还是最终执行器）绑定到当前中间件的 handle 方法
            # 我们需要一个包装器来正确处理 partial 的异步调用
            async def wrapper(h: Callable, ad: ActionDefinition, ctx: ExecutionContext, p: Dict[str, Any], next_h: Callable) -> Any:
                # 检查 handle 是否是协程函数
                if asyncio.iscoroutinefunction(middleware.handle):
                    return await h(ad, ctx, p, next_h)
                else:
                    # 如果是同步的旧版中间件，在线程池中运行它
                    logger.debug(f"正在线程池中运行同步中间件: {middleware.__class__.__name__}")
                    loop = asyncio.get_running_loop()
                    # partial 将同步函数和其参数打包
                    sync_callable = partial(h, ad, ctx, p, lambda *a, **kw: asyncio.run_coroutine_threadsafe(next_h(*a, **kw), loop).result())
                    return await loop.run_in_executor(None, sync_callable)

            handler = partial(wrapper, middleware.handle, next_handler=handler)

        # 调用链的第一个处理器
        return await handler(action_def, context, params)


# 创建一个全局单例
middleware_manager = MiddlewareManager()
"""全局中间件管理器实例。"""

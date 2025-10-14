# -*- coding: utf-8 -*-
"""Aura 框架的中间件（Middleware）系统。

此模块提供了构建和管理中间件链的能力。中间件允许开发者在 Action
执行前后插入自定义逻辑，形成一个处理管道（pipeline）。这对于实现
横切关注点（cross-cutting concerns）非常有用，例如日志记录、权限校验、
性能监控、事务管理等，而无需修改 Action 本身的代码。
"""
import asyncio
from functools import partial
from typing import Callable, List, Any, Dict, Awaitable

from packages.aura_core.api import ActionDefinition
from packages.aura_core.context import Context
from packages.aura_core.logger import logger


class Middleware:
    """异步中间件的基类。

    所有自定义中间件都应继承自此类，并覆盖 `handle` 方法。
    """

    async def handle(self, action_def: ActionDefinition, context: Context, params: Dict[str, Any],
                     next_handler: Callable[..., Awaitable[Any]]) -> Any:
        """异步处理一个 Action 的执行。

        子类应在此方法中实现其逻辑。方法内部必须调用 `await next_handler(...)`
        来将控制权传递给链中的下一个中间件或最终的 Action 执行器。
        可以在调用 `next_handler` 前后执行自定义逻辑。

        Args:
            action_def: 正在被处理的 Action 的定义。
            context: 当前的执行上下文。
            params: 传递给 Action 的参数。
            next_handler: 一个可等待对象，调用它会触发下一个中间件或
                          最终的 Action 执行。

        Returns:
            Action 的执行结果。
        """
        # 默认实现是直接调用并等待下一个处理器
        return await next_handler(action_def, context, params)


class MiddlewareManager:
    """管理和执行异步中间件链。

    此类负责维护一个中间件列表，并能按照正确的顺序构建和执行
    一个异步的调用链。
    """

    def __init__(self):
        """初始化 MiddlewareManager。"""
        self._middlewares: List[Middleware] = []

    def add(self, middleware: Middleware):
        """添加一个中间件到链的末尾。

        Args:
            middleware: 要添加的中间件实例。
        """
        self._middlewares.append(middleware)

    async def process(self, action_def: ActionDefinition, context: Context, params: Dict[str, Any],
                      final_handler: Callable[..., Awaitable[Any]]) -> Any:
        """异步处理一个 Action，使其依次通过所有已注册的中间件。

        此方法会从最后一个中间件开始，反向构建一个嵌套的调用链，
        最终将 `final_handler` (即实际的 Action 执行器) 包裹在最内层。
        然后，它会调用链的第一个处理器来启动整个流程。

        它还特别处理了旧式的同步中间件，会将其在线程池中运行以保持
        整个流程的异步性。

        Args:
            action_def: 正在被处理的 Action 的定义。
            context: 当前的执行上下文。
            params: 传递给 Action 的参数。
            final_handler: 最终的 Action 执行器（一个异步函数）。

        Returns:
            经过所有中间件处理后的 Action 执行结果。
        """
        if not self._middlewares:
            return await final_handler(action_def, context, params)

        handler = final_handler
        for middleware in reversed(self._middlewares):
            # 将下一个处理器（无论是另一个中间件还是最终执行器）绑定到当前中间件的 handle 方法
            async def wrapper(h, ad, ctx, p, next_h):
                if asyncio.iscoroutinefunction(middleware.handle):
                    return await h(ad, ctx, p, next_h)
                else:
                    # 如果是同步的旧版中间件，在线程池中运行它
                    logger.debug(f"正在线程池中运行同步中间件: {middleware.__class__.__name__}")
                    loop = asyncio.get_running_loop()
                    sync_callable = partial(h, ad, ctx, p, lambda *a, **kw: asyncio.run_coroutine_threadsafe(next_h(*a, **kw), loop).result())
                    return await loop.run_in_executor(None, sync_callable)

            handler = partial(wrapper, middleware.handle, next_handler=handler)

        # 调用链的第一个处理器
        return await handler(action_def, context, params)


# 创建一个全局单例
middleware_manager = MiddlewareManager()

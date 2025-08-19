import asyncio
from functools import partial
from typing import Callable, List, Any, Dict, Awaitable

from packages.aura_core.api import ActionDefinition
from packages.aura_core.context import Context
from packages.aura_shared_utils.utils.logger import logger


class Middleware:
    """
    【Async Refactor】异步中间件基类。
    """

    async def handle(self, action_def: ActionDefinition, context: Context, params: Dict[str, Any],
                     next_handler: Callable[..., Awaitable[Any]]) -> Any:
        """
        异步处理一个Action的执行。
        :param next_handler: 一个 awaitable，调用下一个中间件或最终的Action执行器。
        """
        # 默认实现是直接调用并等待下一个处理器
        return await next_handler(action_def, context, params)


class MiddlewareManager:
    """
    【Async Refactor】管理和执行异步中间件链。
    """

    def __init__(self):
        self._middlewares: List[Middleware] = []

    def add(self, middleware: Middleware):
        """添加一个中间件到链的末尾。"""
        self._middlewares.append(middleware)

    async def process(self, action_def: ActionDefinition, context: Context, params: Dict[str, Any],
                      final_handler: Callable[..., Awaitable[Any]]) -> Any:
        """
        异步处理一个Action，依次通过所有中间件。
        """
        if not self._middlewares:
            return await final_handler(action_def, context, params)

        # 构建异步的调用链
        handler = final_handler
        for middleware in reversed(self._middlewares):
            # 将下一个处理器（无论是另一个中间件还是最终执行器）绑定到当前中间件的 handle 方法
            # 我们需要一个包装器来正确处理 partial 的异步调用
            async def wrapper(h, ad, ctx, p, next_h):
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

# packages/aura_core/middleware.py (Aura 3.0 - 阶段三)

from typing import Callable, List, Any, Dict
from functools import partial

# 导入框架核心定义
from packages.aura_core.api import ActionDefinition
from packages.aura_core.context import Context


class Middleware:
    """中间件基类。所有中间件都应继承此类并实现 handle 方法。"""
    def handle(self, action_def: ActionDefinition, context: Context, params: Dict[str, Any], next_handler: Callable) -> Any:
        """
        处理一个Action的执行。

        :param action_def: 正在执行的Action的定义对象。
        :param context: 当前的执行上下文。
        :param params: 传递给Action的参数。
        :param next_handler: 调用下一个中间件或最终Action执行器的句柄。
        :return: Action的执行结果。
        """
        # 默认实现是直接调用下一个处理器
        return next_handler(action_def, context, params)


class MiddlewareManager:
    """
    管理和执行中间件链。
    """
    def __init__(self):
        self._middlewares: List[Middleware] = []

    def add(self, middleware: Middleware):
        """添加一个中间件到链的末尾。"""
        self._middlewares.append(middleware)

    def process(self, action_def: ActionDefinition, context: Context, params: Dict[str, Any], final_handler: Callable) -> Any:
        """
        处理一个Action，依次通过所有中间件，最后由 final_handler 执行。

        :param action_def: 要执行的Action定义。
        :param context: 执行上下文。
        :param params: 传递给Action的参数。
        :param final_handler: 最终执行Action的函数。
        :return: Action的执行结果。
        """
        # 如果没有中间件，直接调用最终处理器
        if not self._middlewares:
            return final_handler(action_def, context, params)

        # 将中间件链反转，以便我们可以从第一个开始构建调用链
        # [m1, m2, m3] -> m1(m2(m3(final_handler)))
        handler = final_handler
        for middleware in reversed(self._middlewares):
            # 使用偏函数 (partial) 来固定 handler，为下一次迭代做准备
            handler = partial(middleware.handle, next_handler=handler)

        # 调用链的第一个处理器
        return handler(action_def, context, params)

# 创建一个全局单例
middleware_manager = MiddlewareManager()

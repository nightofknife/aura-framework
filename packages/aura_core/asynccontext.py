# packages/aura_core/asynccontext.py
"""
提供一个异步上下文管理器，用于安全地设置和恢复方案（Plan）的上下文。

该模块的核心是 `plan_context` 异步上下文管理器，它利用 `contextvars`
来临时设定当前正在执行的方案名称。这确保了在并发执行多个方案时，
每个任务都能正确地访问到其所属方案的配置和资源，避免了上下文混淆。
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from plans.aura_base.services.config_service import current_plan_name
from packages.aura_core.logger import logger


@asynccontextmanager
async def plan_context(plan_name: str) -> AsyncGenerator[None, None]:
    """
    一个异步上下文管理器，用于安全地设置和恢复当前方案的上下文变量。

    它会检查当前的 `current_plan_name` 上下文变量。如果变量的当前值与
    指定的 `plan_name` 不同，它会设置新值，并在退出上下文时恢复原值。
    如果值已经正确，则不执行任何操作。这确保了 `set` 和 `reset` 的
    调用总是平衡的，避免了上下文状态的意外泄露。

    使用示例:
        async with plan_context("my_awesome_plan"):
            # 在此代码块内，current_plan_name.get() 将返回 "my_awesome_plan"
            await do_something_related_to_plan()
        # 退出代码块后，current_plan_name 将恢复为之前的值。

    Args:
        plan_name (str): 要设置的方案名称。

    Yields:
        None: 不产生任何值。
    """
    token = None
    original_plan = current_plan_name.get()
    try:
        if original_plan != plan_name:
            token = current_plan_name.set(plan_name)
            logger.trace(f"方案上下文已切换: '{original_plan}' -> '{plan_name}'")
        yield
    finally:
        if token:
            current_plan_name.reset(token)
            logger.trace(f"方案上下文已恢复: '{plan_name}' -> '{original_plan}'")
# packages/aura_core/asynccontext.py

from contextlib import asynccontextmanager
from plans.aura_base.services.config_service import current_plan_name

@asynccontextmanager
async def plan_context(plan_name: str):
    """
    【新增】异步上下文管理器，确保 current_plan_name 的 set/reset 平衡。
    使用：在检查/执行前 async with plan_context(plan_name): ...
    """
    current = current_plan_name.get()
    if current != plan_name:
        token = current_plan_name.set(plan_name)
        try:
            yield
        finally:
            current_plan_name.reset(token)
            # 显式日志（可选，调试用）
            from packages.aura_core.logger import logger
            logger.debug(f"ContextVar 已重置为: '{current}'")
    else:
        # 已正确，无需 set
        yield
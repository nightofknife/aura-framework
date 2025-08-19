from pathlib import Path
from typing import Optional

from packages.aura_core.api import service_registry
from packages.aura_core.event_bus import Event
from packages.aura_shared_utils.utils.logger import logger
from .context import Context
from .persistent_context import PersistentContext


class ContextManager:
    """
    【Async Refactor】上下文管理器。
    创建上下文的过程现在是异步的，以支持异步加载持久化数据。
    """

    def __init__(self, plan_name: str, plan_path: Path):
        self.plan_name = plan_name
        self.plan_path = plan_path
        self.persistent_context_path = self.plan_path / 'persistent_context.json'

    async def create_context(self, task_id: str, triggering_event: Optional[Event] = None) -> Context:
        """
        为一次任务执行异步创建并初始化一个全新的上下文。
        """
        context = Context(triggering_event=triggering_event)

        # 异步加载并注入持久化上下文
        persistent_context = PersistentContext(str(self.persistent_context_path))
        # The initial load is sync, but we can make it async if needed for reloads
        # await persistent_context.load()
        context.set('persistent_context', persistent_context)
        for key, value in persistent_context.get_all_data().items():
            context.set(key, value)

        # 注入配置服务 (同步操作，无需修改)
        try:
            config_service = service_registry.get_service_instance('config')
            config_service.set_active_plan(self.plan_name)
            context.set('config', config_service.active_plan_config)
        except Exception:
            context.set('config', {})

        # 注入其他元数据 (同步操作，无需修改)
        context.set('log', logger)
        debug_dir = self.plan_path / 'debug_screenshots'
        debug_dir.mkdir(parents=True, exist_ok=True)
        context.set('debug_dir', str(debug_dir))
        context.set('__task_name__', task_id)
        context.set('__plan_name__', self.plan_name)
        if triggering_event:
            context.set('event', triggering_event)

        return context

    async def get_persistent_context_data(self) -> dict:
        """异步获取当前方案的持久化上下文数据。"""
        pc = PersistentContext(str(self.persistent_context_path))
        await pc.load()
        return pc.get_all_data()

    async def save_persistent_context_data(self, data: dict):
        """异步保存持久化上下文数据。"""
        pc = PersistentContext(str(self.persistent_context_path))
        pc._data.clear()
        for key, value in data.items():
            pc.set(key, value)
        await pc.save()

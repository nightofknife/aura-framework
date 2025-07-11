# packages/aura_core/context_manager.py (全新文件)

from pathlib import Path
from typing import Optional

from packages.aura_core.api import service_registry
from packages.aura_core.event_bus import Event
from packages.aura_shared_utils.utils.logger import logger
from .context import Context
from .persistent_context import PersistentContext


class ContextManager:
    """
    上下文管理器。
    负责为每次任务执行创建、初始化和管理上下文（Context），
    包括处理持久化上下文的加载和保存。
    """

    def __init__(self, plan_name: str, plan_path: Path):
        self.plan_name = plan_name
        self.plan_path = plan_path
        self.persistent_context_path = self.plan_path / 'persistent_context.json'

    def create_context(self, task_id: str, triggering_event: Optional[Event] = None) -> Context:
        """
        为一次任务执行创建并初始化一个全新的上下文。
        """
        # 1. 创建基础 Context 对象
        context = Context(triggering_event=triggering_event)

        # 2. 加载并注入持久化上下文
        persistent_context = PersistentContext(str(self.persistent_context_path))
        context.set('persistent_context', persistent_context)
        for key, value in persistent_context.get_all_data().items():
            context.set(key, value)

        # 3. 注入配置服务和方案配置
        try:
            config_service = service_registry.get_service_instance('config')
            config_service.set_active_plan(self.plan_name)
            context.set('config', config_service.active_plan_config)
        except Exception:
            context.set('config', {})

        # 4. 注入其他常用对象和元数据
        context.set('log', logger)
        debug_dir = self.plan_path / 'debug_screenshots'
        debug_dir.mkdir(parents=True, exist_ok=True)
        context.set('debug_dir', str(debug_dir))

        context.set('__task_name__', task_id)
        context.set('__plan_name__', self.plan_name)
        if triggering_event:
            context.set('event', triggering_event)

        return context

    def get_persistent_context_data(self) -> dict:
        """获取当前方案的持久化上下文数据。"""
        pc = PersistentContext(str(self.persistent_context_path))
        return pc.get_all_data()

    def save_persistent_context_data(self, data: dict):
        """保存持久化上下文数据。"""
        pc = PersistentContext(str(self.persistent_context_path))
        pc._data.clear()  # 清空旧数据
        for key, value in data.items():
            pc.set(key, value)
        pc.save()

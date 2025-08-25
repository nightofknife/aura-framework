# packages/aura_core/context_manager.py (Refactored)
from pathlib import Path
from typing import Optional, Dict, Any

from pydantic import ValidationError

from packages.aura_core.api import service_registry
from packages.aura_core.event_bus import Event
from packages.aura_core.logger import logger
from .context import Context, TaskContextModel
from .persistent_context import PersistentContext


class ContextManager:
    """
    【Async Refactor】Context Manager.
    The context creation process is now async to support async data loading.
    【Pydantic Refactor】 It now creates a structured TaskContextModel.
    """

    def __init__(self, plan_name: str, plan_path: Path):
        self.plan_name = plan_name
        self.plan_path = plan_path
        self.persistent_context_path = self.plan_path / 'persistent_context.json'

    async def create_context(
            self,
            task_id: str,
            triggering_event: Optional[Event] = None,
            initial_data: Optional[Dict[str, Any]] = None  # 【新增】
    ) -> Context:
        """
        【API 修改】异步创建一个新的、结构化的上下文，并能合并从API传入的初始数据。
        """
        persistent_context = await PersistentContext.create(str(self.persistent_context_path))

        try:
            config_service = service_registry.get_service_instance('config')
            config_service.set_active_plan(self.plan_name)
            active_config = config_service.active_plan_config
        except Exception:
            active_config = {}

        debug_dir = self.plan_path / 'debug_screenshots'
        debug_dir.mkdir(parents=True, exist_ok=True)

        # 【修改】合并持久化数据和从API传入的初始数据
        dynamic_data = persistent_context.get_all_data()
        if initial_data:
            dynamic_data.update(initial_data)

        try:
            context_model = TaskContextModel(
                plan_name=self.plan_name,
                task_name=task_id,
                log=logger,
                persistent_context=persistent_context,
                config=active_config,
                debug_dir=str(debug_dir),
                event=triggering_event,
                is_sub_context=False,
                dynamic_data=dynamic_data
            )
            return Context(context_model)
        except ValidationError as e:
            logger.critical(f"Failed to create valid Task Context: {e}")
            raise RuntimeError("Could not initialize a valid execution context.") from e

    async def get_persistent_context_data(self) -> dict:
        """Asynchronously gets the current plan's persistent context data."""
        # 【修正】统一使用 .create() 工厂方法，代码更简洁一致。
        pc = await PersistentContext.create(str(self.persistent_context_path))
        return pc.get_all_data()

    async def save_persistent_context_data(self, data: dict):
        """
        Asynchronously saves persistent context data, completely overwriting the existing file.
        """
        # 【修正】逻辑更清晰：创建一个空实例，填充数据，然后保存。
        pc = PersistentContext(str(self.persistent_context_path))
        for key, value in data.items():
            pc.set(key, value)
        await pc.save()


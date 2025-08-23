# packages/aura_core/context_manager.py (Refactored)
from pathlib import Path
from typing import Optional

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

    async def create_context(self, task_id: str, triggering_event: Optional[Event] = None) -> Context:
        """
        Asynchronously creates and initializes a new, structured context for a task execution.
        """
        # 【修正】使用 .create() 工厂方法，它已经包含了 load() 操作。
        persistent_context = await PersistentContext.create(str(self.persistent_context_path))
        # 【修正】移除下面这行多余的 load() 调用。
        # await persistent_context.load()

        # Get config service
        try:
            config_service = service_registry.get_service_instance('config')
            config_service.set_active_plan(self.plan_name)
            active_config = config_service.active_plan_config
        except Exception:
            # If config service fails, proceed with an empty config.
            active_config = {}

        # Prepare debug directory
        debug_dir = self.plan_path / 'debug_screenshots'
        debug_dir.mkdir(parents=True, exist_ok=True)

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
                dynamic_data=persistent_context.get_all_data() # .copy() is already done by get_all_data
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


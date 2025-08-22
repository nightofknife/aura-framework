# packages/aura_core/context_manager.py (Modified)
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from packages.aura_core.api import service_registry
from packages.aura_core.event_bus import Event
from packages.aura_core.logger import logger
# 【Pydantic Refactor】 Import the new Context and its underlying model
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
        # Load persistent context
        persistent_context = PersistentContext(str(self.persistent_context_path))
        # This can be made async if the underlying I/O is async
        await persistent_context.load()

        # Get config service
        try:
            config_service = service_registry.get_service_instance('config')
            config_service.set_active_plan(self.plan_name)
            active_config = config_service.active_plan_config
        except Exception:
            active_config = {}

        # Prepare debug directory
        debug_dir = self.plan_path / 'debug_screenshots'
        debug_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 【Pydantic Refactor】 Instantiate the Pydantic model with all gathered data
            context_model = TaskContextModel(
                plan_name=self.plan_name,
                task_name=task_id,
                log=logger,
                persistent_context=persistent_context,
                config=active_config,
                debug_dir=str(debug_dir),
                event=triggering_event,
                is_sub_context=False,
                # Start with persistent data loaded into the dynamic data store
                dynamic_data=persistent_context.get_all_data().copy()
            )
            return Context(context_model)
        except ValidationError as e:
            logger.critical(f"Failed to create valid Task Context: {e}")
            raise RuntimeError("Could not initialize a valid execution context.") from e


    async def get_persistent_context_data(self) -> dict:
        """Asynchronously gets the current plan's persistent context data."""
        pc = PersistentContext(str(self.persistent_context_path))
        await pc.load()
        return pc.get_all_data()

    async def save_persistent_context_data(self, data: dict):
        """Asynchronously saves persistent context data."""
        pc = PersistentContext(str(self.persistent_context_path))
        pc._data.clear()
        for key, value in data.items():
            pc.set(key, value)
        await pc.save()

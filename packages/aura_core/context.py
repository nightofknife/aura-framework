# packages/aura_core/context.py (Stage 1 Refactor - Complete File)

from __future__ import annotations
import copy
from typing import Any, Dict, Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

from packages.aura_core.logger import logger


from packages.aura_core.event_bus import Event
from .persistent_context import PersistentContext

class TaskContextModel(BaseModel):
    """
    Defines the structured data model for the task execution context.
    This provides type safety, autocompletion, and self-documentation.
    """
    # Core metadata
    plan_name: str
    task_name: str

    # Core services and objects
    log: logger
    persistent_context: PersistentContext
    config: Dict[str, Any]
    debug_dir: str

    # Triggering event (optional)
    event: Optional[Event] = None

    # Internal state flag
    is_sub_context: bool = False

    # Dynamic data store for step outputs, loop variables, etc.
    dynamic_data: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        # Allow complex types like Logger, Event, etc., which are not Pydantic models.
        arbitrary_types_allowed = True




class Context:
    """
    A smart wrapper for the TaskContextModel, providing a controlled interface.
    It maintains the original class's methods and behaviors (forking, sub-context checks)
    while leveraging Pydantic for core data integrity.
    """

    def __init__(self, model: TaskContextModel):
        self._model = model

    @property
    def _data(self) -> Dict[str, Any]:
        """Provides a flattened data view for Jinja2 rendering."""
        # Merge model fields and dynamic data. Dynamic data has higher priority.
        model_dict = self._model.dict(exclude={'dynamic_data', 'log', 'persistent_context', 'event'})

        # Manually add non-serializable core objects
        model_dict['log'] = self._model.log
        model_dict['persistent_context'] = self._model.persistent_context
        model_dict['event'] = self._model.event

        return {**model_dict, **self._model.dynamic_data}

    def set(self, key: str, value: Any):
        """
        Sets a value in the context's dynamic data store.
        It prevents overwriting core, structured context variables.
        """
        key_lower = key.lower()
        # Allow setting 'error' for failure handlers
        if hasattr(self._model, key_lower) and key_lower not in ['dynamic_data', 'error']:
            self._model.log.warning(f"Attempted to overwrite core context variable '{key_lower}'. "
                           f"Dynamic values are stored separately. Use a different key.")
            return
        self._model.dynamic_data[key_lower] = value

    def get(self, key: str, default: Any = None) -> Any:
        """
        Gets a value from the context.
        Priority: 1. Dynamic data, 2. Core structured data.
        """
        key_lower = key.lower()
        if key_lower in self._model.dynamic_data:
            return self._model.dynamic_data[key_lower]
        if hasattr(self._model, key_lower):
            return getattr(self._model, key_lower)
        return default

    def delete(self, key: str):
        """Deletes a key only from the dynamic data store."""
        self._model.dynamic_data.pop(key.lower(), None)

    def is_sub_context(self) -> bool:
        """Checks if this is a sub-context."""
        return self._model.is_sub_context

    def get_triggering_event(self) -> Optional[Event]:
        """Gets the event that triggered this context's creation."""
        return self._model.event

    def fork(self) -> 'Context':
        """
        【Corrected】Creates a new, variable-isolated sub-context.
        It inherits core services but gets a fresh, empty dynamic_data store.
        """
        # Use Pydantic's copy method for a safe copy of the model structure
        # and its data, including complex types.
        forked_model = self._model.copy(deep=True)

        # Explicitly set the forked properties
        forked_model.is_sub_context = True
        # A fork always starts with a clean slate for dynamic data
        forked_model.dynamic_data = {}

        return Context(forked_model)

    def __str__(self):
        trigger_id = self._model.event.id if self._model.event else None
        return (f"Context(dynamic_keys={list(self._model.dynamic_data.keys())}, "
                f"sub={self._model.is_sub_context}, trigger={trigger_id})")

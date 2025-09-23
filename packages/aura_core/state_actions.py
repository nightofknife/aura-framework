# plans/aura_base/actions/state_actions.py

from typing import Any
from pydantic import BaseModel, Field

from packages.aura_core.api import register_action, requires_services
from packages.aura_core.state_store_service import StateStoreService


class StateSetParams(BaseModel):
    key: str = Field(..., description="要设置的键名")
    value: Any = Field(..., description="要设置的值")

@register_action(name="state.set")
@requires_services(state_store="state_store")
async def state_set(params: StateSetParams, state_store: StateStoreService):
    """
    在长期上下文中设置一个键值对。
    """
    await state_store.set(params.key, params.value)
    return True


class StateGetParams(BaseModel):
    key: str = Field(..., description="要获取的键名")
    default: Any = Field(default=None, description="如果键不存在时返回的默认值")

@register_action(name="state.get", read_only=True)
@requires_services(state_store="state_store")
async def state_get(params: StateGetParams, state_store: StateStoreService) -> Any:
    """
    从长期上下文中获取一个值。
    """
    return await state_store.get(params.key, params.default)


class StateDeleteParams(BaseModel):
    key: str = Field(..., description="要删除的键名")

@register_action(name="state.delete")
@requires_services(state_store="state_store")
async def state_delete(params: StateDeleteParams, state_store: StateStoreService):
    """
    从长期上下文中删除一个键。
    """
    await state_store.delete(params.key)
    return True

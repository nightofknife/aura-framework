"""
提供了一组与 `StateStoreService` 交互的基础核心行为 (Actions)。

这些行为封装了对全局状态存储的常见操作（设置、获取、删除），
允许任务通过标准的 Action 调用方式来管理持久化或半持久化的数据，
而无需直接依赖 `StateStoreService`。
"""
from typing import Any
from pydantic import BaseModel, Field

from packages.aura_core.api import register_action, requires_services
from packages.aura_core.state_store_service import StateStoreService


class StateSetParams(BaseModel):
    """
    `state.set` 行为的参数模型。

    Attributes:
        key (str): 要在状态存储中设置的键名。
        value (Any): 要设置的值，可以是任何可被序列化的类型。
    """
    key: str = Field(..., description="要设置的键名")
    value: Any = Field(..., description="要设置的值")

@register_action(name="state.set")
@requires_services(state_store="state_store")
async def state_set(params: StateSetParams, state_store: StateStoreService) -> bool:
    """
    在全局状态存储中设置一个键值对。

    此行为会调用 `StateStoreService` 的 `set` 方法来持久化或缓存一个值。

    Args:
        params (StateSetParams): 包含 `key` 和 `value` 的参数对象。
        state_store (StateStoreService): 自动注入的状态存储服务实例。

    Returns:
        bool: 操作成功时返回 True。
    """
    await state_store.set(params.key, params.value)
    return True


class StateGetParams(BaseModel):
    """
    `state.get` 行为的参数模型。

    Attributes:
        key (str): 要从状态存储中获取的键名。
        default (Any): 如果键不存在时返回的默认值。
    """
    key: str = Field(..., description="要获取的键名")
    default: Any = Field(default=None, description="如果键不存在时返回的默认值")

@register_action(name="state.get", read_only=True)
@requires_services(state_store="state_store")
async def state_get(params: StateGetParams, state_store: StateStoreService) -> Any:
    """
    从全局状态存储中获取一个值。

    如果指定的键不存在，将返回提供的默认值。

    Args:
        params (StateGetParams): 包含 `key` 和 `default` 值的参数对象。
        state_store (StateStoreService): 自动注入的状态存储服务实例。

    Returns:
        Any: 查找到的值，或在未找到时返回默认值。
    """
    return await state_store.get(params.key, params.default)


class StateDeleteParams(BaseModel):
    """
    `state.delete` 行为的参数模型。

    Attributes:
        key (str): 要从状态存储中删除的键名。
    """
    key: str = Field(..., description="要删除的键名")

@register_action(name="state.delete")
@requires_services(state_store="state_store")
async def state_delete(params: StateDeleteParams, state_store: StateStoreService) -> bool:
    """
    从全局状态存储中删除一个键。

    Args:
        params (StateDeleteParams): 包含要删除的 `key` 的参数对象。
        state_store (StateStoreService): 自动注入的状态存储服务实例。

    Returns:
        bool: 操作成功时返回 True。
    """
    await state_store.delete(params.key)
    return True

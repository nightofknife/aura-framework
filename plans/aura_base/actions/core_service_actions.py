# aura_base/actions/core_service_actions.py (已增强)

from typing import Any, Optional, Dict

from packages.aura_core.api import register_action, requires_services
from packages.aura_core.context import Context
# 【新】 导入EventBus相关的类
from packages.aura_core.event_bus import EventBus, Event
from packages.aura_core.state_store import StateStore
from packages.aura_shared_utils.utils.logger import logger


# ==============================================================================
# I. StateStore (驻留信号) Actions
# ==============================================================================

# ... (set_state, get_state, delete_state 保持不变)
@register_action(name="set_state", public=True)
@requires_services(state_store='state_store')
def set_state(
        state_store: StateStore,
        key: str,
        value: Any,
        ttl: Optional[float] = None
) -> bool:
    """
    在全局状态存储中设置一个驻留信号（状态）。

    :param state_store: (由框架注入) StateStore服务实例。
    :param key: 状态的唯一标识符。
    :param value: 要存储的状态值。
    :param ttl: (可选) 状态的存活时间（秒）。如果未提供，则状态永不过期。
    :return: 操作是否成功。
    """
    try:
        state_store.set(key, value, ttl)
        if ttl:
            logger.info(f"设置驻留信号 '{key}' = {repr(value)} (TTL: {ttl}s)")
        else:
            logger.info(f"设置驻留信号 '{key}' = {repr(value)}")
        return True
    except Exception as e:
        logger.error(f"设置驻留信号 '{key}' 时失败: {e}", exc_info=True)
        return False


@register_action(name="get_state", read_only=True, public=True)
@requires_services(state_store='state_store')
def get_state(
        state_store: StateStore,
        context: Context,
        key: str,
        default: Any = None,
        output_to: Optional[str] = None
) -> Any:
    """
    从全局状态存储中获取一个驻留信号（状态）的值。

    这个Action有两种用法：
    1. 如果提供了 `output_to`，它会将结果存入上下文并返回True/False表示是否找到。
    2. 如果没有提供 `output_to`，它会直接返回值本身。

    :param state_store: (由框架注入) StateStore服务实例。
    :param context: (由框架注入) 当前任务的上下文。
    :param key: 要获取的状态的键。
    :param default: (可选) 如果状态不存在，返回的默认值。
    :param output_to: (可选) 如果提供，则将结果存入此上下文变量名下。
    :return: 根据用法返回状态值或布尔值。
    """
    value = state_store.get(key, default)

    if output_to:
        context.set(output_to, value)
        found = value is not default
        logger.info(f"获取驻留信号 '{key}' -> '{output_to}' (找到: {found})")
        return found
    else:
        logger.info(f"获取驻留信号 '{key}' -> 返回值")
        return value


@register_action(name="delete_state", public=True)
@requires_services(state_store='state_store')
def delete_state(
        state_store: StateStore,
        key: str
) -> bool:
    """
    从全局状态存储中删除一个驻留信号（状态）。

    :param state_store: (由框架注入) StateStore服务实例。
    :param key: 要删除的状态的键。
    :return: 如果成功删除或键原本就不存在，返回True。
    """
    try:
        deleted = state_store.delete(key)
        if deleted:
            logger.info(f"删除了驻留信号 '{key}'")
        else:
            logger.info(f"尝试删除驻留信号 '{key}'，但它不存在。")
        return True  # 即使键不存在，从逻辑上讲，也达到了“它不存在”的目标
    except Exception as e:
        logger.error(f"删除驻留信号 '{key}' 时失败: {e}", exc_info=True)
        return False


# ==============================================================================
# II. EventBus (瞬时信号) Actions
# ==============================================================================

@register_action(name="publish_event", public=True)
@requires_services(event_bus='event_bus')
def publish_event(
        event_bus: EventBus,
        context: Context,
        name: str,
        payload: Dict[str, Any] = None,
        source: Optional[str] = None
) -> bool:
    """
    向事件总线发布一个瞬时信号（事件）。

    :param event_bus: (由框架注入) EventBus服务实例。
    :param context: (由框架注入) 当前任务的上下文，用于追踪调用链。
    :param name: 事件的名称 (例如 'orders:created', 'player:died')。
    :param payload: (可选) 附加到事件的数据字典。
    :param source: (可选) 事件的来源。如果未提供，会尝试从上下文中推断。
    :return: 操作是否成功。
    """
    try:
        # 准备调用链和深度
        causation_chain = []
        depth = 0
        triggering_event = context.get_triggering_event()  # 我们即将添加这个方法
        if triggering_event:
            causation_chain.extend(triggering_event.causation_chain)
            depth = triggering_event.depth + 1

        # 确定事件来源
        event_source = source or context.get('__task_name__', 'unknown_task')

        # 创建并发布事件
        new_event = Event(
            name=name,
            payload=payload or {},
            source=event_source,
            causation_chain=causation_chain,
            depth=depth
        )
        event_bus.publish(new_event)

        return True
    except Exception as e:
        logger.error(f"发布事件 '{name}' 时失败: {e}", exc_info=True)
        return False

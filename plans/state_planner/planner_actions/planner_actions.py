# plans/state_planner/planner_actions/planner_actions.py

from packages.aura_core.api import register_action, requires_services, service_registry
from packages.aura_core.context import Context
from packages.aura_core.event_bus import Event
from packages.aura_shared_utils.utils.logger import logger
from ..planner_services.state_planner_service import StatePlannerService

@register_action(name="ensure_state", public=True)
@requires_services(state_planner='state_planner')
def ensure_state(
        state_planner: StatePlannerService,
        context: Context,
        target: str,
        map: str,
        # 【新增】超时参数，默认为5分钟
        timeout: float = 300.0,
        # 【新增】默认转移成本，默认为1
        default_cost: float = 1.0
) -> bool:
    """
    确保系统处于指定的状态。
    如果当前不处于该状态，会自动规划并执行一系列动作来到达目标状态。

    :param state_planner: (注入) 状态规划器服务实例。
    :param context: (注入) 当前任务的上下文。
    :param target: 目标状态的名称 (在 world_map.yaml 中定义)。
    :param map: world_map.yaml 文件的路径 (相对于方案包根目录)。
    :param timeout: (可选) 整个规划和执行过程的最大允许时间（秒）。默认为300。
    :param default_cost: (可选) 地图中未指定成本的转移的默认成本。默认为1。
    :return: 如果成功到达目标状态则返回 True，否则返回 False。
    """
    try:
        plan_name = context.get('__plan_name__')
        if not plan_name:
            raise ValueError("无法确定当前方案包名称，无法使用 StatePlanner。")

        # 【修改】将新参数传递给服务
        return state_planner.ensure_state(
            plan_name=plan_name,
            target_state=target,
            map_file=map,
            timeout=float(timeout),
            default_cost=float(default_cost)
        )
    except Exception as e:
        logger.error(f"执行 ensure_state 时发生错误: {e}", exc_info=True)
        # 【新增】在Action层面也发布一个失败事件
        try:
            event_bus = service_registry.get_service_instance('event_bus')
            event = Event(
                name="PLANNER_FAILED",
                channel="planner",
                payload={"reason": f"Action执行异常: {e}"},
                source="ensure_state_action"
            )
            event_bus.publish(event)
        except Exception as bus_error:
            logger.error(f"发布规划器失败事件时再次发生错误: {bus_error}")
        return False

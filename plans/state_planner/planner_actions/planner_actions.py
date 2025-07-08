# plans/state_planner/planner_actions/planner_actions.py (正确版本)

from packages.aura_core.api import register_action, requires_services
from packages.aura_core.context import Context
from packages.aura_shared_utils.utils.logger import logger

# 导入服务类仅用于类型提示，增强代码可读性
from ..planner_services.state_planner_service import StatePlannerService


# 【核心修改】模仿 notifier 的 Action 写法
@register_action(name="ensure_state", public=True)
@requires_services(state_planner='state_planner')  # 显式声明依赖的服务别名
def ensure_state(
        state_planner: StatePlannerService,  # 参数名与@requires_services中的key匹配
        context: Context,
        target: str,
        map: str
) -> bool:
    """
    确保系统处于指定的状态。
    如果当前不处于该状态，会自动规划并执行一系列动作来到达目标状态。

    :param state_planner: (注入) 状态规划器服务实例。
    :param context: (注入) 当前任务的上下文。
    :param target: 目标状态的名称 (在 world_map.yaml 中定义)。
    :param map: world_map.yaml 文件的路径 (相对于方案包根目录)。
    :return: 如果成功到达目标状态则返回 True，否则返回 False。
    """
    try:
        plan_name = context.get('__plan_name__')
        if not plan_name:
            raise ValueError("无法确定当前方案包名称，无法使用 StatePlanner。")

        return state_planner.ensure_state(
            plan_name=plan_name,
            target_state=target,
            map_file=map
        )
    except Exception as e:
        logger.error(f"执行 ensure_state 时发生错误: {e}", exc_info=True)
        return False


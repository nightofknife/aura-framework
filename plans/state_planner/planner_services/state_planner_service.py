# plans/state_planner/planner_services/state_planner_service.py
import heapq
import time
from collections import defaultdict
from typing import Dict, Any, List, Optional, Tuple

import yaml

from packages.aura_core.api import register_service, service_registry
from packages.aura_core.event_bus import EventBus, Event
from packages.aura_shared_utils.utils.logger import logger


# 一个简单的图数据结构，用于状态规划
class StateGraph:
    def __init__(self):
        self.nodes: Dict[str, Dict] = {}
        self.edges: Dict[str, List[Tuple[str, float]]] = defaultdict(list)  # {from: [(to, cost), ...]}
        self.transitions: Dict[Tuple[str, str], Dict] = {}

    def add_state(self, state_data: Dict):
        name = state_data['name']
        self.nodes[name] = state_data

    def add_transition(self, trans_data: Dict, default_cost: float):
        from_state = trans_data['from']
        to_state = trans_data['to']
        # 【新增】如果用户在 transition 中定义了 cost，就用它，否则用默认值
        cost = float(trans_data.get('cost', default_cost))
        self.edges[from_state].append((to_state, cost))
        self.transitions[(from_state, to_state)] = trans_data

    def find_path(self, start: str, end: str) -> Optional[Tuple[List[str], float]]:
        """
        【升级】使用Dijkstra算法寻找成本最低的路径。
        返回路径列表和总成本。
        """
        if start not in self.nodes or end not in self.nodes:
            return None

        # (cost, current_node, path_list)
        queue = [(0, start, [start])]
        visited_costs = {start: 0}

        while queue:
            current_cost, current_node, path = heapq.heappop(queue)

            if current_node == end:
                return path, current_cost

            if current_cost > visited_costs.get(current_node, float('inf')):
                continue

            for neighbor, edge_cost in self.edges.get(current_node, []):
                new_cost = current_cost + edge_cost
                if new_cost < visited_costs.get(neighbor, float('inf')):
                    visited_costs[neighbor] = new_cost
                    new_path = path + [neighbor]
                    heapq.heappush(queue, (new_cost, neighbor, new_path))

        return None  # 找不到路径


@register_service(alias="state_planner", public=True)
class StatePlannerService:
    def __init__(self, event_bus: EventBus):
        self._map_cache: Dict[str, StateGraph] = {}
        self._plan_orchestrators: Dict[str, Any] = {}
        self.event_bus = event_bus  # 保存 event_bus 实例
        logger.info("StatePlannerService 已初始化，并已连接到 EventBus。")

    def _publish_event(self, name: str, payload: Dict):
        """一个发布规划器事件的辅助方法"""
        event = Event(
            name=name,
            channel="planner",  # 所有规划器事件都在 'planner' 频道发布
            payload=payload,
            source="state_planner_service"
        )
        self.event_bus.publish(event)

    def _get_orchestrator(self, plan_name: str):
        """获取或缓存指定方案包的Orchestrator实例"""
        if plan_name not in self._plan_orchestrators:
            scheduler = service_registry.get_service_instance('scheduler')
            if plan_name in scheduler.plans:
                self._plan_orchestrators[plan_name] = scheduler.plans[plan_name]
            else:
                raise ValueError(f"找不到方案包 '{plan_name}' 的Orchestrator实例。")
        return self._plan_orchestrators[plan_name]

    def _load_map(self, plan_name: str, map_file: str, default_cost: float) -> StateGraph:
        orchestrator = self._get_orchestrator(plan_name)
        map_path_str = str(orchestrator.current_plan_path / map_file)

        # 缓存键现在包含 default_cost，以防同一个地图用不同成本加载
        cache_key = f"{map_path_str}::{default_cost}"
        if cache_key in self._map_cache:
            return self._map_cache[cache_key]

        logger.info(f"正在为方案 '{plan_name}' 加载状态地图: {map_file}")
        try:
            map_content = orchestrator.get_file_content(map_file)
            map_data = yaml.safe_load(map_content)
        except Exception as e:
            logger.error(f"加载或解析地图文件 '{map_path_str}' 失败: {e}")
            raise

        graph = StateGraph()
        for state in map_data.get('states', []):
            graph.add_state(state)
        for transition in map_data.get('transitions', []):
            # 将 default_cost 传递给 add_transition
            graph.add_transition(transition, default_cost)

        self._map_cache[cache_key] = graph

        # 【新增】发布地图加载事件
        self._publish_event("PLANNER_MAP_LOADED", {
            "map_file": map_file,
            "nodes": list(graph.nodes.keys()),
            "transitions": [
                {"from": t[0], "to": t[1], "cost": c} for t, (n, c) in graph.edges.items() for n, c in graph.edges[t]
            ]
        })
        return graph

    def get_current_state(self, plan_name: str, state_map: StateGraph) -> Optional[str]:
        orchestrator = self._get_orchestrator(plan_name)
        logger.debug("正在确定当前状态...")
        for state_name, state_data in state_map.nodes.items():
            check_action = state_data.get('check')
            if not check_action:
                continue
            if orchestrator.perform_condition_check(check_action):
                logger.info(f"当前状态已确定为: '{state_name}'")
                return state_name
        logger.warning("无法确定当前状态，所有状态检查均未通过。")
        return None

    def execute_transition(self, plan_name: str, transition_data: Dict[str, Any]):
        orchestrator = self._get_orchestrator(plan_name)
        action_data = transition_data.get('action')

        if not isinstance(action_data, dict):
            logger.error(f"转移定义中的 'action' 格式错误，不是一个字典: {action_data}")
            raise ValueError("无效的转移动作定义")

        from packages.aura_core.engine import ExecutionEngine
        from packages.aura_core.context import Context

        context = Context()
        orchestrator._initialize_context(context, None, f"planner_transition_for_{plan_name}")

        engine = ExecutionEngine(context=context, orchestrator=orchestrator)

        # 【修正】直接使用 engine 的 _execute_single_step_logic 来执行
        # 因为它包含了重试和错误处理逻辑，更健壮
        step_succeeded = engine._execute_single_step_logic(action_data)

        if not step_succeeded:
            raise RuntimeError(f"状态转移失败: 动作 '{action_data.get('action')}' 执行失败。")

    def ensure_state(self, plan_name: str, target_state: str, map_file: str, timeout: float,
                     default_cost: float) -> bool:
        start_time = time.time()
        logger.info(f"规划器目标: 确保处于状态 '{target_state}' (地图: {map_file}, 超时: {timeout}s)")
        self._publish_event("PLANNER_STARTED", {
            "target": target_state,
            "map_file": map_file,
            "timeout": timeout
        })

        # 1. 加载地图
        try:
            state_map = self._load_map(plan_name, map_file, default_cost)
        except Exception as e:
            self._publish_event("PLANNER_FAILED", {"reason": f"地图加载失败: {e}"})
            return False

        # 2. 定位当前状态
        start_state = self.get_current_state(plan_name, state_map)
        if not start_state:
            logger.error("规划失败：无法确定起始状态。")
            self._publish_event("PLANNER_FAILED", {"reason": "无法确定起始状态"})
            return False

        self._publish_event("PLANNER_STATE_LOCATED", {"current_state": start_state})

        if start_state == target_state:
            logger.info(f"已处于目标状态 '{target_state}'，无需规划。")
            self._publish_event("PLANNER_SUCCEEDED", {"reason": "已处于目标状态"})
            return True

        # 3. 寻找路径
        path_info = state_map.find_path(start_state, target_state)
        if not path_info:
            logger.error(f"规划失败：找不到从 '{start_state}' 到 '{target_state}' 的路径。")
            self._publish_event("PLANNER_FAILED", {
                "reason": "找不到路径",
                "from": start_state,
                "to": target_state
            })
            return False

        path, total_cost = path_info
        logger.info(f"已规划路径: {' -> '.join(path)} (总成本: {total_cost})")
        self._publish_event("PLANNER_PATH_FOUND", {"path": path, "total_cost": total_cost})

        # 4. 执行计划
        for i in range(len(path) - 1):
            # 检查超时
            if time.time() - start_time > timeout:
                logger.error(f"规划执行超时（超过 {timeout} 秒）。")
                self._publish_event("PLANNER_FAILED", {"reason": "执行超时"})
                return False

            current_step = path[i]
            next_step = path[i + 1]

            logger.info(f"执行路径步骤: 从 '{current_step}' -> '{next_step}'")
            self._publish_event("PLANNER_STEP_EXECUTING", {
                "from": current_step,
                "to": next_step,
                "path_index": i + 1,
                "total_steps": len(path) - 1
            })

            transition_key = (current_step, next_step)
            transition_data = state_map.transitions.get(transition_key)

            if not transition_data:
                logger.error(f"严重错误：路径有效但找不到转移定义 for {transition_key}")
                self._publish_event("PLANNER_FAILED", {"reason": f"内部错误：找不到转移定义 for {transition_key}"})
                return False

            try:
                self.execute_transition(plan_name, transition_data)
                # 验证是否真的到达了下一个状态
                time.sleep(1)
                validated_state = self.get_current_state(plan_name, state_map)
                if validated_state != next_step:
                    logger.error(f"转移执行后状态验证失败！期望到达 '{next_step}'，但当前状态是 '{validated_state}'。")
                    self._publish_event("PLANNER_FAILED", {
                        "reason": "状态验证失败",
                        "expected": next_step,
                        "actual": validated_state
                    })
                    return False

                self._publish_event("PLANNER_STEP_COMPLETED", {"state_reached": next_step})

            except Exception as e:
                logger.error(f"执行转移 {transition_key} 时失败: {e}")
                self._publish_event("PLANNER_FAILED", {
                    "reason": f"执行转移时发生异常",
                    "from": current_step,
                    "to": next_step,
                    "error": str(e)
                })
                return False

        logger.info(f"成功到达目标状态: '{target_state}'")
        self._publish_event("PLANNER_SUCCEEDED", {"reason": "成功到达目标状态"})
        return True

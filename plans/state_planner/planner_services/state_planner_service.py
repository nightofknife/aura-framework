# plans/state_planner/planner_services/state_planner_service.py
import time

import yaml
from pathlib import Path
from collections import deque, defaultdict
from typing import Dict, Any, List, Optional

from packages.aura_core.api import  register_service, service_registry
from packages.aura_shared_utils.utils.logger import logger


# 一个简单的图数据结构，用于状态规划
class StateGraph:
    def __init__(self):
        self.nodes = {}  # {state_name: state_data}
        self.edges = defaultdict(list)  # {from_state: [to_state, ...]}
        self.transitions = {}  # {(from_state, to_state): transition_data}

    def add_state(self, state_data: Dict):
        name = state_data['name']
        self.nodes[name] = state_data

    def add_transition(self, trans_data: Dict):
        from_state = trans_data['from']
        to_state = trans_data['to']
        self.edges[from_state].append(to_state)
        self.transitions[(from_state, to_state)] = trans_data

    def find_path(self, start: str, end: str) -> Optional[List[str]]:
        """使用广度优先搜索 (BFS) 寻找最短路径"""
        if start == end:
            return [start]
        if start not in self.nodes or end not in self.nodes:
            return None

        queue = deque([(start, [start])])
        visited = {start}

        while queue:
            current_node, path = queue.popleft()
            if current_node == end:
                return path

            for neighbor in self.edges.get(current_node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    new_path = list(path)
                    new_path.append(neighbor)
                    queue.append((neighbor, new_path))
        return None

@register_service(alias="state_planner", public=True)
class StatePlannerService:
    def __init__(self):
        self._map_cache: Dict[str, StateGraph] = {}
        self._plan_orchestrators: Dict[str, Any] = {}
        logger.info("StatePlannerService 已初始化。")

    def _get_orchestrator(self, plan_name: str):
        """获取或缓存指定方案包的Orchestrator实例"""
        if plan_name not in self._plan_orchestrators:
            scheduler = service_registry.get_service_instance('scheduler')
            if plan_name in scheduler.plans:
                self._plan_orchestrators[plan_name] = scheduler.plans[plan_name]
            else:
                raise ValueError(f"找不到方案包 '{plan_name}' 的Orchestrator实例。")
        return self._plan_orchestrators[plan_name]

    def _load_map(self, plan_name: str, map_file: str) -> StateGraph:
        """加载并解析 world_map.yaml 文件"""
        orchestrator = self._get_orchestrator(plan_name)
        map_path_str = str(orchestrator.current_plan_path / map_file)

        if map_path_str in self._map_cache:
            return self._map_cache[map_path_str]

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
            graph.add_transition(transition)

        self._map_cache[map_path_str] = graph
        return graph

    def get_current_state(self, plan_name: str, state_map: StateGraph) -> Optional[str]:
        """遍历所有状态的check，确定当前所处的状态"""
        orchestrator = self._get_orchestrator(plan_name)
        logger.debug("正在确定当前状态...")
        for state_name, state_data in state_map.nodes.items():
            check_action = state_data.get('check')
            if not check_action:
                continue

            # 使用Orchestrator的perform_condition_check来执行只读的检查动作
            # 这是为了重用现有的、安全的只读Action执行逻辑
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

    def ensure_state(self, plan_name: str, target_state: str, map_file: str) -> bool:
        """
        核心规划与执行逻辑。
        确保系统最终处于 target_state。
        """
        logger.info(f"规划器目标: 确保处于状态 '{target_state}' (地图: {map_file})")

        # 1. 加载地图
        state_map = self._load_map(plan_name, map_file)

        # 2. 定位当前状态
        start_state = self.get_current_state(plan_name, state_map)
        if not start_state:
            logger.error("规划失败：无法确定起始状态。")
            return False

        if start_state == target_state:
            logger.info(f"已处于目标状态 '{target_state}'，无需规划。")
            return True

        # 3. 寻找路径
        path = state_map.find_path(start_state, target_state)
        if not path:
            logger.error(f"规划失败：找不到从 '{start_state}' 到 '{target_state}' 的路径。")
            return False

        logger.info(f"已规划路径: {' -> '.join(path)}")

        # 4. 执行计划
        for i in range(len(path) - 1):
            current_step = path[i]
            next_step = path[i + 1]

            logger.info(f"执行路径步骤: 从 '{current_step}' -> '{next_step}'")

            transition_key = (current_step, next_step)
            transition_data = state_map.transitions.get(transition_key)

            if not transition_data:
                logger.error(f"严重错误：路径有效但找不到转移定义 for {transition_key}")
                return False

            try:
                self.execute_transition(plan_name, transition_data)
                # 验证是否真的到达了下一个状态
                time.sleep(1)  # 等待一下，让状态稳定
                if self.get_current_state(plan_name, state_map) != next_step:
                    logger.error(f"转移执行后状态验证失败！期望到达 '{next_step}'，但未能确认。")
                    return False
            except Exception as e:
                logger.error(f"执行转移 {transition_key} 时失败: {e}")
                return False

        logger.info(f"成功到达目标状态: '{target_state}'")
        return True


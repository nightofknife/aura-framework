# packages/aura_core/state_planner.py (全新文件 - 完整版)

import heapq
from typing import Dict, List, Optional, Any
from packages.aura_core.logger import logger


class StateMap:
    """一个数据类，用于保存解析后的 states_map.yaml 内容。"""

    def __init__(self, data: Dict[str, Any]):
        self.states: Dict[str, Any] = data.get('states', {})
        self.transitions: List[Dict[str, Any]] = data.get('transitions', [])
        logger.info(f"StateMap 加载完成: {len(self.states)} 个状态, {len(self.transitions)} 条转移路径。")


class StatePlanner:
    """
    状态规划器，使用 Dijkstra 算法在状态图中寻找成本最低的路径。
    """

    def __init__(self, state_map: StateMap):
        self.state_map = state_map
        self.graph = self._build_graph()

    def _build_graph(self) -> Dict[str, List[tuple]]:
        """将 transitions 列表预处理成邻接表格式的图，以提高寻路效率。"""
        graph = {state: [] for state in self.state_map.states}
        for transition in self.state_map.transitions:
            from_state = transition.get('from')
            to_state = transition.get('to')
            cost = transition.get('cost', 1)
            task = transition.get('transition_task')
            if from_state in graph:
                graph[from_state].append((to_state, cost, task))
        return graph

    def find_path(self, start_node: str, end_node: str) -> Optional[List[str]]:
        """
        使用 Dijkstra 算法寻找从 start_node 到 end_node 的最短路径。
        返回一个有序的 transition_task ID 列表。
        """
        if start_node not in self.graph or end_node not in self.graph:
            logger.error(f"路径规划失败: 起点 '{start_node}' 或终点 '{end_node}' 不在状态图中。")
            return None

        # 队列元素: (总成本, 当前节点, 任务路径列表)
        priority_queue = [(0, start_node, [])]
        # 记录到达每个节点的最低成本，防止循环
        min_costs = {node: float('inf') for node in self.graph}
        min_costs[start_node] = 0

        while priority_queue:
            cost, current_node, path_tasks = heapq.heappop(priority_queue)

            # 如果已经有更优路径到达当前节点，则跳过
            if cost > min_costs[current_node]:
                continue

            # 如果到达终点，返回任务路径
            if current_node == end_node:
                logger.info(f"路径规划成功: 从 '{start_node}' 到 '{end_node}'，路径: {path_tasks}")
                return path_tasks

            # 遍历邻居
            for neighbor, edge_cost, task in self.graph.get(current_node, []):
                new_cost = cost + edge_cost
                if new_cost < min_costs[neighbor]:
                    min_costs[neighbor] = new_cost
                    new_path = path_tasks + [task]
                    heapq.heappush(priority_queue, (new_cost, neighbor, new_path))

        logger.warning(f"路径规划失败: 从 '{start_node}' 到 '{end_node}' 找不到可用路径。")
        return None  # 找不到路径

# packages/aura_core/state_planner.py (最终修正版)

import asyncio
import heapq
from collections import deque
from typing import Dict, List, Optional, Any, Set, TYPE_CHECKING

from packages.aura_core.logger import logger

if TYPE_CHECKING:
    from .orchestrator import Orchestrator

class StateMap:
    """一个数据类，用于保存解析后的 states_map.yaml 内容。"""

    def __init__(self, data: Dict[str, Any]):
        self.states: Dict[str, Any] = data.get('states', {})
        self.transitions: List[Dict[str, Any]] = data.get('transitions', [])
        logger.info(f"StateMap 加载完成: {len(self.states)} 个状态, {len(self.transitions)} 条转移路径。")


class StatePlanner:
    """
    【集成版】智能状态规划器 v3.0
    - 结合了高效的状态确定机制和基于Dijkstra算法的最低成本路径规划。
    """

    def __init__(self, state_map: StateMap, orchestrator: 'Orchestrator'):
        self.state_map = state_map
        self.orchestrator = orchestrator
        self.graph = self._build_graph()
        self._reverse_graph = self._build_reverse_graph()

    def _build_graph(self) -> Dict[str, List[tuple]]:
        """将 transitions 列表预处理成邻接表格式的图，以提高寻路效率。"""
        graph = {state: [] for state in self.state_map.states}
        for transition in self.state_map.transitions:
            from_state = transition.get('from')
            to_state = transition.get('to')
            cost = transition.get('cost', 1)
            task = transition.get('transition_task')
            if from_state in graph and to_state in graph:
                graph[from_state].append((to_state, cost, task))
        return graph

    def _build_reverse_graph(self) -> Dict[str, Set[str]]:
        """构建一个反向图，用于BFS距离计算。"""
        reverse = {state: set() for state in self.state_map.states}
        for from_node, edges in self.graph.items():
            for to_node, _, _ in edges:
                reverse[to_node].add(from_node)
        return reverse

    def _calculate_distances_to_target(self, target_state: str) -> Dict[str, int]:
        """使用广度优先搜索(BFS)计算所有状态到目标状态的最短距离（无视权重）。"""
        if target_state not in self.state_map.states:
            return {}

        distances = {state: float('inf') for state in self.state_map.states}
        distances[target_state] = 0
        queue = deque([target_state])

        while queue:
            current_state = queue.popleft()
            for predecessor in self._reverse_graph.get(current_state, set()):
                if distances[predecessor] == float('inf'):
                    distances[predecessor] = distances[current_state] + 1
                    queue.append(predecessor)
        return distances

    async def determine_current_state(self, target_state: str) -> Optional[str]:
        """
        【修正版】使用分阶段、有序、可中断的逻辑来确定当前状态。
        """
        logger.info(f"智能状态规划：开始确定当前状态，目标是 '{target_state}'。")

        distances = self._calculate_distances_to_target(target_state)

        check_list = []
        for state_name, state_data in self.state_map.states.items():
            check_list.append({
                "state_name": state_name,
                "task_name": state_data.get('check_task'),
                "can_async": state_data.get('can_async', True),
                "priority": state_data.get('priority', 100),
                "distance": distances.get(state_name, float('inf'))
            })

        check_list.sort(key=lambda x: (x['distance'], x['priority']))

        parallel_checks = [c for c in check_list if c['can_async']]
        sequential_checks = [c for c in check_list if not c['can_async']]

        current_state = None

        # 阶段一：并行检查
        if parallel_checks:
            logger.debug(f"规划阶段一：并行执行 {len(parallel_checks)} 个检查任务。")
            async_tasks = {
                asyncio.create_task(self.orchestrator.execute_task(c['task_name'])): c
                for c in parallel_checks if c['task_name']
            }

            if async_tasks:
                pending_tasks = set(async_tasks.keys())
                try:
                    while pending_tasks and current_state is None:
                        done, pending_tasks = await asyncio.wait(
                            pending_tasks, return_when=asyncio.FIRST_COMPLETED
                        )

                        for task in done:
                            check_info = async_tasks[task]
                            try:
                                result = task.result()
                                # 【新增】添加详细日志，便于调试
                                logger.debug(f"并行状态检查任务 '{check_info['task_name']}' 返回结果: {result}")

                                # 【修复】使用 bool() 放宽检查，将任何 "truthy" 值（如 "True", 1, 非空对象）视为成功
                                if isinstance(result, dict) and result.get('status').upper() == 'SUCCESS' and bool(
                                        result.get('user_data', False)):
                                    current_state = check_info['state_name']
                                    logger.info(f"✅ 状态确认: 当前状态是 '{current_state}'。中断其他检查。")
                                    break
                            except Exception as e:
                                logger.warning(f"状态检查任务 '{check_info['task_name']}' 执行时发生异常: {e}")

                        if current_state:
                            break
                finally:
                    for task in pending_tasks:
                        task.cancel()

        # 阶段二：串行检查 (仅当并行检查未找到状态时执行)
        if current_state is None and sequential_checks:
            logger.debug(f"规划阶段二：串行执行 {len(sequential_checks)} 个检查任务。")
            for check in sequential_checks:
                if not check['task_name']: continue

                logger.info(f"  -> 正在串行检查状态: '{check['state_name']}'...")
                try:
                    result = await self.orchestrator.execute_task(check['task_name'])
                    # 【新增】添加详细日志
                    logger.debug(f"串行状态检查任务 '{check['task_name']}' 返回结果: {result}")

                    # 【修复】同样，使用 bool() 放宽检查
                    if isinstance(result, dict) and result.get('status').upper() == 'SUCCESS' and bool(
                            result.get('user_data', False)):
                        current_state = check['state_name']
                        logger.info(f"✅ 状态确认: 当前状态是 '{current_state}'。")
                        break  # 找到即停
                except Exception as e:
                    logger.warning(f"状态检查任务 '{check['task_name']}' 执行时发生异常: {e}")

        if current_state is None:
            logger.error("所有状态检查任务均未返回成功，无法确定当前系统状态。")

        return current_state

    def find_path(self, start_node: str, end_node: str) -> Optional[List[str]]:
        """
        使用 Dijkstra 算法寻找从 start_node 到 end_node 的成本最低路径。
        """
        if start_node not in self.graph or end_node not in self.graph:
            logger.error(f"路径规划失败: 起点 '{start_node}' 或终点 '{end_node}' 不在状态图中。")
            return None

        priority_queue = [(0, start_node, [])]
        min_costs = {node: float('inf') for node in self.graph}
        min_costs[start_node] = 0

        while priority_queue:
            cost, current_node, path_tasks = heapq.heappop(priority_queue)

            if cost > min_costs[current_node]:
                continue

            if current_node == end_node:
                logger.info(f"路径规划成功: 从 '{start_node}' 到 '{end_node}'，成本为 {cost}，任务路径: {path_tasks}")
                return path_tasks

            for neighbor, edge_cost, task in self.graph.get(current_node, []):
                new_cost = cost + edge_cost
                if new_cost < min_costs[neighbor]:
                    min_costs[neighbor] = new_cost
                    new_path = path_tasks + [task]
                    heapq.heappush(priority_queue, (new_cost, neighbor, new_path))

        logger.warning(f"路径规划失败: 从 '{start_node}' 到 '{end_node}' 找不到可用路径。")
        return None

    def get_expected_state_after_transition(self, from_state: str, transition_task: str) -> Optional[str]:
        """
        辅助方法：从 state_map 中查找一个转移任务执行后应该到达的状态。
        """
        for t in self.state_map.transitions:
            if t.get('from') == from_state and t.get('transition_task') == transition_task:
                return t.get('to')
        return None

    async def verify_state_with_retry(self, state_name: str, retries: int = 5, delay: float = 0.5) -> bool:
        """
        带重试机制地检查当前是否处于某个状态。
        这是一个独立的验证器，用于在状态转移后确认结果。
        """
        check_task = self.state_map.states.get(state_name, {}).get('check_task')
        if not check_task:
            logger.error(f"无法验证状态 '{state_name}'，因为它没有定义 'check_task'。")
            return False

        for attempt in range(retries):
            logger.info(f"正在验证状态 '{state_name}'... (尝试 {attempt + 1}/{retries})")
            try:
                tfr = await self.orchestrator.execute_task(check_task)
                # 检查任务是否成功，并且其业务返回值 (user_data) 为 True 或 'True'
                if tfr and tfr.get('status') == 'SUCCESS' and tfr.get('user_data'):
                    logger.info(f"✅ 状态 '{state_name}' 验证成功。")
                    return True
            except Exception as e:
                logger.warning(f"验证状态 '{state_name}' 时发生异常: {e}", exc_info=False)

            # 如果不是最后一次尝试，就等待一下
            if attempt < retries - 1:
                await asyncio.sleep(delay)

        logger.error(f"在 {retries} 次尝试后，仍无法验证状态 '{state_name}'。")
        return False
"""
定义了 `StatePlanner`（状态规划器）及其相关的数据结构。

该模块的核心是 `StatePlanner` 类，它负责 Aura 框架中的两个关键功能：
1.  **状态确定**: 智能地、高效地确定系统当前所处的抽象状态（例如，“用户已登录”、“应用未运行”）。
    它通过执行与每个状态关联的 `check_task` 来实现这一点，并利用到目标状态的距离
    和优先级来优化检查顺序。
2.  **路径规划**: 当需要从当前状态转换到目标状态时，它使用 Dijkstra 算法在
    `states_map.yaml` 中定义的状态图中寻找成本最低的转换路径。这个路径
    是一系列需要被执行的 `transition_task`。

`StateMap` 是一个简单的数据类，用于加载和持有从 `states_map.yaml` 文件中解析出的状态图定义。
"""
import asyncio
import heapq
from collections import deque
from typing import Dict, List, Optional, Any, Set, TYPE_CHECKING

from packages.aura_core.logger import logger

if TYPE_CHECKING:
    from .orchestrator import Orchestrator

class StateMap:
    """
    一个数据类，用于保存从 `states_map.yaml` 文件解析出的内容。

    Attributes:
        states (Dict[str, Any]): 一个从状态名称映射到其定义的字典。
            每个状态定义可以包含 `check_task`, `priority` 等元数据。
        transitions (List[Dict[str, Any]]): 一个包含所有状态转移定义的列表。
            每个转移定义了 `from` 状态、`to` 状态、执行的 `transition_task` 和 `cost`。
    """

    def __init__(self, data: Dict[str, Any]):
        """
        初始化 StateMap。

        Args:
            data (Dict[str, Any]): 从 `states_map.yaml` 文件安全加载后的字典数据。
        """
        self.states: Dict[str, Any] = data.get('states', {})
        self.transitions: List[Dict[str, Any]] = data.get('transitions', [])
        logger.info(f"StateMap 加载完成: {len(self.states)} 个状态, {len(self.transitions)} 条转移路径。")


class StatePlanner:
    """
    智能状态规划器。

    它结合了高效的状态确定机制和基于Dijkstra算法的最低成本路径规划。
    每个需要状态管理功能的方案（Plan）都会拥有一个 `StatePlanner` 实例。
    """

    def __init__(self, state_map: StateMap, orchestrator: 'Orchestrator'):
        """
        初始化状态规划器。

        Args:
            state_map (StateMap): 已加载的状态图定义。
            orchestrator (Orchestrator): 对父级 `Orchestrator` 的引用，
                用于执行状态检查和状态转移任务。
        """
        self.state_map = state_map
        self.orchestrator = orchestrator
        self.graph = self._build_graph()
        self._reverse_graph = self._build_reverse_graph()

    def _build_graph(self) -> Dict[str, List[tuple]]:
        """
        将 `transitions` 列表预处理成邻接表格式的图，以提高寻路效率。

        Returns:
            Dict[str, List[tuple]]: 一个表示状态图的邻接表。
                键是起始状态，值是一个元组列表 `(邻居状态, 转移成本, 转移任务)`。
        """
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
        """
        构建一个反向图，用于后续的广度优先搜索（BFS）计算。

        Returns:
            Dict[str, Set[str]]: 一个表示反向状态图的邻接表。
        """
        reverse = {state: set() for state in self.state_map.states}
        for from_node, edges in self.graph.items():
            for to_node, _, _ in edges:
                reverse[to_node].add(from_node)
        return reverse

    def _calculate_distances_to_target(self, target_state: str) -> Dict[str, int]:
        """
        使用广度优先搜索(BFS)计算所有状态到目标状态的最短距离（无视权重）。

        这个距离（跳数）被用作状态检查的启发式信息，优先检查离目标“更近”的状态。

        Args:
            target_state (str): 目标状态的名称。

        Returns:
            Dict[str, int]: 一个从状态名称到其距离目标跳数的映射。
        """
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
        使用分阶段、有序、可中断的逻辑来确定当前系统的状态。

        此方法会：
        1.  根据到目标状态的距离和优先级对待检查的状态进行排序。
        2.  首先并行执行所有可并行的检查任务。
        3.  一旦任何一个检查任务返回真值，就立即中断其他检查并返回该状态。
        4.  如果并行检查未找到状态，则继续串行执行不可并行的检查任务。

        Args:
            target_state (str): 期望达到的目标状态，用于优化检查顺序。

        Returns:
            Optional[str]: 探测到的当前状态的名称，如果无法确定则返回 None。
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
                                logger.debug(f"并行状态检查任务 '{check_info['task_name']}' 返回结果: {result}")
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
                    logger.debug(f"串行状态检查任务 '{check['task_name']}' 返回结果: {result}")
                    if isinstance(result, dict) and result.get('status').upper() == 'SUCCESS' and bool(
                            result.get('user_data', False)):
                        current_state = check['state_name']
                        logger.info(f"✅ 状态确认: 当前状态是 '{current_state}'。")
                        break
                except Exception as e:
                    logger.warning(f"状态检查任务 '{check['task_name']}' 执行时发生异常: {e}")

        if current_state is None:
            logger.error("所有状态检查任务均未返回成功，无法确定当前系统状态。")

        return current_state

    def find_path(self, start_node: str, end_node: str) -> Optional[List[str]]:
        """
        使用 Dijkstra 算法寻找从 `start_node` 到 `end_node` 的成本最低的路径。

        Args:
            start_node (str): 起始状态的名称。
            end_node (str): 目标状态的名称。

        Returns:
            Optional[List[str]]: 一个包含按顺序应执行的 `transition_task` 名称的列表。
                如果找不到路径，则返回 None。
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
        辅助方法：从 `state_map` 中查找一个转移任务执行后应该到达的状态。

        Args:
            from_state (str): 转移前的起始状态。
            transition_task (str): 执行的转移任务的名称。

        Returns:
            Optional[str]: 预期的目标状态名称，如果找不到匹配的转移则返回 None。
        """
        for t in self.state_map.transitions:
            if t.get('from') == from_state and t.get('transition_task') == transition_task:
                return t.get('to')
        return None

    async def verify_state_with_retry(self, state_name: str, retries: int = 5, delay: float = 0.5) -> bool:
        """
        带重试机制地检查当前是否处于某个特定状态。

        这是一个独立的验证器，通常在执行完一个状态转移任务后调用，以确认
        系统是否真的达到了预期的状态。

        Args:
            state_name (str): 要验证的状态的名称。
            retries (int): 最大重试次数。
            delay (float): 每次重试之间的等待时间（秒）。

        Returns:
            bool: 如果在重试次数内成功验证状态，则返回 True，否则返回 False。
        """
        check_task = self.state_map.states.get(state_name, {}).get('check_task')
        if not check_task:
            logger.error(f"无法验证状态 '{state_name}'，因为它没有定义 'check_task'。")
            return False

        for attempt in range(retries):
            logger.info(f"正在验证状态 '{state_name}'... (尝试 {attempt + 1}/{retries})")
            try:
                tfr = await self.orchestrator.execute_task(check_task)
                if tfr and tfr.get('status') == 'SUCCESS' and tfr.get('user_data'):
                    logger.info(f"✅ 状态 '{state_name}' 验证成功。")
                    return True
            except Exception as e:
                logger.warning(f"验证状态 '{state_name}' 时发生异常: {e}", exc_info=False)

            if attempt < retries - 1:
                await asyncio.sleep(delay)

        logger.error(f"在 {retries} 次尝试后，仍无法验证状态 '{state_name}'。")
        return False
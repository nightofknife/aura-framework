# plans/state_planner/planner_services/state_planner_service.py (异步升级版)

import asyncio
import heapq
import threading
from collections import defaultdict
from typing import Dict, Any, List, Optional, Tuple

import yaml

from packages.aura_core.api import register_service, service_registry
from packages.aura_core.engine import ExecutionEngine
from packages.aura_core.event_bus import EventBus, Event
from packages.aura_core.logger import logger


# StateGraph 类保持不变，因为它只是一个数据结构
class StateGraph:
    def __init__(self):
        self.nodes: Dict[str, Dict] = {}
        self.edges: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        self.transitions: Dict[Tuple[str, str], Dict] = {}

    def add_state(self, state_data: Dict):
        name = state_data['name']
        self.nodes[name] = state_data

    def add_transition(self, trans_data: Dict, default_cost: float):
        from_state = trans_data['from']
        to_state = trans_data['to']
        cost = float(trans_data.get('cost', default_cost))
        self.edges[from_state].append((to_state, cost))
        self.transitions[(from_state, to_state)] = trans_data

    def find_path(self, start: str, end: str) -> Optional[Tuple[List[str], float]]:
        if start not in self.nodes or end not in self.nodes:
            return None
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
        return None


@register_service(alias="state_planner", public=True)
class StatePlannerService:
    """
    【异步升级版】状态规划服务。
    - 对外保持同步接口 `ensure_state` 不变。
    - 内部使用异步核心 `ensure_state_async`，实现非阻塞的规划与执行。
    """

    def __init__(self, event_bus: EventBus):
        self._map_cache: Dict[str, StateGraph] = {}
        self._plan_orchestrators: Dict[str, Any] = {}
        self.event_bus = event_bus
        logger.info("StatePlannerService (异步核心版) 已初始化。")
        # --- 桥接器组件 ---
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_lock = threading.Lock()

    # =========================================================================
    # Section 1: 公共同步接口 (保持100%向后兼容)
    # =========================================================================

    def ensure_state(self, plan_name: str, target_state: str, map_file: str, timeout: float,
                     default_cost: float) -> bool:
        """
        【同步接口】确保系统达到目标状态。
        此方法会阻塞调用线程，直到规划完成、失败或超时。
        """
        return self._submit_to_loop_and_wait(
            self.ensure_state_async(plan_name, target_state, map_file, timeout, default_cost)
        )

    # =========================================================================
    # Section 2: 内部异步核心实现
    # =========================================================================

    async def ensure_state_async(self, plan_name: str, target_state: str, map_file: str, timeout: float,
                                 default_cost: float) -> bool:
        """【异步内核】执行完整的状态规划流程，全程非阻塞。"""
        logger.info(f"异步规划器目标: 确保处于状态 '{target_state}' (地图: {map_file}, 超时: {timeout}s)")
        await self._publish_event_async("PLANNER_STARTED", {
            "target": target_state, "map_file": map_file, "timeout": timeout
        })

        try:
            async with asyncio.timeout(timeout):
                # 1. 加载地图
                state_map = await self._load_map_async(plan_name, map_file, default_cost)

                # 2. 定位当前状态
                start_state = await self.get_current_state_async(plan_name, state_map)
                if not start_state:
                    logger.error("规划失败：无法确定起始状态。")
                    await self._publish_event_async("PLANNER_FAILED", {"reason": "无法确定起始状态"})
                    return False

                await self._publish_event_async("PLANNER_STATE_LOCATED", {"current_state": start_state})

                if start_state == target_state:
                    logger.info(f"已处于目标状态 '{target_state}'，无需规划。")
                    await self._publish_event_async("PLANNER_SUCCEEDED", {"reason": "已处于目标状态"})
                    return True

                # 3. 寻找路径 (路径查找是CPU密集型，放入线程池)
                path_info = await asyncio.to_thread(state_map.find_path, start_state, target_state)
                if not path_info:
                    logger.error(f"规划失败：找不到从 '{start_state}' 到 '{target_state}' 的路径。")
                    await self._publish_event_async("PLANNER_FAILED",
                                                    {"reason": "找不到路径", "from": start_state, "to": target_state})
                    return False

                path, total_cost = path_info
                logger.info(f"已规划路径: {' -> '.join(path)} (总成本: {total_cost})")
                await self._publish_event_async("PLANNER_PATH_FOUND", {"path": path, "total_cost": total_cost})

                # 4. 执行计划
                for i in range(len(path) - 1):
                    current_step, next_step = path[i], path[i + 1]
                    transition_data = state_map.transitions.get((current_step, next_step))
                    if not transition_data:
                        raise RuntimeError(f"内部错误：路径有效但找不到转移定义 for ({current_step}, {next_step})")

                    step_succeeded = await self._execute_transition_step_with_retry_async(
                        plan_name, state_map, current_step, next_step, transition_data
                    )
                    if not step_succeeded:
                        # 失败事件已在子方法中发布
                        return False

                logger.info(f"成功到达目标状态: '{target_state}'")
                await self._publish_event_async("PLANNER_SUCCEEDED", {"reason": "成功到达目标状态"})
                return True

        except TimeoutError:
            logger.error(f"规划执行超时（超过 {timeout} 秒）。")
            await self._publish_event_async("PLANNER_FAILED", {"reason": "执行超时"})
            return False
        except Exception as e:
            logger.critical(f"状态规划过程中发生未捕获的严重错误: {e}", exc_info=True)
            await self._publish_event_async("PLANNER_FAILED", {"reason": f"未捕获的异常: {e}"})
            return False

    async def _execute_transition_step_with_retry_async(
            self, plan_name: str, state_map: StateGraph, current_step: str, next_step: str, transition_data: Dict
    ) -> bool:
        """【新增】执行单个带重试逻辑的转移步骤。"""
        retry_config = transition_data.get('retry', {})
        max_attempts = retry_config.get('attempts', 1)
        retry_delay = retry_config.get('delay', 1.0)
        post_delay = retry_config.get('post_delay', 1.0)

        for attempt in range(1, max_attempts + 1):
            logger.info(f"执行路径步骤: '{current_step}' -> '{next_step}' (尝试 {attempt}/{max_attempts})")
            await self._publish_event_async("PLANNER_STEP_EXECUTING", {
                "from": current_step, "to": next_step, "attempt": attempt, "max_attempts": max_attempts
            })

            try:
                await self._execute_single_transition_async(plan_name, transition_data)
                await asyncio.sleep(post_delay)  # 非阻塞等待状态稳定
                validated_state = await self.get_current_state_async(plan_name, state_map)

                if validated_state == next_step:
                    logger.info(f"步骤成功: 已到达 '{next_step}'")
                    await self._publish_event_async("PLANNER_STEP_COMPLETED",
                                                    {"state_reached": next_step, "attempts_used": attempt})
                    return True
                else:
                    logger.warning(f"尝试 {attempt} 失败: 期望到达 '{next_step}'，但当前状态是 '{validated_state}'。")

            except Exception as e:
                logger.error(f"尝试 {attempt} 失败: 执行转移时发生异常: {e}", exc_info=True)

            if attempt < max_attempts:
                logger.info(f"将在 {retry_delay} 秒后进行下一次尝试...")
                await asyncio.sleep(retry_delay)

        logger.error(f"步骤失败: 转移 '{current_step}' -> '{next_step}' 在所有 {max_attempts} 次尝试后均未成功。")
        await self._publish_event_async("PLANNER_FAILED", {
            "reason": "转移步骤执行失败", "from": current_step, "to": next_step, "attempts_made": max_attempts
        })
        return False

    # =========================================================================
    # Section 3: 内部异步辅助工具
    # =========================================================================

    async def _publish_event_async(self, name: str, payload: Dict):
        """【修正】异步发布规划器事件的辅助方法。"""
        event = Event(name=name, channel="planner", payload=payload, source="state_planner_service")
        # 直接 await 正确的异步调用
        await self.event_bus.publish(event)

    async def _get_orchestrator_async(self, plan_name: str) -> Any:
        """异步获取或缓存指定方案包的Orchestrator实例。"""
        if plan_name not in self._plan_orchestrators:
            scheduler = service_registry.get_service_instance('scheduler')
            if plan_name in scheduler.plans:
                self._plan_orchestrators[plan_name] = scheduler.plans[plan_name]
            else:
                raise ValueError(f"找不到方案包 '{plan_name}' 的Orchestrator实例。")
        return self._plan_orchestrators[plan_name]

    async def _load_map_async(self, plan_name: str, map_file: str, default_cost: float) -> StateGraph:
        """异步加载状态地图。"""
        orchestrator = await self._get_orchestrator_async(plan_name)
        map_path_str = str(orchestrator.current_plan_path / map_file)
        cache_key = f"{map_path_str}::{default_cost}"
        if cache_key in self._map_cache:
            return self._map_cache[cache_key]

        logger.info(f"正在为方案 '{plan_name}' 异步加载状态地图: {map_file}")
        try:
            # 【修正】使用异步的文件读取方法
            map_content = await orchestrator.get_file_content(map_file)
            map_data = yaml.safe_load(map_content)
        except Exception as e:
            logger.error(f"加载或解析地图文件 '{map_path_str}' 失败: {e}")
            raise

        graph = StateGraph()
        for state in map_data.get('states', []):
            graph.add_state(state)
        for transition in map_data.get('transitions', []):
            graph.add_transition(transition, default_cost)
        self._map_cache[cache_key] = graph

        await self._publish_event_async("PLANNER_MAP_LOADED", {"map_file": map_file})
        return graph

    async def get_current_state_async(self, plan_name: str, state_map: StateGraph) -> Optional[str]:
        """异步确定当前状态。"""
        orchestrator = await self._get_orchestrator_async(plan_name)
        logger.debug("正在异步确定当前状态...")
        for state_name, state_data in state_map.nodes.items():
            check_action = state_data.get('check')
            if not check_action:
                continue
            # 【修正】Orchestrator需要一个异步的条件检查方法
            if await orchestrator.perform_condition_check_async(check_action):
                logger.info(f"当前状态已确定为: '{state_name}'")
                return state_name
        logger.warning("无法确定当前状态，所有状态检查均未通过。")
        return None

    async def _execute_single_transition_async(self, plan_name: str, transition_data: Dict[str, Any]):
        """异步执行单个状态转移的动作。"""
        orchestrator = await self._get_orchestrator_async(plan_name)
        action_data = transition_data.get('action')
        if not isinstance(action_data, dict):
            raise ValueError("无效的转移动作定义")

        context = orchestrator.context_manager.create_context(
            task_id=f"planner_transition/{plan_name}/{action_data.get('action')}"
        )
        engine = ExecutionEngine(context=context, orchestrator=orchestrator)

        # _execute_single_action_step 已经是 async def，所以可以直接 await
        result = await engine._execute_single_action_step(action_data)

        # 检查逻辑失败
        is_logical_failure = (result is False or (hasattr(result, 'found') and result.found is False))
        if is_logical_failure:
            raise RuntimeError(f"状态转移失败: 动作 '{action_data.get('action')}' 返回了失败状态。")

    # =========================================================================
    # Section 4: 同步/异步桥接器
    # =========================================================================

    def _get_running_loop(self) -> asyncio.AbstractEventLoop:
        """线程安全地获取正在运行的事件循环。"""
        with self._loop_lock:
            if self._loop is None or self._loop.is_closed():
                scheduler = service_registry.get_service_instance('scheduler')
                if scheduler and scheduler._loop and scheduler._loop.is_running():
                    self._loop = scheduler._loop
                else:
                    raise RuntimeError("StatePlannerService无法找到正在运行的asyncio事件循环。")
            return self._loop

    def _submit_to_loop_and_wait(self, coro: asyncio.Future) -> Any:
        """将一个协程从同步代码提交到事件循环，并阻塞等待其结果。"""
        loop = self._get_running_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()


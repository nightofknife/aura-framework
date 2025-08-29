# packages/aura_core/execution_manager.py (修改版)

import asyncio
import queue
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from datetime import datetime
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from contextlib import AsyncExitStack

from packages.aura_core.api import hook_manager
from packages.aura_core.task_queue import Tasklet
from packages.aura_core.logger import logger

if TYPE_CHECKING:
    from packages.aura_core.scheduler import Scheduler
    from packages.aura_core.state_planner import StateMap


class ExecutionManager:
    def __init__(self, scheduler: 'Scheduler', max_concurrent_tasks: int = 32, io_workers: int = 16,
                 cpu_workers: int = 4):
        self.scheduler = scheduler
        self.max_concurrent_tasks = max_concurrent_tasks
        self.io_workers = io_workers
        self.cpu_workers = cpu_workers
        self.ui_update_queue: Optional[queue.Queue] = None
        self._io_pool: Optional[ThreadPoolExecutor] = None
        self._cpu_pool: Optional[ProcessPoolExecutor] = None
        self._global_sem = asyncio.Semaphore(max_concurrent_tasks)
        self._resource_sems: Dict[str, asyncio.Semaphore] = {}
        self._resource_sem_lock = asyncio.Lock()

    def set_ui_update_queue(self, q: queue.Queue):
        self.ui_update_queue = q

    async def _get_semaphores_for(self, tasklet: Tasklet) -> List[asyncio.Semaphore]:
        sems = [self._global_sem]
        for tag in tasklet.resource_tags:
            parts = tag.split(':', 1)
            key = parts[0]
            limit = int(parts[1]) if len(parts) > 1 else 1
            async with self._resource_sem_lock:
                if key not in self._resource_sems:
                    self._resource_sems[key] = asyncio.Semaphore(limit)
            sems.append(self._resource_sems[key])
        return sems

    async def submit(self, tasklet: Tasklet, is_interrupt_handler: bool = False):
        if self._io_pool is None or self._cpu_pool is None:
            logger.error("ExecutionManager: 尝试在未启动的执行器上提交任务。请先调用 startup()。")
            raise RuntimeError("Executor pools are not running.")

        task_id_for_status = tasklet.payload.get('id') if tasklet.payload else None
        task_name_for_log = task_id_for_status or tasklet.task_name
        now = datetime.now()
        task_context = {"tasklet": tasklet, "start_time": now}

        if task_id_for_status and not is_interrupt_handler:
            self.scheduler.update_run_status(task_id_for_status, {'status': 'running', 'started_at': now})

        current_task = asyncio.current_task()
        if not is_interrupt_handler:
            with self.scheduler.shared_data_lock:
                self.scheduler.running_tasks[tasklet.task_name] = current_task

        semaphores = await self._get_semaphores_for(tasklet)

        try:
            async with AsyncExitStack() as stack:
                for sem in semaphores:
                    await stack.enter_async_context(sem)

                if not is_interrupt_handler:
                    planning_success = await self._handle_state_planning(tasklet)
                    if not planning_success:
                        raise StatePlanningError(f"任务 '{task_name_for_log}' 的初始状态规划失败。")

                async with asyncio.timeout(tasklet.timeout):
                    logger.info(f"开始执行主任务: '{task_name_for_log}' (模式: {tasklet.execution_mode})")
                    await hook_manager.trigger('before_task_run', task_context=task_context)
                    result = await self._run_execution_chain(tasklet)
                    task_context['end_time'] = datetime.now()
                    task_context['result'] = result
                    await hook_manager.trigger('after_task_success', task_context=task_context)
                    logger.info(f"任务 '{task_name_for_log}' 执行成功。")
                    if task_id_for_status and not is_interrupt_handler:
                        self.scheduler.update_run_status(task_id_for_status,
                                                         {'status': 'idle', 'last_run': now, 'result': 'success'})

        except (asyncio.TimeoutError, asyncio.CancelledError, StatePlanningError) as e:
            status_update = {'status': 'idle', 'last_run': now}
            if isinstance(e, asyncio.TimeoutError):
                logger.error(f"任务 '{task_name_for_log}' 超时 (超过 {tasklet.timeout} 秒)。")
                status_update['result'] = 'timeout'
            elif isinstance(e, asyncio.CancelledError):
                logger.warning(f"任务 '{task_name_for_log}' 被取消。")
                status_update['result'] = 'cancelled'
            else:  # StatePlanningError
                logger.error(str(e))
                status_update['result'] = 'planning_failed'
            task_context['exception'] = e
            if task_id_for_status and not is_interrupt_handler:
                self.scheduler.update_run_status(task_id_for_status, status_update)
            await hook_manager.trigger('after_task_failure', task_context=task_context)
        except Exception as e:
            logger.error(f"任务 '{task_name_for_log}' 执行时发生致命错误: {e}", exc_info=True)
            task_context['exception'] = e
            if task_id_for_status and not is_interrupt_handler:
                self.scheduler.update_run_status(task_id_for_status,
                                                 {'status': 'idle', 'last_run': now, 'result': 'failure'})
            await hook_manager.trigger('after_task_failure', task_context=task_context)
        finally:
            if not is_interrupt_handler:
                with self.scheduler.shared_data_lock:
                    self.scheduler.running_tasks.pop(tasklet.task_name, None)
            await hook_manager.trigger('after_task_run', task_context=task_context)
            logger.info(f"任务 '{task_name_for_log}' 执行完毕，资源已释放。")

    async def _handle_state_planning(self, tasklet: Tasklet) -> bool:
        """【修改】处理状态规划，现在使用 Plan 专属的规划器。"""
        task_def = self.scheduler.all_tasks_definitions.get(tasklet.task_name)
        if not task_def: return True

        target_state = task_def.get('required_initial_state')
        if not target_state: return True

        # --- 【架构修正】从任务所属的 Plan 获取其专属规划器 ---
        plan_name = tasklet.task_name.split('/')[0]
        orchestrator = self.scheduler.plans.get(plan_name)

        if not orchestrator:
            logger.error(f"规划失败: 找不到任务 '{tasklet.task_name}' 所属的方案 '{plan_name}'。")
            return False

        planner = orchestrator.state_planner
        state_map = planner.state_map if planner else None
        # --- 逻辑结束 ---

        if not planner or not state_map:
            logger.warning(f"任务 '{tasklet.task_name}' 需要状态规划，但其所属方案 '{plan_name}' 没有可用的状态规划器。")
            return False

        logger.info(f"任务 '{tasklet.task_name}' 需要初始状态: '{target_state}'。使用方案 '{plan_name}' 的规划器。")

        target_state_def = state_map.states.get(target_state)
        if not target_state_def:
            logger.error(f"规划失败: 目标状态 '{target_state}' 未在方案 '{plan_name}' 的 states_map.yaml 中定义。")
            return False

        is_satisfied = await self._run_internal_task(target_state_def['check_task'])
        if is_satisfied:
            logger.info(f"初始状态 '{target_state}' 已满足，跳过状态转移。")
            return True

        current_state = await self._find_current_state(state_map)
        if not current_state:
            logger.error("规划失败: 无法确定当前系统状态，所有状态检查任务均失败。")
            return False

        logger.info(f"当前状态被确定为: '{current_state}'。")

        transition_tasks = planner.find_path(current_state, target_state)
        if transition_tasks is None:
            return False

        logger.info(f"开始执行状态转移计划: {transition_tasks}")
        for i, transition_task_id in enumerate(transition_tasks):
            logger.info(f"转移步骤 {i + 1}/{len(transition_tasks)}: 执行任务 '{transition_task_id}'...")
            success = await self._run_internal_task(transition_task_id)
            if not success:
                logger.error(f"状态转移失败于步骤 {i + 1}，任务 '{transition_task_id}' 执行失败。")
                return False

        logger.info("状态转移计划执行完毕。正在最后一次验证目标状态...")
        final_check_success = await self._run_internal_task(target_state_def['check_task'])
        if not final_check_success:
            logger.error(f"规划失败: 完成所有转移任务后，系统仍未达到目标状态 '{target_state}'。")
            return False

        logger.info(f"状态规划成功，系统已达到目标状态 '{target_state}'。")
        return True

    async def _find_current_state(self, state_map: 'StateMap') -> Optional[str]:
        check_coroutines = []
        state_names = []
        for name, definition in state_map.states.items():
            check_coroutines.append(self._run_internal_task(definition['check_task']))
            state_names.append(name)

        results = await asyncio.gather(*check_coroutines, return_exceptions=True)

        for i, result in enumerate(results):
            if result is True:
                return state_names[i]

        return None

    async def _run_internal_task(self, task_id: str) -> bool:
        """【修改】一个内部辅助方法，现在能正确处理任务的显式返回值。"""
        if task_id not in self.scheduler.all_tasks_definitions:
            logger.error(f"内部任务执行失败: 任务 '{task_id}' 未定义。")
            return False

        tasklet = Tasklet(task_name=task_id, is_ad_hoc=True, execution_mode='sync')

        try:
            # 直接调用 _run_execution_chain 并捕获其返回值
            result = await self._run_execution_chain(tasklet)

            # --- 【新】更健壮的返回值解析逻辑 ---
            if isinstance(result, bool):
                return result

            if isinstance(result, str):
                # 处理Jinja2可能返回字符串 "True" 或 "False" 的情况
                if result.lower() == 'true':
                    return True
                if result.lower() == 'false':
                    return False

            # 如果返回的是字典，检查 'status' 字段。
            # 这是为了兼容没有 'returns' 字段的老任务，它们成功时会返回 {'status': 'success'}
            if isinstance(result, dict):
                return result.get('status') == 'success'

            # 对于其他类型 (int, NoneType等)，bool() 的行为是正确的
            # 0 -> False, 1 -> True, None -> False
            return bool(result)
            # --- 逻辑结束 ---

        except Exception as e:
            # 任何未捕获的异常都意味着任务失败
            logger.debug(f"内部任务 '{task_id}' 执行时发生异常，视为失败: {e}")
            return False

    async def _run_execution_chain(self, tasklet: Tasklet) -> Any:
        payload = tasklet.payload or {}
        plan_name = payload.get('plan_name')
        task_name_in_plan = payload.get('task') or payload.get('task_name')
        if not plan_name:
            parts = tasklet.task_name.split('/', 1)
            if len(parts) == 2:
                plan_name, task_name_in_plan = parts
            else:
                raise ValueError(f"无法从 tasklet.task_name '{tasklet.task_name}' 中解析出 plan_name。")
        if not plan_name or not task_name_in_plan:
            raise ValueError(f"无法从 tasklet 中确定 plan_name 或 task_name: {tasklet}")
        orchestrator = self.scheduler.plans.get(plan_name)
        if not orchestrator:
            raise RuntimeError(f"在执行任务时找不到方案包 '{plan_name}' 的 Orchestrator。")

        return await orchestrator.execute_task(
            task_name_in_plan,
            tasklet.triggering_event,
            tasklet.initial_context
        )

    def startup(self):
        if self._io_pool is None or self._io_pool._shutdown:
            logger.info(f"ExecutionManager: 正在创建新的IO线程池 (workers={self.io_workers})...")
            self._io_pool = ThreadPoolExecutor(max_workers=self.io_workers, thread_name_prefix="aura-io-worker")
        if self._cpu_pool is None:
            logger.info(f"ExecutionManager: 正在创建新的CPU进程池 (workers={self.cpu_workers})...")
            self._cpu_pool = ProcessPoolExecutor(max_workers=self.cpu_workers)

    def shutdown(self):
        logger.info("ExecutionManager: 正在关闭执行器池...")
        if self._io_pool:
            self._io_pool.shutdown(wait=True)
            self._io_pool = None
            logger.debug("ExecutionManager: IO线程池已关闭。")
        if self._cpu_pool:
            self._cpu_pool.shutdown(wait=True, cancel_futures=True)
            self._cpu_pool = None
            logger.debug("ExecutionManager: CPU进程池已关闭。")
        logger.info("ExecutionManager: 执行器池已完全关闭。")


class StatePlanningError(Exception):
    pass

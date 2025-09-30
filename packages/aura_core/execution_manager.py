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
        """【修复】提交任务执行，迁移 shared_data_lock 到 get_async_lock（异步锁）。"""
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
            # 【修改】原 with self.scheduler.shared_data_lock: → async with get_async_lock()
            async with self.scheduler.get_async_lock():
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
                # 【修改】原 with self.scheduler.shared_data_lock: → async with get_async_lock()
                try:
                    async with self.scheduler.get_async_lock():
                        self.scheduler.running_tasks.pop(tasklet.task_name, None)
                except Exception as lock_e:
                    logger.warning(f"清理 running_tasks 锁异常 (忽略): {lock_e}")  # 【新增】防护，防 finally 崩溃
            await hook_manager.trigger('after_task_run', task_context=task_context)
            logger.debug(f"任务 '{task_name_for_log}' 执行完毕，资源已释放。")  # 【修改】debug 级，避免洪水

    async def _handle_state_planning(self, tasklet: Tasklet) -> bool:
        """
        【最终修正版】处理状态规划，集成健壮的、带重试的转移验证。
        """
        task_def = self.scheduler.all_tasks_definitions.get(tasklet.task_name)
        if not task_def: return True

        target_state = task_def.get('meta', {}).get('requires_initial_state')
        if not target_state:
            return True

        plan_name = tasklet.task_name.split('/')[0]
        orchestrator = self.scheduler.plans.get(plan_name)
        if not orchestrator or not orchestrator.state_planner:
            logger.error(f"规划失败: 任务 '{tasklet.task_name}' 需要状态规划，但方案 '{plan_name}' 没有配置状态规划器。")
            return False

        state_planner = orchestrator.state_planner
        max_replans = 10

        for attempt in range(max_replans):
            logger.info(f"【规划循环 {attempt + 1}/{max_replans}】正在确定当前状态 (目标: '{target_state}')...")

            # 1. 感知 (Perceive)
            current_state = await state_planner.determine_current_state(target_state)
            if not current_state:
                logger.error("无法确定当前系统状态，规划中止。")
                return False

            if current_state == target_state:
                logger.info(f"✅ 状态规划成功，系统已达到目标状态 '{target_state}'。")
                return True

            logger.info(f"当前状态已确认为: '{current_state}'")

            # 2. 规划 (Plan)
            logger.info(f"正在从 '{current_state}' 规划到 '{target_state}' 的路径...")
            path = state_planner.find_path(current_state, target_state)
            if not path:
                logger.error(f"找不到从 '{current_state}' 到 '{target_state}' 的路径，规划中止。")
                return False

            # 3. 行动与验证 (Act & Verify)
            transition_ok = True
            for transition_task in path:
                expected_state = state_planner.get_expected_state_after_transition(current_state, transition_task)
                full_task_id = f"{plan_name}/{transition_task}"

                logger.info(f"执行转移任务: '{full_task_id}' (期望到达: '{expected_state}')...")

                # 执行转移任务
                transition_tfr = await orchestrator.execute_task(transition_task)

                # 检查任务本身是否失败
                if not transition_tfr or transition_tfr.get('status') != 'SUCCESS':
                    logger.warning(f"转移任务 '{full_task_id}' 本身执行失败。将重新规划。")
                    transition_ok = False
                    break  # 中断当前路径，进入下一次重规划循环

                # 任务成功，现在带重试地验证是否到达了期望状态
                if expected_state:
                    # 调用 StatePlanner 中新增的验证方法
                    is_verified = await state_planner.verify_state_with_retry(expected_state)
                    if not is_verified:
                        logger.warning(
                            f"转移任务 '{full_task_id}' 执行成功，但未能验证到达状态 '{expected_state}'。将重新规划。")
                        transition_ok = False
                        break  # 验证失败，中断当前路径，进入下一次重规划循环
                    else:
                        # 验证成功！更新当前状态，为路径中的下一步做准备
                        current_state = expected_state
                else:
                    logger.warning(f"在状态图中找不到任务 '{transition_task}' 对应的目标状态，无法验证，假设成功。")

            if transition_ok:
                # 如果整个路径都成功执行并验证，我们再次确认最终状态
                if current_state == target_state:
                    logger.info(f"✅ 整个状态转移路径成功完成，系统已到达目标状态 '{target_state}'。")
                    return True
                else:
                    logger.warning(
                        f"路径执行完毕，但最终状态为 '{current_state}'，与目标 '{target_state}' 不符。将重新规划。")

            # 如果 transition_ok 为 False，或者路径走完状态不对，就等待一下再重新规划
            await asyncio.sleep(1)

        logger.critical(f"重规划次数达到上限 ({max_replans})，但仍未到达目标状态 '{target_state}'。")
        return False

    async def _run_internal_task(self, task_id: str) -> Dict[str, Any]:
        """
        【升级版】一个内部辅助方法，执行任务并返回统一的字典结果。
        """
        if task_id not in self.scheduler.all_tasks_definitions:
            logger.error(f"内部任务执行失败: 任务 '{task_id}' 未定义。")
            return {'status': 'error', 'reason': 'Task not defined'}

        tasklet = Tasklet(task_name=task_id, is_ad_hoc=True, execution_mode='sync')

        try:
            # 直接调用 _run_execution_chain 并捕获其返回值
            result = await self._run_execution_chain(tasklet)

            # _run_execution_chain -> orchestrator.execute_task 已经返回了统一的字典格式
            # 我们只需要确保如果发生异常，也返回一个标准的错误字典
            return result if isinstance(result, dict) else {'status': 'error', 'reason': 'Invalid return type'}

        except Exception as e:
            logger.debug(f"内部任务 '{task_id}' 执行时发生异常，视为失败: {e}")
            return {'status': 'error', 'reason': str(e)}

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

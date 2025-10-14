# -*- coding: utf-8 -*-
"""Aura 框架的任务执行管理器。

`ExecutionManager` 是任务执行的核心协调者。它负责管理用于IO密集型和CPU
密集型任务的线程池和进程池，处理任务的提交、并发控制，并协调状态规划
（State Planning）等高级功能。

主要职责:
- **执行池管理**: 启动和关闭 `ThreadPoolExecutor` (用于IO任务) 和
  `ProcessPoolExecutor` (用于CPU任务)。
- **任务提交**: 提供 `submit` 方法作为执行任务的统一入口。
- **并发控制**: 使用全局信号量（Semaphore）和基于资源的信号量来限制并发
  执行的任务数量，防止系统过载。
- **状态规划**: 在任务执行前，如果任务定义了 `requires_initial_state`，
  会自动调用 `StatePlanner` 来执行一系列状态转移任务，以确保系统处于
  正确的初始状态。
- **生命周期钩子**: 在任务执行的不同阶段（开始前、成功后、失败后、结束后）
  触发相应的钩子事件。
- **错误处理**: 统一处理任务执行过程中的超时、取消和未知异常。
"""
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


class ExecutionManager:
    """管理执行池和任务提交的核心类。"""
    def __init__(self, scheduler: 'Scheduler', max_concurrent_tasks: int = 32, io_workers: int = 16,
                 cpu_workers: int = 4):
        """初始化 ExecutionManager。

        Args:
            scheduler: 调度器主实例的引用。
            max_concurrent_tasks: 全局最大并发任务数。
            io_workers: IO密集型任务线程池的工作线程数。
            cpu_workers: CPU密集型任务进程池的工作进程数。
        """
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
        """设置用于向UI发送更新的队列。

        Args:
            q: 一个线程安全的队列实例。
        """
        self.ui_update_queue = q

    async def _get_semaphores_for(self, tasklet: Tasklet) -> List[asyncio.Semaphore]:
        """(私有) 根据任务的资源标签获取其需要的所有信号量。"""
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
        """提交一个任务 (Tasklet) 到执行管理器。

        这是执行任务的核心方法。它会处理：
        1. 获取必要的信号量以控制并发。
        2. 如果需要，执行状态规划。
        3. 在指定的超时时间内运行任务的执行链。
        4. 触发所有相关的生命周期钩子。
        5. 统一处理成功、失败、超时和取消等情况。
        6. 确保资源（如信号量和正在运行的任务记录）被正确释放。

        Args:
            tasklet: 要执行的任务单元。
            is_interrupt_handler: 标记此任务是否为中断处理程序，
                若是，则不进行状态规划和某些状态更新。
        """
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
                try:
                    async with self.scheduler.get_async_lock():
                        self.scheduler.running_tasks.pop(tasklet.task_name, None)
                except Exception as lock_e:
                    logger.warning(f"清理 running_tasks 锁异常 (忽略): {lock_e}")
            await hook_manager.trigger('after_task_run', task_context=task_context)
            logger.debug(f"任务 '{task_name_for_log}' 执行完毕，资源已释放。")

    async def _handle_state_planning(self, tasklet: Tasklet) -> bool:
        """(私有) 处理状态规划逻辑。

        如果任务需要特定的初始状态，此方法会：
        1.  感知当前状态。
        2.  规划一条从当前状态到目标状态的路径（一系列转移任务）。
        3.  按顺序执行并验证路径中的每个转移任务。
        4.  如果中途失败，会进行重试，直到达到最大次数。

        Returns:
            bool: 如果成功到达目标状态则返回 True，否则返回 False。
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

            current_state = await state_planner.determine_current_state(target_state)
            if not current_state:
                logger.error("无法确定当前系统状态，规划中止。")
                return False

            if current_state == target_state:
                logger.info(f"✅ 状态规划成功，系统已达到目标状态 '{target_state}'。")
                return True

            logger.info(f"当前状态已确认为: '{current_state}'")

            logger.info(f"正在从 '{current_state}' 规划到 '{target_state}' 的路径...")
            path = state_planner.find_path(current_state, target_state)
            if not path:
                logger.error(f"找不到从 '{current_state}' 到 '{target_state}' 的路径，规划中止。")
                return False

            transition_ok = True
            for transition_task in path:
                expected_state = state_planner.get_expected_state_after_transition(current_state, transition_task)
                full_task_id = f"{plan_name}/{transition_task}"

                logger.info(f"执行转移任务: '{full_task_id}' (期望到达: '{expected_state}')...")

                transition_tfr = await orchestrator.execute_task(transition_task)

                if not transition_tfr or transition_tfr.get('status') != 'SUCCESS':
                    logger.warning(f"转移任务 '{full_task_id}' 本身执行失败。将重新规划。")
                    transition_ok = False
                    break

                if expected_state:
                    is_verified = await state_planner.verify_state_with_retry(expected_state)
                    if not is_verified:
                        logger.warning(
                            f"转移任务 '{full_task_id}' 执行成功，但未能验证到达状态 '{expected_state}'。将重新规划。")
                        transition_ok = False
                        break
                    else:
                        current_state = expected_state
                else:
                    logger.warning(f"在状态图中找不到任务 '{transition_task}' 对应的目标状态，无法验证，假设成功。")

            if transition_ok:
                if current_state == target_state:
                    logger.info(f"✅ 整个状态转移路径成功完成，系统已到达目标状态 '{target_state}'。")
                    return True
                else:
                    logger.warning(
                        f"路径执行完毕，但最终状态为 '{current_state}'，与目标 '{target_state}' 不符。将重新规划。")

            await asyncio.sleep(1)

        logger.critical(f"重规划次数达到上限 ({max_replans})，但仍未到达目标状态 '{target_state}'。")
        return False

    async def _run_internal_task(self, task_id: str) -> Dict[str, Any]:
        """(私有) 一个内部辅助方法，用于执行一个任务并返回标准化的结果字典。"""
        if task_id not in self.scheduler.all_tasks_definitions:
            logger.error(f"内部任务执行失败: 任务 '{task_id}' 未定义。")
            return {'status': 'error', 'reason': 'Task not defined'}

        tasklet = Tasklet(task_name=task_id, is_ad_hoc=True, execution_mode='sync')

        try:
            result = await self._run_execution_chain(tasklet)
            return result if isinstance(result, dict) else {'status': 'error', 'reason': 'Invalid return type'}

        except Exception as e:
            logger.debug(f"内部任务 '{task_id}' 执行时发生异常，视为失败: {e}")
            return {'status': 'error', 'reason': str(e)}

    async def _run_execution_chain(self, tasklet: Tasklet) -> Any:
        """(私有) 运行任务的核心执行链，最终调用 Orchestrator。"""
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
        """启动执行管理器，创建线程池和进程池。"""
        if self._io_pool is None or self._io_pool._shutdown:
            logger.info(f"ExecutionManager: 正在创建新的IO线程池 (workers={self.io_workers})...")
            self._io_pool = ThreadPoolExecutor(max_workers=self.io_workers, thread_name_prefix="aura-io-worker")
        if self._cpu_pool is None:
            logger.info(f"ExecutionManager: 正在创建新的CPU进程池 (workers={self.cpu_workers})...")
            self._cpu_pool = ProcessPoolExecutor(max_workers=self.cpu_workers)

    def shutdown(self):
        """优雅地关闭执行管理器，等待所有池中的任务完成。"""
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
    """在状态规划阶段发生不可恢复的错误时抛出。"""
    pass

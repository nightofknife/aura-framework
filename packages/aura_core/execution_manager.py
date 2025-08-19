import asyncio
import functools
import queue
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from datetime import datetime
from typing import Dict, Any, Optional, List
from contextlib import AsyncExitStack

from packages.aura_core.api import hook_manager
from packages.aura_core.task_queue import Tasklet
from packages.aura_shared_utils.utils.logger import logger


class ExecutionManager:
    """
    【Async Refactor】异步执行管理器与并发控制器。
    - 废除全局锁，使用基于资源的 asyncio.Semaphore 进行精细化并发控制。
    - 管理线程池和进程池，用于执行同步任务和CPU密集型任务。
    - 根据任务的 execution_mode 标签，分派到不同的执行“泳道”。
    - 提供统一的超时、取消和异常处理机制。
    """

    def __init__(self, scheduler, max_concurrent_tasks: int = 32, io_workers: int = 16, cpu_workers: int = 4):
        self.scheduler = scheduler
        self._io_pool = ThreadPoolExecutor(max_workers=io_workers, thread_name_prefix="aura-io-worker")
        self._cpu_pool = ProcessPoolExecutor(max_workers=cpu_workers)

        self._global_sem = asyncio.Semaphore(max_concurrent_tasks)
        self._resource_sems: Dict[str, asyncio.Semaphore] = {}
        self._resource_sem_lock = asyncio.Lock()
        self.ui_update_queue: Optional[queue.Queue] = None

    def set_ui_update_queue(self, q: queue.Queue):  # 【新增】
        """从外部注入UI更新队列。"""
        self.ui_update_queue = q

    async def _get_semaphores_for(self, tasklet: Tasklet) -> List[asyncio.Semaphore]:
        """动态获取任务所需的所有信号量。"""
        sems = [self._global_sem]
        for tag in tasklet.resource_tags:
            # tag format: "resource_name:limit" e.g., "device_camera:1"
            parts = tag.split(':', 1)
            key = parts[0]
            limit = int(parts[1]) if len(parts) > 1 else 1

            async with self._resource_sem_lock:
                if key not in self._resource_sems:
                    self._resource_sems[key] = asyncio.Semaphore(limit)
            sems.append(self._resource_sems[key])
        return sems

    async def submit(self, tasklet: Tasklet, is_interrupt_handler: bool = False):
        """
        提交一个任务以供执行，并管理其生命周期。
        """
        task_id_for_status = tasklet.payload.get('id') if tasklet.payload else None
        task_name_for_log = task_id_for_status or tasklet.task_name
        now = datetime.now()
        task_context = {"tasklet": tasklet, "start_time": now}

        # 【修改】在任务开始前，立即更新状态为 'running'
        if task_id_for_status and not is_interrupt_handler:
            self.scheduler.update_run_status(task_id_for_status, {'status': 'running', 'started_at': now})

        # 将当前异步任务注册到调度器，以便中断时可以取消
        current_task = asyncio.current_task()
        if not is_interrupt_handler:
            with self.scheduler.shared_data_lock:
                self.scheduler.running_tasks[tasklet.task_name] = current_task

        semaphores = []

        try:
            # 1. 获取所有必需的资源锁
            semaphores = await self._get_semaphores_for(tasklet)
            async with AsyncExitStack() as stack:
                for sem in semaphores:
                    await stack.enter_async_context(sem)
                # 2. 在超时控制下执行
                async with asyncio.timeout(tasklet.timeout):
                    logger.info(f"开始执行任务: '{task_name_for_log }' (模式: {tasklet.execution_mode})")
                    await hook_manager.trigger('before_task_run', task_context=task_context)

                    # 3. 根据执行模式分派
                    if tasklet.execution_mode == 'async':
                        result = await self._run_execution_chain(tasklet)
                    else:  # 'sync'
                        executor = self._cpu_pool if tasklet.cpu_bound else self._io_pool
                        loop = asyncio.get_running_loop()
                        # 在线程池中运行整个（现在是异步的）执行链
                        func = functools.partial(asyncio.run, self._run_execution_chain(tasklet))
                        result = await loop.run_in_executor(executor, func)

                    task_context['end_time'] = datetime.now()
                    task_context['result'] = result
                    await hook_manager.trigger('after_task_success', task_context=task_context)
                    logger.info(f"任务 '{task_name_for_log }' 执行成功。")
                    if task_id_for_status  and not is_interrupt_handler:
                        self.scheduler.update_run_status(task_name_for_log ,
                                                         {'status': 'idle', 'last_run': now, 'result': 'success'})

        except (asyncio.TimeoutError, asyncio.CancelledError, Exception) as e:
            # 【修改】任务失败后，更新状态
            if task_id_for_status  and not is_interrupt_handler:
                self.scheduler.update_run_status(task_id_for_status , {'status': 'idle', 'last_run': now, 'result': 'failure'})
            if isinstance(e, asyncio.TimeoutError):
                logger.error(f"任务 '{task_name_for_log }' 超时 (超过 {tasklet.timeout} 秒)。")
                task_context['exception'] = e
            elif isinstance(e, asyncio.CancelledError):
                logger.warning(f"任务 '{task_name_for_log }' 被取消。")
                task_context['exception'] = e
            else:
                logger.error(f"任务 '{task_name_for_log }' 执行时发生致命错误: {e}", exc_info=True)
                task_context['exception'] = e
            await hook_manager.trigger('after_task_failure', task_context=task_context)
        finally:
            # 5. 最终清理
            for sem in reversed(semaphores):
                sem.release()

            if not is_interrupt_handler:
                 with self.scheduler.shared_data_lock:
                    self.scheduler.running_tasks.pop(tasklet.task_name, None)
            await hook_manager.trigger('after_task_run', task_context=task_context)
            logger.info(f"任务 '{task_name_for_log }' 执行完毕，资源已释放。")

    async def _run_execution_chain(self, tasklet: Tasklet) -> Any:
        """调用Orchestrator来启动实际的任务执行逻辑。"""
        payload = tasklet.payload or {}
        plan_name = payload.get('plan_name')
        task_name_in_plan = payload.get('task') or payload.get('task_name')

        if not plan_name:
            # 对于 ad-hoc 或 event-triggered 任务，从 task_name 解析
            plan_name, task_name_in_plan = tasklet.task_name.split('/', 1)

        if not plan_name or not task_name_in_plan:
            raise ValueError(f"无法从 tasklet 中确定 plan_name 或 task_name: {tasklet}")

        orchestrator = self.scheduler.plans.get(plan_name)
        if not orchestrator:
            raise RuntimeError(f"在执行任务时找不到方案包 '{plan_name}' 的 Orchestrator。")

        return await orchestrator.execute_task(task_name_in_plan, tasklet.triggering_event)

    def shutdown(self):
        """关闭执行器池。"""
        logger.info("正在关闭执行器池...")
        self._io_pool.shutdown(wait=True)
        self._cpu_pool.shutdown(wait=True)
        logger.info("执行器池已关闭。")


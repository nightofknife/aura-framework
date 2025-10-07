"""
定义了 `SchedulingService`，一个基于时间的后台调度服务。

该服务的功能类似于一个异步的 `cron`守护进程。它作为一个独立的后台任务运行，
定期（每分钟）检查所有方案中定义的计划任务（通常在 `schedule.yaml` 中定义）。
当一个任务的 `cron` 表达式与当前时间匹配时，它会将该任务封装成一个 `Tasklet`
并放入主任务队列中，等待 `ExecutionManager` 的执行。
"""
import asyncio
from datetime import datetime
from typing import Dict, Any

from croniter import croniter

from packages.aura_core.task_queue import Tasklet
from packages.aura_core.logger import logger
from .asynccontext import plan_context

class SchedulingService:
    """
    异步的时间基准调度服务，也被称为“闹钟”（Alarm Clock）。

    它作为一个独立的后台异步任务运行，定期检查并提交到期的定时任务。
    """

    def __init__(self, scheduler: Any):
        """
        初始化调度服务。

        Args:
            scheduler (Any): 对主调度器 `Scheduler` 的引用，用于访问共享状态和主任务队列。
        """
        self.scheduler = scheduler
        self.is_running = asyncio.Event()

    async def run(self):
        """
        服务的主循环，每分钟检查一次所有定时任务。

        为了提高时间的准确性，循环的等待时间会动态调整，使其在每分钟的开始时刻
        （即第0秒）被唤醒。
        """
        logger.info("时间基准调度服务 (SchedulingService) 正在启动...")
        self.is_running.set()
        try:
            while True:
                if self.scheduler.is_running.is_set():
                    await self._check_and_enqueue_tasks(datetime.now())

                # 等待直到下一分钟的开始，以提高准确性
                now = datetime.now()
                await asyncio.sleep(60 - now.second)
        except asyncio.CancelledError:
            logger.info("时间基准调度服务 (SchedulingService) 已停止。")
        finally:
            self.is_running.clear()

    async def _check_and_enqueue_tasks(self, now: datetime):
        """
        检查所有已定义的计划任务，并将到期的任务异步加入主任务队列。

        此方法会获取所有方案的 `schedule.yaml` 中定义的任务项，并逐一
        调用 `_is_ready_to_run` 来判断是否应该触发。

        Args:
            now (datetime): 当前时间，用于 `croniter` 的计算。
        """
        async with self.scheduler.get_async_lock():
            schedule_items_copy = list(self.scheduler.schedule_items)

        for item in schedule_items_copy:
            item_id = item.get('id')
            plan_name = item.get('plan_name')

            if not item_id or not plan_name or not item.get('enabled', False):
                continue

            async with plan_context(plan_name):
                try:
                    async with self.scheduler.get_async_lock():
                        status = self.scheduler.run_statuses.get(item_id, {})
                        if status.get('status') in ['queued', 'running']:
                            continue

                    if self._is_ready_to_run(item, now, status):
                        logger.info(f"定时任务 '{item.get('name', item_id)}' ({plan_name}) 条件满足，已加入执行队列。")

                        full_task_id = f"{plan_name}/{item['task']}"
                        task_def = self.scheduler.all_tasks_definitions.get(full_task_id, {})

                        tasklet = Tasklet(
                            task_name=full_task_id,
                            payload=item,
                            execution_mode=task_def.get('execution_mode', 'sync')
                        )
                        await self.scheduler.task_queue.put(tasklet)

                        async with self.scheduler.get_async_lock():
                            self.scheduler.run_statuses.setdefault(item_id, {}).update({
                                'status': 'queued',
                                'queued_at': now
                            })
                except Exception as e:
                    logger.error(f"在检查定时任务 '{item_id}' 时发生错误: {e}", exc_info=True)

    def _is_ready_to_run(self, item: Dict[str, Any], now: datetime, status: Dict[str, Any]) -> bool:
        """
        判断单个计划任务项是否已准备好运行。

        主要检查逻辑包括：
        1.  **冷却时间 (Cooldown)**: 检查距离上次运行结束是否已超过指定的冷却时间。
        2.  **时间触发 (Time-based)**: 使用 `croniter` 库检查 `cron` 表达式是否
            与当前时间匹配，并且该匹配的时间点晚于上次的运行时间。

        Args:
            item (Dict[str, Any]): 从 `schedule.yaml` 解析出的单个任务项字典。
            now (datetime): 当前时间。
            status (Dict[str, Any]): 该任务项的当前运行状态字典。

        Returns:
            bool: 如果任务已准备好运行，则返回 True，否则返回 False。
        """
        item_id = item['id']
        cooldown = item.get('run_options', {}).get('cooldown', 0)
        last_run = status.get('last_run')
        if last_run and (now - last_run).total_seconds() < cooldown:
            return False

        trigger = item.get('trigger', {})
        trigger_type = trigger.get('type')

        if trigger_type == 'time_based':
            schedule = trigger.get('schedule')
            if not schedule:
                return False
            try:
                iterator = croniter(schedule, now)
                prev_scheduled_run = iterator.get_prev(datetime)
                effective_last_run = last_run or datetime.min
                if prev_scheduled_run > effective_last_run:
                    return True
            except Exception as e:
                logger.error(f"任务 '{item_id}' 的 cron 表达式 '{schedule}' 无效: {e}")

        return False
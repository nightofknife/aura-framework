import asyncio
from datetime import datetime

from croniter import croniter

from packages.aura_core.task_queue import Tasklet
from packages.aura_core.logger import logger


class SchedulingService:
    """
    【Async Refactor】异步的时间基准调度服务 (闹钟)。
    作为一个独立的后台异步任务运行，定期检查并提交到期的任务。
    """

    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.is_running = asyncio.Event()

    async def run(self):
        """服务的主循环，每分钟检查一次所有定时任务。"""
        logger.info("时间基准调度服务 (SchedulingService) 正在启动...")
        self.is_running.set()
        try:
            while True:
                if self.scheduler.is_running.is_set():
                    await self._check_and_enqueue_tasks(datetime.now())

                await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.info("时间基准调度服务 (SchedulingService) 已停止。")
        finally:
            self.is_running.clear()

    async def _check_and_enqueue_tasks(self, now: datetime):
        """检查所有调度项，并将到期的任务异步加入主任务队列。"""
        with self.scheduler.shared_data_lock:
            schedule_items_copy = list(self.scheduler.schedule_items)

        for item in schedule_items_copy:
            item_id = item.get('id')
            if not item_id or not item.get('enabled', False):
                continue

            with self.scheduler.shared_data_lock:
                status = self.scheduler.run_statuses.get(item_id, {})
                if status.get('status') in ['queued', 'running']:
                    continue

            if self._is_ready_to_run(item, now, status):
                logger.info(f"定时任务 '{item.get('name', item_id)}' ({item['plan_name']}) 条件满足，已加入执行队列。")

                full_task_id = f"{item['plan_name']}/{item['task']}"
                task_def = self.scheduler.all_tasks_definitions.get(full_task_id, {})

                tasklet = Tasklet(
                    task_name=full_task_id,
                    payload=item,
                    execution_mode=task_def.get('execution_mode', 'sync')
                )
                await self.scheduler.task_queue.put(tasklet)

                with self.scheduler.shared_data_lock:
                    self.scheduler.run_statuses.setdefault(item_id, {}).update({
                        'status': 'queued',
                        'queued_at': now
                    })

    def _is_ready_to_run(self, item, now, status) -> bool:
        # ... (此方法逻辑不变) ...
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

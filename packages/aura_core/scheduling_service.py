# -*- coding: utf-8 -*-
"""Aura 框架的时间基准调度服务。

此模块定义了 `SchedulingService`，它像一个“闹钟”一样工作。
它作为一个独立的后台异步任务运行，其核心职责是定期（每分钟）检查
所有在 `schedule.yaml` 文件中定义的、基于时间的计划任务。
"""
import asyncio
from datetime import datetime

from croniter import croniter

from packages.aura_core.logger import logger
from .asynccontext import plan_context
from packages.aura_core.config_loader import get_config_value

class SchedulingService:
    """异步的时间基准调度服务。

    作为一个独立的后台异步任务运行，定期检查所有已启用的、基于时间的
    计划任务，并将到期的任务提交到主任务队列中。
    """

    def __init__(self, scheduler):
        """初始化调度服务。

        Args:
            scheduler: 调度器主实例的引用。
        """
        self.scheduler = scheduler
        self.is_running = asyncio.Event()
        self.tick_sec = int(get_config_value("scheduling_service.tick_sec", 60))

    async def run(self):
        """服务的主循环，每分钟检查一次所有定时任务。

        此方法会无限循环，直到被取消。为了提高调度的准确性，它会计算
        并等待到下一分钟的零秒时刻再执行检查。
        """
        logger.info("时间基准调度服务 (SchedulingService) 正在启动...")
        self.is_running.set()
        try:
            while True:
                if self.scheduler.is_running.is_set():
                    await self._check_and_enqueue_tasks(datetime.now())

                now = datetime.now()
                sleep_for = max(1, self.tick_sec - (now.second % self.tick_sec))
                await asyncio.sleep(sleep_for)
        except asyncio.CancelledError:
            logger.info("时间基准调度服务 (SchedulingService) 已停止。")
        finally:
            self.is_running.clear()

    async def _check_and_enqueue_tasks(self, now: datetime):
        """(私有) 检查所有调度项，并将到期的任务异步加入主任务队列。"""
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

                    if self._is_ready_to_run(item, now, status) and self._has_cron_trigger_match(item, now, status):
                        logger.info(f"定时任务 '{item.get('name', item_id)}' ({plan_name}) 条件满足，已加入执行队列。")


                        await self.scheduler._enqueue_schedule_item(item, source="schedule")

                except Exception as e:
                    logger.error(f"在检查定时任务 '{item_id}' 时发生错误: {e}", exc_info=True)

    def _is_ready_to_run(self, item: dict, now: datetime, status: dict) -> bool:
        """(private) Decide whether a schedule item can run now.

        Checks:
        1. Cooldown window.
        """
        cooldown = item.get('run_options', {}).get('cooldown', 0)
        last_run = status.get('last_run')
        if last_run and (now - last_run).total_seconds() < cooldown:
            return False
        return True

    def _has_cron_trigger_match(self, item: dict, now: datetime, status: dict) -> bool:
        triggers = item.get('triggers') or []
        if not isinstance(triggers, list):
            return False
        last_run = status.get('last_run')
        for trigger in triggers:
            if not isinstance(trigger, dict):
                continue
            if trigger.get('type') != 'cron':
                continue
            expression = trigger.get('expression')
            if not expression:
                continue
            try:
                iterator = croniter(expression, now)
                prev_scheduled_run = iterator.get_prev(datetime)
                effective_last_run = last_run or datetime.min
                if prev_scheduled_run > effective_last_run:
                    return True
            except Exception as e:
                item_id = item.get('id')
                logger.error(f"Invalid cron expression for schedule '{item_id}': {expression} ({e})")
        return False
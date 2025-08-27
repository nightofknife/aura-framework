# packages/aura_core/scheduling_service.py (Fixed with Context Isolation)

import asyncio
from datetime import datetime

from croniter import croniter

from packages.aura_core.task_queue import Tasklet
from packages.aura_core.logger import logger
# 【修复】导入用于设置配置上下文的 ContextVar
from plans.aura_base.services.config_service import current_plan_name


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

                # 等待直到下一分钟的开始，以提高准确性
                now = datetime.now()
                await asyncio.sleep(60 - now.second)
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
            plan_name = item.get('plan_name')

            if not item_id or not plan_name or not item.get('enabled', False):
                continue

            # 【修复】为每个任务的检查设置独立的上下文
            token = current_plan_name.set(plan_name)
            try:
                with self.scheduler.shared_data_lock:
                    status = self.scheduler.run_statuses.get(item_id, {})
                    if status.get('status') in ['queued', 'running']:
                        continue

                # 现在 _is_ready_to_run 可以在正确的上下文中安全地执行任何操作
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

                    with self.scheduler.shared_data_lock:
                        self.scheduler.run_statuses.setdefault(item_id, {}).update({
                            'status': 'queued',
                            'queued_at': now
                        })
            except Exception as e:
                logger.error(f"在检查定时任务 '{item_id}' 时发生错误: {e}", exc_info=True)
            finally:
                # 【修复】无论成功与否，都必须重置上下文
                current_plan_name.reset(token)

    def _is_ready_to_run(self, item, now, status) -> bool:
        # 这个方法本身不需要修改，但现在它在被调用时，已经处于正确的上下文中了。
        # 这使得未来在这里添加配置依赖的检查成为可能和安全的。
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
                # croniter 检查逻辑保持不变
                iterator = croniter(schedule, now)
                prev_scheduled_run = iterator.get_prev(datetime)
                effective_last_run = last_run or datetime.min
                if prev_scheduled_run > effective_last_run:
                    return True
            except Exception as e:
                logger.error(f"任务 '{item_id}' 的 cron 表达式 '{schedule}' 无效: {e}")

        # 在这里可以安全地添加其他 trigger_type 的检查，例如：
        # elif trigger_type == 'condition_based':
        #     orchestrator = self.scheduler.plans.get(item['plan_name'])
        #     if orchestrator and await orchestrator.perform_condition_check(...):
        #         return True

        return False


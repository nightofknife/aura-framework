# packages/aura_core/scheduling_service.py (全新文件)

import threading
import time
from datetime import datetime
from typing import Dict

from croniter import croniter

from packages.aura_core.task_queue import Tasklet
from packages.aura_shared_utils.utils.logger import logger


class SchedulingService:
    """
    时间基准调度服务 (闹钟)。
    负责处理所有在 schedule.yaml 中定义的、基于 cron 表达式的定时任务。
    它作为一个独立的后台服务运行，定期检查并提交到期的任务。
    """

    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.lock = scheduler.lock  # 复用 Scheduler 的锁
        self.is_running = threading.Event()
        self.thread: threading.Thread = None

    def start(self):
        """启动调度服务线程。"""
        if self.is_running.is_set():
            logger.warning("SchedulingService 已经在运行中。")
            return

        logger.info("时间基准调度服务 (SchedulingService) 正在启动...")
        self.is_running.set()
        self.thread = threading.Thread(target=self._scheduling_loop, name="SchedulingServiceThread", daemon=True)
        self.thread.start()

    def stop(self):
        """停止调度服务线程。"""
        if not self.is_running.is_set():
            return

        logger.info("时间基准调度服务 (SchedulingService) 正在停止...")
        self.is_running.clear()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        logger.info("时间基准调度服务 (SchedulingService) 已停止。")

    def _scheduling_loop(self):
        """服务的主循环，每分钟检查一次所有定时任务。"""
        while self.is_running.is_set():
            # 只有当调度器本身也在运行时才检查
            if self.scheduler.is_scheduler_running.is_set():
                self._check_and_enqueue_tasks(datetime.now())

            # 每分钟检查一次，对于 cron 来说足够了
            time.sleep(60)
        logger.info("SchedulingService 循环已安全退出。")

    def _check_and_enqueue_tasks(self, now: datetime):
        """
        检查所有调度项，并将到期的任务加入主任务队列。
        这是从 Scheduler 中迁移过来的核心逻辑。
        """
        with self.lock:
            # 创建副本以避免在迭代时修改
            schedule_items_copy = list(self.scheduler.schedule_items)

            for item in schedule_items_copy:
                item_id = item.get('id')
                if not item_id:
                    continue

                # 检查任务是否启用，以及是否已经是活动状态
                if not item.get('enabled', False):
                    continue

                status = self.scheduler.run_statuses.get(item_id, {})
                if status.get('status') in ['queued', 'running']:
                    continue

                # 检查是否满足运行条件
                if self._is_ready_to_run(item, now, status):
                    logger.info(
                        f"定时任务 '{item.get('name', item_id)}' ({item['plan_name']}) 条件满足，已加入执行队列。")

                    # 将任务封装为 Tasklet 并放入 Scheduler 的主队列
                    tasklet = Tasklet(task_name=item_id, payload=item)
                    self.scheduler.task_queue.put(tasklet)

                    # 更新任务状态为已入队
                    self.scheduler.run_statuses.setdefault(item_id, {}).update({
                        'status': 'queued',
                        'queued_at': now
                    })

    def _is_ready_to_run(self, item: Dict, now: datetime, status: Dict) -> bool:
        """
        判断一个任务项是否准备好运行。
        这是从 Scheduler 中迁移过来的核心逻辑。
        """
        item_id = item['id']

        # 1. 检查冷却时间
        cooldown = item.get('run_options', {}).get('cooldown', 0)
        last_run = status.get('last_run')
        if last_run and (now - last_run).total_seconds() < cooldown:
            return False

        # 2. 检查触发器类型和条件
        trigger = item.get('trigger', {})
        trigger_type = trigger.get('type')

        if trigger_type == 'time_based':
            schedule = trigger.get('schedule')
            if not schedule:
                logger.warning(f"任务 '{item_id}' 是 time_based 类型，但缺少 'schedule' 表达式。")
                return False

            try:
                # 使用 croniter 检查上一个预定运行时间点
                iterator = croniter(schedule, now)
                prev_scheduled_run = iterator.get_prev(datetime)

                # 如果上一个预定运行时间点晚于任务的最后一次实际运行时间，说明到期了
                effective_last_run = last_run or datetime.min
                if prev_scheduled_run > effective_last_run:
                    logger.debug(
                        f"任务 '{item_id}' 已到期。上次运行: {effective_last_run}, 上个预定点: {prev_scheduled_run}")
                    return True
                return False
            except Exception as e:
                logger.error(f"任务 '{item_id}' 的 cron 表达式 '{schedule}' 无效: {e}")
                return False

        # SchedulingService 只关心 'time_based' 类型的任务
        return False

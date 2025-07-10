# packages/aura_core/interrupt_service.py (全新文件)

import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Set, Optional

from packages.aura_shared_utils.utils.logger import logger


class InterruptService:
    """
    中断服务 (哨兵/守护者)。
    负责监控系统状态，并在满足条件时触发中断。
    它作为一个独立的后台服务运行，定期检查所有激活的中断规则。
    """

    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.lock = scheduler.lock  # 复用 Scheduler 的锁
        self.is_running = threading.Event()
        self.thread: threading.Thread = None

    def start(self):
        """启动中断监控服务线程。"""
        if self.is_running.is_set():
            logger.warning("InterruptService 已经在运行中。")
            return

        logger.info("中断监控服务 (InterruptService/Guardian) 正在启动...")
        self.is_running.set()
        self.thread = threading.Thread(target=self._guardian_loop, name="GuardianThread", daemon=True)
        self.thread.start()

    def stop(self):
        """停止中断监控服务线程。"""
        if not self.is_running.is_set():
            return

        logger.info("中断监控服务 (InterruptService/Guardian) 正在停止...")
        self.is_running.clear()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        logger.info("中断监控服务 (InterruptService/Guardian) 已停止。")

    def _guardian_loop(self):
        """服务的主循环，负责监控中断条件。"""
        while self.is_running.is_set():
            if not self.scheduler.is_scheduler_running.is_set():
                time.sleep(1)
                continue

            active_interrupts = self._get_active_interrupts()
            now = datetime.now()

            for rule_name in active_interrupts:
                should_check, rule = self._should_check_interrupt(rule_name, now)
                if not should_check:
                    continue

                logger.debug(f"守护者: 正在检查中断条件 '{rule_name}'...")
                try:
                    # 委托给 Orchestrator 进行条件检查
                    orchestrator = self.scheduler.plans.get(rule['plan_name'])
                    if orchestrator and orchestrator.perform_condition_check(rule.get('condition', {})):
                        logger.warning(f"检测到中断条件: '{rule_name}'! 已提交给指挥官处理。")
                        self._submit_interrupt(rule, now)
                        break  # 一次只处理一个中断，避免中断风暴
                except Exception as e:
                    logger.error(f"守护者在检查中断 '{rule_name}' 时出错: {e}", exc_info=True)

            time.sleep(1)  # 守护者需要较快的响应速度
        logger.info("InterruptService 循环已安全退出。")

    def _get_active_interrupts(self) -> Set[str]:
        """
        确定当前需要监控哪些中断规则。
        这是从 Scheduler 中迁移过来的核心逻辑。
        """
        with self.lock:
            # 1. 获取所有用户启用的全局中断
            active_set = self.scheduler.user_enabled_globals.copy()

            # 2. 获取当前运行任务所激活的局部中断
            current_task_item = self.scheduler.current_running_task
            if current_task_item:
                plan_name = current_task_item.get('plan_name')
                task_id_in_plan = current_task_item.get('task') or current_task_item.get('task_name')

                if plan_name and task_id_in_plan:
                    full_task_id = f"{plan_name}/{task_id_in_plan}"
                    task_def = self.scheduler.all_tasks_definitions.get(full_task_id)
                    if task_def:
                        active_set.update(task_def.get('activates_interrupts', []))

        return active_set

    def _should_check_interrupt(self, rule_name: str, now: datetime) -> (bool, Optional[Dict]):
        """
        判断一个中断规则是否应该在此时被检查（考虑冷却和间隔）。
        这是从 Scheduler 中迁移过来的核心逻辑。
        """
        with self.lock:
            rule = self.scheduler.interrupt_definitions.get(rule_name)
            if not rule:
                return False, None

            cooldown_expired = now >= self.scheduler.interrupt_cooldown_until.get(rule_name, datetime.min)
            last_check = self.scheduler.interrupt_last_check_times.get(rule_name, datetime.min)
            interval_passed = (now - last_check).total_seconds() >= rule.get('check_interval', 5)

            if cooldown_expired and interval_passed:
                self.scheduler.interrupt_last_check_times[rule_name] = now
                return True, rule
            return False, None

    def _submit_interrupt(self, rule: Dict, now: datetime):
        """
        将触发的中断放入 Scheduler 的队列并设置冷却时间。
        这是从 Scheduler 中迁移过来的核心逻辑。
        """
        with self.lock:
            self.scheduler.interrupt_queue.append(rule)
            cooldown_seconds = rule.get('cooldown', 60)
            self.scheduler.interrupt_cooldown_until[rule['name']] = now + timedelta(seconds=cooldown_seconds)

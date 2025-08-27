# packages/aura_core/interrupt_service.py (Fixed with Context Isolation)

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Set, Optional

from packages.aura_core.logger import logger
# 【修复】导入用于设置配置上下文的 ContextVar
from plans.aura_base.services.config_service import current_plan_name


class InterruptService:
    """
    【Async Refactor】异步中断服务 (哨兵/守护者)。
    作为一个独立的后台异步任务运行，定期检查所有激活的中断规则。
    """

    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.is_running = asyncio.Event()
        # 状态现在由 Scheduler 统一管理，但服务需要一个锁来安全地访问它们
        self.lock = scheduler.shared_data_lock
        self.interrupt_last_check_times: Dict[str, datetime] = {}
        self.interrupt_cooldown_until: Dict[str, datetime] = {}

    async def run(self):
        """服务的主循环，负责监控中断条件。"""
        logger.info("中断监控服务 (InterruptService/Guardian) 正在启动...")
        self.is_running.set()
        try:
            while True:
                # 仅在调度器未暂停时运行
                if self.scheduler.is_running.is_set():
                    active_interrupts = self._get_active_interrupts()
                    now = datetime.now()

                    for rule_name in active_interrupts:
                        should_check, rule = self._should_check_interrupt(rule_name, now)
                        if not should_check:
                            continue

                        logger.trace(f"守护者: 正在检查中断条件 '{rule_name}'...")

                        # 【修复】在进行条件检查前，设置正确的方案上下文
                        token = current_plan_name.set(rule['plan_name'])
                        try:
                            orchestrator = self.scheduler.plans.get(rule['plan_name'])
                            if orchestrator and await orchestrator.perform_condition_check(rule.get('condition', {})):
                                logger.warning(f"检测到中断条件: '{rule_name}'! 已提交给指挥官处理。")
                                await self._submit_interrupt(rule, now)
                                break  # 一次只处理一个中断
                        except Exception as e:
                            logger.error(f"守护者在检查中断 '{rule_name}' 时出错: {e}", exc_info=True)
                        finally:
                            # 【修复】无论检查成功与否，都必须重置上下文
                            current_plan_name.reset(token)

                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("中断监控服务 (InterruptService/Guardian) 已停止。")
        finally:
            self.is_running.clear()

    def _get_active_interrupts(self) -> Set[str]:
        """确定当前需要监控哪些中断规则。"""
        with self.lock:
            # 复制一份以避免在迭代时修改
            interrupt_definitions = dict(self.scheduler.interrupt_definitions)
            user_enabled_globals = self.scheduler.user_enabled_globals.copy()
            running_task_ids = list(self.scheduler.running_tasks.keys())
            all_tasks_defs = dict(self.scheduler.all_tasks_definitions)

        # 始终激活用户启用的全局中断
        active_set = user_enabled_globals

        # 添加当前正在运行的任务所激活的中断
        for task_id in running_task_ids:
            task_def = all_tasks_defs.get(task_id)
            if task_def:
                active_set.update(task_def.get('activates_interrupts', []))

        # 过滤掉不存在的规则定义
        return {rule_name for rule_name in active_set if rule_name in interrupt_definitions}

    def _should_check_interrupt(self, rule_name: str, now: datetime) -> (bool, Optional[Dict]):
        """判断一个中断规则是否应该在此时被检查。"""
        with self.lock:
            rule = self.scheduler.interrupt_definitions.get(rule_name)
        if not rule:
            return False, None

        cooldown_expired = now >= self.interrupt_cooldown_until.get(rule_name, datetime.min)
        if not cooldown_expired:
            return False, None

        last_check = self.interrupt_last_check_times.get(rule_name, datetime.min)
        interval_passed = (now - last_check).total_seconds() >= rule.get('check_interval', 5)

        if interval_passed:
            self.interrupt_last_check_times[rule_name] = now
            return True, rule

        return False, None

    async def _submit_interrupt(self, rule: Dict, now: datetime):
        """将触发的中断异步放入 Scheduler 的队列并设置冷却时间。"""
        if self.scheduler.interrupt_queue:
            await self.scheduler.interrupt_queue.put(rule)
            cooldown_seconds = rule.get('cooldown', 60)
            self.interrupt_cooldown_until[rule['name']] = now + timedelta(seconds=cooldown_seconds)
        else:
            logger.error("无法提交中断，因为中断队列尚未初始化。")


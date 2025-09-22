import asyncio
import threading
from datetime import datetime, timedelta
from typing import Dict, Set, Optional

from packages.aura_core.logger import logger
from plans.aura_base.services.config_service import current_plan_name
from .asynccontext import plan_context

class InterruptService:
    """
    【Async Refactor】异步中断服务 (哨兵/守护者)。
    作为一个独立的后台异步任务运行，定期检查所有激活的中断规则。
    """

    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.is_running = asyncio.Event()
        # 【确认】移除 self.lock；用 self.scheduler.get_async_lock() 动态获取
        self.interrupt_last_check_times: Dict[str, datetime] = {}
        self.interrupt_cooldown_until: Dict[str, datetime] = {}

    async def run(self):
        """服务的主循环，负责监控中断条件。"""
        logger.info("中断监控服务 (InterruptService/Guardian) 正在启动...")
        self.is_running.set()
        try:
            while True:
                if self.scheduler.is_running.is_set():
                    # 【修改】await 异步 _get_active_interrupts（因为现在是 async def）
                    active_interrupts = await self._get_active_interrupts()  # 【新增】await
                    now = datetime.now()

                    for rule_name in active_interrupts:
                        # 【修改】await 异步 _should_check_interrupt
                        should_check, rule = await self._should_check_interrupt(rule_name, now)  # 【新增】await
                        if not should_check:
                            continue

                        logger.trace(f"守护者: 正在检查中断条件 '{rule_name}'...")

                        # 【确认】用 async with plan_context 包裹检查
                        async with plan_context(rule['plan_name']):
                            try:
                                orchestrator = self.scheduler.plans.get(rule[
                                                                            'plan_name'])  # 【新增】plans 是 plan_manager.plans（如果无，改为 self.scheduler.plan_manager.plans）
                                if orchestrator and await orchestrator.perform_condition_check(
                                        rule.get('condition', {})):
                                    logger.warning(f"检测到中断条件: '{rule_name}'! 已提交给指挥官处理。")
                                    await self._submit_interrupt(rule, now)
                                    break  # 一次只处理一个中断
                            except Exception as e:
                                logger.error(f"守护者在检查中断 '{rule_name}' 时出错: {e}", exc_info=True)
                                # 管理器确保 reset，即使异常

                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("中断监控服务 (InterruptService/Guardian) 已停止。")
        finally:
            self.is_running.clear()

    async def _get_active_interrupts(self) -> Set[str]:
        """【修改】异步确定当前需要监控哪些中断规则。直接 await async_get，无嵌套 run_until_complete。"""

        async def async_get():
            async with self.scheduler.get_async_lock():  # 【确认】异步锁
                # 复制一份以避免在迭代时修改
                interrupt_definitions = dict(self.scheduler.interrupt_definitions)
                user_enabled_globals = self.scheduler.user_enabled_globals.copy()
                running_task_ids = list(self.scheduler.running_tasks.keys())
                all_tasks_defs = dict(self.scheduler.all_tasks_definitions)

            # 始终激活用户启用的全局中断
            active_set = set(user_enabled_globals)

            # 添加当前正在运行的任务所激活的中断
            for task_id in running_task_ids:
                task_def = all_tasks_defs.get(task_id)
                if task_def:
                    # 【确认】原修复
                    interrupts_to_activate = task_def.get('activates_interrupts')
                    if isinstance(interrupts_to_activate, list) and interrupts_to_activate:
                        active_set.update(interrupts_to_activate)
                        logger.debug(f"任务 '{task_id}' 激活了中断: {interrupts_to_activate}")

            # 过滤掉不存在的规则定义
            return {rule_name for rule_name in active_set if rule_name in interrupt_definitions}

        # 【修改】直接 await（run() 已异步）；fallback 只在异常时
        try:
            return await async_get()
        except RuntimeError as e:
            if "event loop is already running" in str(e).lower():
                logger.warning("嵌套事件循环检测到，fallback 到同步实现。")
                # 【确认】完整 fallback
                with self.scheduler.fallback_lock:
                    interrupt_definitions = dict(self.scheduler.interrupt_definitions)
                    user_enabled_globals = self.scheduler.user_enabled_globals.copy()
                    running_task_ids = list(self.scheduler.running_tasks.keys())
                    all_tasks_defs = dict(self.scheduler.all_tasks_definitions)
                    active_set = set(user_enabled_globals)
                    for task_id in running_task_ids:
                        task_def = all_tasks_defs.get(task_id)
                        if task_def:
                            interrupts_to_activate = task_def.get('activates_interrupts')
                            if isinstance(interrupts_to_activate, list) and interrupts_to_activate:
                                active_set.update(interrupts_to_activate)
                                logger.debug(f"任务 '{task_id}' 激活了中断: {interrupts_to_activate}")
                    return {rule_name for rule_name in active_set if rule_name in interrupt_definitions}
            else:
                logger.error(f"RuntimeError in _get_active_interrupts: {e}")
                raise e
        except Exception as e:
            logger.error(f"Unexpected error in _get_active_interrupts: {e}", exc_info=True)
            return set()  # 安全返回空集

    async def _should_check_interrupt(self, rule_name: str, now: datetime) -> tuple[bool, Optional[Dict]]:
        """【修改】异步判断一个中断规则是否应该在此时被检查。直接 await async_should_check。"""

        async def async_should_check():
            async with self.scheduler.get_async_lock():  # 【确认】异步锁
                rule = self.scheduler.interrupt_definitions.get(rule_name)
            if not rule:
                return False, None

            cooldown_expired = now >= self.interrupt_cooldown_until.get(rule_name, datetime.min)
            if not cooldown_expired:
                return False, None

            last_check = self.interrupt_last_check_times.get(rule_name, datetime.min)
            interval_passed = (now - last_check).total_seconds() >= rule.get('check_interval', 5)

            # 更新 last_check 在锁外（原子）
            if interval_passed:
                self.interrupt_last_check_times[rule_name] = now  # 【确认】原代码
            return interval_passed, rule

        # 【修改】直接 await；fallback 类似
        try:
            return await async_should_check()
        except RuntimeError as e:
            if "event loop is already running" in str(e).lower():
                logger.warning("嵌套事件循环检测到，fallback 到同步实现。")
                # 【确认】完整 fallback
                with self.scheduler.fallback_lock:
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
                    return interval_passed, rule
            else:
                logger.error(f"RuntimeError in _should_check_interrupt: {e}")
                raise e
        except Exception as e:
            logger.error(f"Unexpected error in _should_check_interrupt: {e}", exc_info=True)
            return False, None  # 安全返回

    async def _submit_interrupt(self, rule: Dict, now: datetime):
        """将触发的中断异步放入 Scheduler 的队列并设置冷却时间。"""
        async with self.scheduler.get_async_lock():  # 【确认】异步锁
            if self.scheduler.interrupt_queue:
                await self.scheduler.interrupt_queue.put(rule)
                cooldown_seconds = rule.get('cooldown', 60)
                self.interrupt_cooldown_until[rule['name']] = now + timedelta(seconds=cooldown_seconds)
            else:
                logger.error("无法提交中断，因为中断队列尚未初始化。")
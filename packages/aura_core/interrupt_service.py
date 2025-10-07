"""
定义了 `InterruptService`，一个作为后台守护进程运行的异步服务。

该服务的主要职责是持续监控系统中所有已激活的中断规则。当某个中断
规则的条件被满足时，它会将一个中断信号提交给 `Scheduler` 的中断队列，
由 `Scheduler` 负责暂停当前任务并执行相应的中断处理流程。

`InterruptService` 的设计是完全异步的，它独立于主任务执行流程，
通过定期检查和条件评估来工作，是实现响应式和事件驱动自动化逻辑的核心组件。
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Set, Optional, Any

from packages.aura_core.logger import logger
from .asynccontext import plan_context

class InterruptService:
    """
    异步中断服务，也被称为“守护者”（Guardian）。

    它作为一个独立的后台异步任务运行，定期检查所有被激活的中断规则。
    中断规则可以由正在运行的任务动态激活，也可以由用户全局启用。
    """

    def __init__(self, scheduler: Any):
        """
        初始化中断服务。

        Args:
            scheduler (Any): 对主调度器 `Scheduler` 的引用，用于访问共享状态和队列。
        """
        self.scheduler = scheduler
        self.is_running = asyncio.Event()
        self.interrupt_last_check_times: Dict[str, datetime] = {}
        self.interrupt_cooldown_until: Dict[str, datetime] = {}

    async def run(self):
        """
        服务的主循环，负责持续监控中断条件。

        此方法启动后会一直运行，直到其 `asyncio.Task` 被取消。
        在循环中，它会定期：
        1. 获取当前所有需要监控的中断规则。
        2. 遍历这些规则，检查是否满足检查条件（如检查间隔）。
        3. 如果满足，则在对应的方案上下文中评估中断条件。
        4. 如果条件为真，则提交中断并进入冷却期。
        """
        logger.info("中断监控服务 (InterruptService/Guardian) 正在启动...")
        self.is_running.set()
        try:
            while True:
                if self.scheduler.is_running.is_set():
                    active_interrupts = await self._get_active_interrupts()
                    now = datetime.now()

                    for rule_name in active_interrupts:
                        should_check, rule = await self._should_check_interrupt(rule_name, now)
                        if not should_check:
                            continue

                        logger.trace(f"守护者: 正在检查中断条件 '{rule_name}'...")

                        async with plan_context(rule['plan_name']):
                            try:
                                orchestrator = self.scheduler.plans.get(rule['plan_name'])
                                if orchestrator and await orchestrator.perform_condition_check(
                                        rule.get('condition', {})):
                                    logger.warning(f"检测到中断条件: '{rule_name}'! 已提交给指挥官处理。")
                                    await self._submit_interrupt(rule, now)
                                    break  # 一次只处理一个中断
                            except Exception as e:
                                logger.error(f"守护者在检查中断 '{rule_name}' 时出错: {e}", exc_info=True)

                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("中断监控服务 (InterruptService/Guardian) 已停止。")
        finally:
            self.is_running.clear()

    async def _get_active_interrupts(self) -> Set[str]:
        """
        异步地确定当前需要监控哪些中断规则。

        它通过组合以下两部分来构建活动的规则集：
        1. 用户在全局级别启用的中断。
        2. 当前正在运行的任务在其定义中声明要激活的中断。

        Returns:
            Set[str]: 一个包含所有活动中断规则名称的集合。
        """
        async def async_get() -> Set[str]:
            async with self.scheduler.get_async_lock():
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

        try:
            return await async_get()
        except RuntimeError as e:
            if "event loop is already running" in str(e).lower():
                logger.warning("检测到嵌套事件循环，回退到同步实现。")
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
                    return {rule_name for rule_name in active_set if rule_name in interrupt_definitions}
            else:
                logger.error(f"在 _get_active_interrupts 中发生运行时错误: {e}")
                raise e
        except Exception as e:
            logger.error(f"在 _get_active_interrupts 中发生意外错误: {e}", exc_info=True)
            return set()

    async def _should_check_interrupt(self, rule_name: str, now: datetime) -> tuple[bool, Optional[Dict]]:
        """
        异步地判断一个中断规则是否应该在此时被检查。

        一个规则应该被检查，必须同时满足以下条件：
        1. 规则定义存在。
        2. 当前时间已超过该规则的冷却期（cooldown）。
        3. 距离上次检查的时间已超过规则定义的检查间隔（check_interval）。

        Args:
            rule_name (str): 要检查的规则的名称。
            now (datetime): 当前时间，用于计算。

        Returns:
            tuple[bool, Optional[Dict]]: 第一个元素指示是否应检查，
            第二个元素是该规则的定义字典（如果应检查）。
        """
        async def async_should_check() -> tuple[bool, Optional[Dict]]:
            async with self.scheduler.get_async_lock():
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

        try:
            return await async_should_check()
        except RuntimeError as e:
            if "event loop is already running" in str(e).lower():
                logger.warning("检测到嵌套事件循环，回退到同步实现。")
                with self.scheduler.fallback_lock:
                    rule = self.scheduler.interrupt_definitions.get(rule_name)
                    if not rule: return False, None
                    cooldown_expired = now >= self.interrupt_cooldown_until.get(rule_name, datetime.min)
                    if not cooldown_expired: return False, None
                    last_check = self.interrupt_last_check_times.get(rule_name, datetime.min)
                    interval_passed = (now - last_check).total_seconds() >= rule.get('check_interval', 5)
                    if interval_passed: self.interrupt_last_check_times[rule_name] = now
                    return interval_passed, rule
            else:
                logger.error(f"在 _should_check_interrupt 中发生运行时错误: {e}")
                raise e
        except Exception as e:
            logger.error(f"在 _should_check_interrupt 中发生意外错误: {e}", exc_info=True)
            return False, None

    async def _submit_interrupt(self, rule: Dict, now: datetime):
        """
        将一个已触发的中断提交到调度器的中断队列，并设置其冷却时间。

        Args:
            rule (Dict): 已触发的中断规则的定义字典。
            now (datetime): 当前时间，用于计算冷却截止时间。
        """
        async with self.scheduler.get_async_lock():
            if self.scheduler.interrupt_queue:
                await self.scheduler.interrupt_queue.put(rule)
                cooldown_seconds = rule.get('cooldown', 60)
                self.interrupt_cooldown_until[rule['name']] = now + timedelta(seconds=cooldown_seconds)
            else:
                logger.error("无法提交中断，因为中断队列尚未初始化。")
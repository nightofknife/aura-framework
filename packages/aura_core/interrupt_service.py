# -*- coding: utf-8 -*-
"""Aura 框架的中断监控服务。

此模块定义了 `InterruptService`，它作为一个独立的后台异步任务（守护者）运行。
它的核心职责是定期地、智能地检查所有当前被激活的中断规则。当中断条件满足时，
它会将该中断事件提交给调度器（Scheduler）进行处理。
"""
import asyncio
import threading
from datetime import datetime, timedelta
from typing import Dict, Set, Optional

from packages.aura_core.logger import logger
from plans.aura_base.services.config_service import current_plan_name
from .asynccontext import plan_context

class InterruptService:
    """异步中断服务（守护者）。

    作为一个独立的后台异步任务运行，定期检查所有被激活的中断规则。
    它管理着中断的检查频率（`check_interval`）和触发后的冷却时间（`cooldown`）。
    """

    def __init__(self, scheduler):
        """初始化中断服务。

        Args:
            scheduler: 调度器主实例的引用。
        """
        self.scheduler = scheduler
        self.is_running = asyncio.Event()
        self.interrupt_last_check_times: Dict[str, datetime] = {}
        self.interrupt_cooldown_until: Dict[str, datetime] = {}

    async def run(self):
        """服务的主循环，负责持续监控中断条件。

        此方法会无限循环，直到被取消。在每个循环中，它会：
        1. 获取当前所有应被激活的中断规则列表。
        2. 遍历每个规则，检查是否到了应该检查它的时间点（考虑检查间隔和冷却期）。
        3. 如果需要检查，则在对应 Plan 的上下文中评估其中断条件。
        4. 如果条件满足，则提交中断给调度器并进入冷却期。
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
                                    break
                            except Exception as e:
                                logger.error(f"守护者在检查中断 '{rule_name}' 时出错: {e}", exc_info=True)

                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("中断监控服务 (InterruptService/Guardian) 已停止。")
        finally:
            self.is_running.clear()

    async def _get_active_interrupts(self) -> Set[str]:
        """(私有) 异步地确定当前需要监控哪些中断规则。

        一个中断规则被认为是“活跃的”如果：
        - 它是一个被用户手动启用的全局中断。
        - 或者，当前有一个正在运行的任务在其定义中声明要激活此中断。

        Returns:
            一个包含所有活跃中断规则名称的集合。
        """
        async def async_get():
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
                logger.warning("嵌套事件循环检测到，fallback 到同步实现。")
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
            return set()

    async def _should_check_interrupt(self, rule_name: str, now: datetime) -> tuple[bool, Optional[Dict]]:
        """(私有) 异步地判断一个中断规则是否应该在此时被检查。

        判断依据：
        1. 规则必须存在。
        2. 规则必须不在冷却期内。
        3. 距离上次检查的时间必须超过规则定义的 `check_interval`。

        Args:
            rule_name: 要检查的规则名称。
            now: 当前时间。

        Returns:
            一个元组 (should_check, rule_definition)。如果 should_check 为 True，
            则 rule_definition 为该规则的定义字典。
        """
        async def async_should_check():
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
                logger.warning("嵌套事件循环检测到，fallback 到同步实现。")
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
            return False, None

    async def _submit_interrupt(self, rule: Dict, now: datetime):
        """(私有) 将触发的中断异步放入 Scheduler 的队列并设置冷却时间。"""
        async with self.scheduler.get_async_lock():
            if self.scheduler.interrupt_queue:
                await self.scheduler.interrupt_queue.put(rule)
                cooldown_seconds = rule.get('cooldown', 60)
                self.interrupt_cooldown_until[rule['name']] = now + timedelta(seconds=cooldown_seconds)
            else:
                logger.error("无法提交中断，因为中断队列尚未初始化。")
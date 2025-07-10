# packages/aura_core/execution_manager.py (全新文件)

import threading
from datetime import datetime
from typing import Dict, Any, Optional

from packages.aura_core.api import hook_manager
from packages.aura_shared_utils.utils.logger import logger


class ExecutionManager:
    """
    执行管理器 (施工队长)。
    负责宏观层面的任务执行，包括：
    - 启动和管理任务线程。
    - 维护全局设备锁 (is_device_busy)。
    - 更新和跟踪任务的全局运行状态 (run_statuses)。
    - 与 Scheduler 协作处理中断的暂停/恢复/重启。
    """

    def __init__(self, scheduler):
        # 需要一个对 Scheduler 的引用来访问状态和方法
        self.scheduler = scheduler
        self.lock = scheduler.lock  # 复用 Scheduler 的锁，保证全局状态一致性

    def execute_task(self, item_to_run: Dict[str, Any], is_handler: bool = False, handler_rule: Dict = None):
        """
        执行一个任务项的主入口。
        这个方法会创建一个新线程来运行任务，避免阻塞主调度循环。
        """
        task_id = item_to_run.get('id', 'ad-hoc')
        thread_name = f"HandlerThread-{task_id}" if is_handler else f"TaskThread-{task_id}"

        task_thread = threading.Thread(
            target=self._run_task_in_thread,
            name=thread_name,
            args=(item_to_run, is_handler, handler_rule)
        )
        task_thread.start()

    def _run_task_in_thread(self, item_to_run: Dict, is_handler: bool, handler_rule: Optional[Dict]):
        """
        这个方法在独立的线程中运行，是实际的任务执行逻辑。
        它完全接管了之前在 Scheduler 中的同名方法。
        """
        plan_name = item_to_run.get('plan_name')
        task_id_in_plan = item_to_run.get('task') or item_to_run.get('task_name')
        item_id = item_to_run.get('id')
        now = datetime.now()

        if not plan_name or not task_id_in_plan:
            logger.error(f"任务项缺少 'plan_name' 或 ('task'/'task_name') 键: {item_to_run}")
            return

        full_task_id = f"{plan_name}/{task_id_in_plan}"
        task_started = False
        task_context = {"item": item_to_run, "is_handler": is_handler, "handler_rule": handler_rule, "start_time": now}

        try:
            # 1. 获取设备锁并更新状态
            with self.lock:
                if self.scheduler.is_device_busy and not is_handler:
                    logger.warning(f"任务 '{full_task_id}' 启动时发现设备已忙，放弃执行。")
                    if item_id:
                        self.scheduler.run_statuses[item_id]['status'] = 'idle'
                    return

                self.scheduler.is_device_busy = True
                task_started = True

                if not is_handler:
                    self.scheduler.current_running_thread = threading.current_thread()
                    self.scheduler.current_running_task = item_to_run
                    if item_id:
                        self.scheduler.run_statuses.setdefault(item_id, {}).update(
                            {'status': 'running', 'started_at': now}
                        )

            # 2. 实际执行任务 (委托给 Orchestrator)
            if task_started:
                hook_manager.trigger('before_task_run', task_context=task_context)

                orchestrator = self.scheduler.plans.get(plan_name)
                if not orchestrator:
                    raise RuntimeError(f"在执行任务时找不到方案包 '{plan_name}' 的 Orchestrator。")

                result = orchestrator.execute_task(task_id_in_plan)

                task_context['end_time'] = datetime.now()
                task_context['result'] = result
                hook_manager.trigger('after_task_success', task_context=task_context)

                # 3. 成功后更新状态
                if not is_handler and item_id:
                    with self.lock:
                        logger.info(f"任务 '{full_task_id}' (ID: {item_id}) 执行成功。")
                        self.scheduler.run_statuses.setdefault(item_id, {}).update(
                            {'status': 'idle', 'last_run': now, 'result': 'success'}
                        )

        except Exception as e:
            # 4. 异常处理
            task_context['end_time'] = datetime.now()
            task_context['exception'] = e
            hook_manager.trigger('after_task_failure', task_context=task_context)

            log_prefix = "处理器任务" if is_handler else f"任务 '{full_task_id}'"
            logger.error(f"{log_prefix} 执行时发生致命错误: {e}", exc_info=True)

            if not is_handler and item_id:
                with self.lock:
                    self.scheduler.run_statuses.setdefault(item_id, {}).update(
                        {'status': 'idle', 'last_run': now, 'result': 'failure'}
                    )
        finally:
            # 5. 最终清理
            if task_started:
                with self.lock:
                    self.scheduler.is_device_busy = False
                    logger.info(f"'{full_task_id}' 执行完毕，设备资源已释放。")

                    if is_handler:
                        # 委托给 Scheduler 处理中断善后
                        self.scheduler._post_interrupt_handling(handler_rule)
                    else:
                        # 清理当前运行任务的引用
                        if self.scheduler.current_running_thread is threading.current_thread():
                            self.scheduler.current_running_task = None
                            self.scheduler.current_running_thread = None

                hook_manager.trigger('after_task_run', task_context=task_context)

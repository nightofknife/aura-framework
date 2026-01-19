# -*- coding: utf-8 -*-
"""Scheduler生命周期管理器

职责: 管理调度器的启动、停止、资源清理和异步组件初始化
"""

import asyncio
import threading
from typing import TYPE_CHECKING, Optional
from packages.aura_core.observability.logging.core_logger import logger
from packages.aura_core.observability.events import Event

if TYPE_CHECKING:
    from .core import Scheduler


class LifecycleManager:
    """调度器生命周期管理

    管理调度器的完整生命周期，包括启动、停止和资源清理。
    """

    def __init__(self, scheduler: 'Scheduler'):
        """初始化生命周期管理器

        Args:
            scheduler: 父调度器实例
        """
        self.scheduler = scheduler
        self._scheduler_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._main_task: Optional[asyncio.Task] = None
        self._startup_lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._shutdown_done = False

    def start(self):
        """启动调度器及所有后台服务

        线程安全的启动流程：
        1. 检查是否已在运行
        2. 重置shutdown标志
        3. 启动执行管理器
        4. 创建并启动调度器线程
        5. 等待启动完成
        6. 发布启动事件

        实现来自: scheduler.py 行534-590
        """
        with self._startup_lock:
            if self._scheduler_thread and self._scheduler_thread.is_alive():
                logger.warning("调度器已经在运行中")
                return

            # 重置shutdown标志，允许重新启动
            with self._shutdown_lock:
                self._shutdown_done = False

            self.scheduler.startup_complete_event.clear()
            logger.info("用户请求启动调度器及所有后台服务...")
            self.scheduler.execution_manager.startup()

            self._scheduler_thread = threading.Thread(
                target=self._run_in_thread,
                name="SchedulerThread",
                daemon=True
            )
            self._scheduler_thread.start()

            # 等待调度器完全启动
            logger.info("等待调度器事件循环完全启动...")
            startup_success = self.scheduler.startup_complete_event.wait(timeout=10)

            if not startup_success:
                logger.error("调度器启动超时！")
                self.stop()
                return

            # ✅ 删除了有竞态条件的事件循环检查（原 line 80-82）
            # startup_complete_event 已经表示启动成功，直接发布启动事件

            logger.info("调度器已启动，正在发布 scheduler.started 事件...")

            # ✅ 添加事件循环检查，避免空指针错误
            if not self._loop:
                logger.warning("事件循环未设置，跳过发布 scheduler.started 事件")
            else:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self.scheduler.event_bus.publish(Event(
                            name="scheduler.started",
                            payload={"message": "Scheduler has started."}
                        )),
                        self._loop
                    )
                    future.result(timeout=5)
                    logger.info("scheduler.started 事件发布成功")
                except asyncio.TimeoutError:
                    logger.error("发布 scheduler.started 事件超时")
                except Exception as e:
                    logger.error(f"发布 scheduler.started 事件失败: {e}", exc_info=True)

        # 推送UI更新
        if hasattr(self.scheduler, 'ui_bridge'):
            self.scheduler.ui_bridge.push_update('master_status_update', {"is_running": True})

    def stop(self):
        """停止调度器及所有后台服务

        线程安全的停止流程：
        1. 检查是否在运行
        2. 停止后台服务（SchedulingService、InterruptService）
        3. 发布停止事件
        4. 请求停止事件循环
        5. 等待线程结束（带重试）
        6. 清理资源

        实现来自: scheduler.py 行635-680
        """
        with self._startup_lock:
            if not self._scheduler_thread or not self._scheduler_thread.is_alive():
                logger.warning("调度器已经处于停止状态")
                return

            logger.info("用户请求停止调度器...")

            # ✅ 新增：先停止后台服务
            logger.info("正在停止后台服务...")
            if hasattr(self.scheduler, 'scheduling_service'):
                self.scheduler.scheduling_service.stop()
            if hasattr(self.scheduler, 'interrupt_service'):
                self.scheduler.interrupt_service.stop()

            # 给服务一点时间响应停止信号
            import time
            time.sleep(0.5)

            # 发布停止事件
            if self._loop and self._loop.is_running():
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self.scheduler.event_bus.publish(Event(
                            name="scheduler.stopping",
                            payload={"message": "Scheduler is stopping."}
                        )),
                        self._loop
                    )
                    future.result(timeout=5)
                    logger.info("scheduler.stopping 事件发布成功")
                except Exception as e:
                    logger.error(f"发布 scheduler.stopping 事件失败: {e}")

            # 请求停止
            if self._loop:  # ✅ 添加检查：确保事件循环存在
                if hasattr(self.scheduler, 'is_running') and self.scheduler.is_running:
                    self._loop.call_soon_threadsafe(self.scheduler.is_running.clear)
                if self._main_task:
                    self._loop.call_soon_threadsafe(self._main_task.cancel)
            else:
                logger.debug("事件循环不存在，跳过停止信号发送")

            # ✅ 改进：等待线程结束，带重试
            logger.info("等待调度器线程结束...")
            self._scheduler_thread.join(timeout=5)

            if self._scheduler_thread.is_alive():
                logger.warning("调度器线程第一次join超时(5秒)，尝试强制取消所有任务")

                # 强制取消所有任务
                if self._loop:
                    try:
                        def cancel_all():
                            tasks = asyncio.all_tasks(self._loop)
                            for task in tasks:
                                if not task.done():
                                    task.cancel()

                        self._loop.call_soon_threadsafe(cancel_all)
                    except Exception as e:
                        logger.error(f"强制取消任务失败: {e}")

                # 再次等待
                self._scheduler_thread.join(timeout=5)

                if self._scheduler_thread.is_alive():
                    logger.error("调度器线程在多次尝试后仍未能停止，可能存在死锁")
                    logger.error("建议检查后台服务的停止逻辑")

            self._scheduler_thread = None
            self._loop = None

        # 推送UI更新
        if hasattr(self.scheduler, 'ui_bridge'):
            self.scheduler.ui_bridge.push_update('master_status_update', {"is_running": False})

        logger.info("调度器已停止")

    def _cleanup_resources(self):
        """统一的资源清理方法，防止双重shutdown

        实现来自: scheduler.py 行591-621
        """
        with self._shutdown_lock:
            if self._shutdown_done:
                logger.debug("资源已清理，跳过重复调用")
                return

            try:
                logger.info("正在清理调度器资源...")

                # 1. 清理运行中任务记录
                self.scheduler.running_tasks.clear()
                if hasattr(self.scheduler, '_running_task_meta'):
                    self.scheduler._running_task_meta.clear()

                # 2. 关闭执行管理器
                if hasattr(self.scheduler, 'execution_manager') and self.scheduler.execution_manager:
                    try:
                        self.scheduler.execution_manager.shutdown()
                    except Exception as e:
                        logger.error(f"关闭执行管理器时发生异常: {e}", exc_info=True)

                # 3. 标记为已关闭
                self._shutdown_done = True
                logger.info("调度器资源清理完成")

            except Exception as e:
                logger.error(f"资源清理时发生异常: {e}", exc_info=True)
            finally:
                # 4. 无论成功失败都设置事件
                self.scheduler.startup_complete_event.set()

    def _run_in_thread(self):
        """在独立线程中运行主事件循环

        实现来自: scheduler.py 行622-634
        """
        try:
            asyncio.run(self.scheduler.run())
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("调度器事件循环被取消")
        except Exception as e:
            logger.critical(f"调度器主事件循环崩溃: {e}", exc_info=True)
        finally:
            self._cleanup_resources()

    def initialize_async_components(self):
        """在事件循环内部初始化所有需要事件循环的组件

        实现来自: scheduler.py 行163-177
        """
        from packages.aura_core.scheduler.queues.task_queue import TaskQueue
        from packages.aura_core.config.loader import get_config_value

        logger.debug("Scheduler: 正在事件循环内初始化/重置异步组件...")

        # 初始化事件和锁
        self.scheduler.is_running = asyncio.Event()
        if self.scheduler.async_data_lock is None:
            self.scheduler.async_data_lock = asyncio.Lock()

        # 初始化异步日志队列（无界）
        if not hasattr(self.scheduler, 'api_log_queue') or self.scheduler.api_log_queue is None:
            self.scheduler.api_log_queue = asyncio.Queue(maxsize=0)

        # 初始化任务队列
        self.scheduler.task_queue = TaskQueue(
            maxsize=int(get_config_value("scheduler.queue.main_maxsize", 1000))
        )
        self.scheduler.event_task_queue = TaskQueue(
            maxsize=int(get_config_value("scheduler.queue.event_maxsize", 2000))
        )
        self.scheduler.interrupt_queue = asyncio.Queue(
            maxsize=int(get_config_value("scheduler.queue.interrupt_maxsize", 100))
        )

        logger.debug("异步组件初始化完成")

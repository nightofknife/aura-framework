# -*- coding: utf-8 -*-
"""Scheduler生命周期管理器

职责: 管理调度器的启动、停止、资源清理和异步组件初始化
"""

import asyncio
import inspect
import threading
from typing import TYPE_CHECKING, Optional, Dict, Any, Iterable
from packages.aura_core.observability.logging.core_logger import logger
from packages.aura_core.observability.events import Event
from packages.aura_core.api.registries import service_registry

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

        self._schedule_service_preload()

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

                # ✅ 修复内存泄漏：清理所有事件订阅
                try:
                    logger.info("正在清理事件总线订阅...")
                    cleanup_future = asyncio.run_coroutine_threadsafe(
                        self.scheduler.event_bus.clear_subscriptions(keep_persistent=False),
                        self._loop
                    )
                    cleanup_future.result(timeout=5)

                    # 获取清理后的统计信息
                    stats = self.scheduler.event_bus.get_stats()
                    logger.info(
                        f"事件订阅已清理完成。剩余订阅: {stats['total_subscriptions']} "
                        f"(持久: {stats['persistent_subscriptions']}, 临时: {stats['transient_subscriptions']})"
                    )
                except asyncio.TimeoutError:
                    logger.error("清理事件订阅超时")
                except Exception as e:
                    logger.error(f"清理事件订阅失败: {e}", exc_info=True)

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

    def _schedule_service_preload(self) -> None:
        if not self._loop or not self._loop.is_running():
            logger.warning("Service preload skipped: event loop not ready.")
            return

        config_service = None
        try:
            config_service = service_registry.get_service_instance('config')
        except Exception:
            config_service = None

        services_cfg = config_service.get('services', {}) if config_service else {}
        preload_cfg = services_cfg.get('preload', {}) if isinstance(services_cfg, dict) else {}
        enabled = bool(preload_cfg.get('enabled', False))
        warmup_default = bool(preload_cfg.get('warmup', False))
        configured_targets = preload_cfg.get('targets', []) or []
        target_list = []
        seen = set()
        if isinstance(configured_targets, list):
            for item in configured_targets:
                if isinstance(item, str) and item not in seen:
                    target_list.append(item)
                    seen.add(item)

        if isinstance(services_cfg, dict):
            for name, svc_cfg in services_cfg.items():
                if name == 'preload' or not isinstance(svc_cfg, dict):
                    continue
                if svc_cfg.get('lazy_load') is False or svc_cfg.get('preload_on_start'):
                    if name not in seen:
                        target_list.append(name)
                        seen.add(name)

        if not target_list:
            return

        async def _runner():
            await self._preload_services(
                targets=target_list,
                enabled=enabled,
                warmup_default=warmup_default,
                config_service=config_service,
            )

        asyncio.run_coroutine_threadsafe(_runner(), self._loop)

    async def _preload_services(
        self,
        *,
        targets: Iterable[str],
        enabled: bool,
        warmup_default: bool,
        config_service: Any,
    ) -> None:
        for name in targets:
            svc_cfg = config_service.get(f"services.{name}", {}) if config_service else {}
            if not isinstance(svc_cfg, dict):
                svc_cfg = {}
            lazy_load = svc_cfg.get('lazy_load', True)
            preload_on_start = svc_cfg.get('preload_on_start', False)
            warmup = bool(svc_cfg.get('warmup', warmup_default))

            should_preload = enabled or preload_on_start or (lazy_load is False)
            if not should_preload:
                continue

            try:
                service = service_registry.get_service_instance(name)
            except Exception as exc:
                logger.warning("Service preload skipped: '%s' not available (%s).", name, exc)
                continue

            await self._preload_service_instance(name, service, warmup=warmup)

    async def _preload_service_instance(self, name: str, service: Any, *, warmup: bool) -> None:
        candidates = (
            ("preload_engine", {"warmup": warmup}),
            ("preload", {"warmup": warmup}),
            ("initialize_engine", {}),
            ("initialize", {}),
            ("self_check", {}),
        )

        for method_name, kwargs in candidates:
            method = getattr(service, method_name, None)
            if not callable(method):
                continue
            try:
                await self._run_preload_method(method, kwargs)
                logger.info("Service '%s' preloaded via %s.", name, method_name)
            except Exception as exc:
                logger.warning("Service '%s' preload via %s failed: %s", name, method_name, exc)
            return

        logger.debug("Service '%s' has no preload method, skipping.", name)

    async def _run_preload_method(self, method, kwargs: Dict[str, Any]) -> Any:
        if inspect.iscoroutinefunction(method):
            try:
                return await method(**kwargs)
            except TypeError:
                return await method()
        return await asyncio.to_thread(self._call_preload_method, method, kwargs)

    def _call_preload_method(self, method, kwargs: Dict[str, Any]) -> Any:
        if not kwargs:
            return method()
        try:
            return method(**kwargs)
        except TypeError:
            return method()

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

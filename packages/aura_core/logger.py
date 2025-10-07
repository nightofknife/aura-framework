"""
提供一个全局的、可配置的日志记录器。

该模块的核心是一个单例的 `Logger` 类，它封装了 Python 的 `logging` 模块，
提供了一个统一的接口来配置和使用日志记录。

主要特性:
- **单例模式**: 整个应用程序共享一个日志记录器实例 (`logger`)。
- **多处理器支持**: 可以同时将日志输出到控制台、文件、以及用于UI更新的队列。
- **动态配置**: 可以通过 `setup` 方法在运行时配置日志级别、文件路径和队列。
- **自定义日志级别**: 增加了 `TRACE` 级别 (5)，用于更详细的调试输出。
- **异步UI支持**: 提供了 `AsyncioQueueHandler`，可以将日志记录安全地发送到
  `asyncio.Queue`，适用于基于 asyncio 的 UI 框架或 API 推送。
- **传统UI支持**: 提供了 `QueueLogHandler`，支持将日志发送到标准的 `queue.Queue`，
  适用于多线程环境（如 Tkinter）。
"""
import logging
import os
import queue
import sys
import time
import asyncio
from logging.handlers import RotatingFileHandler
from typing import Optional, Any


class QueueLogHandler(logging.Handler):
    """
    一个自定义的日志处理器，它将日志记录发送到一个标准的 `queue.Queue` 中。

    这个处理器是线程安全的，主要用于将日志从工作线程发送到主UI线程，
    以便在图形用户界面中显示日志，而不会直接操作UI组件导致线程安全问题。
    """

    def __init__(self, log_queue: queue.Queue):
        """
        初始化处理器。

        Args:
            log_queue (queue.Queue): 用于接收日志条目的线程安全队列。
        """
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord):
        """
        当日志被记录时，由 logging 框架调用此方法。

        它会格式化日志记录，并将最终的字符串放入队列中。

        Args:
            record (logging.LogRecord): 要处理的日志记录对象。
        """
        log_entry = self.format(record)
        self.log_queue.put(log_entry)


# --- 自定义 TRACE 日志级别 ---
TRACE_LEVEL_NUM = 5
logging.addLevelName(TRACE_LEVEL_NUM, "TRACE")


def trace(self: logging.Logger, message: str, *args: Any, **kwargs: Any):
    """
    为 Logger 类添加一个 `trace` 方法。

    这允许使用 `logger.trace("message")` 来记录超详细的调试信息。
    """
    if self.isEnabledFor(TRACE_LEVEL_NUM):
        self._log(TRACE_LEVEL_NUM, message, args, **kwargs)


logging.Logger.trace = trace  # type: ignore


class AsyncioQueueHandler(logging.Handler):
    """
    一个自定义的日志处理器，它将日志记录放入一个 `asyncio.Queue`。

    这个处理器设计用于异步应用。它通过 `loop.call_soon_threadsafe`
    来保证即使日志记录发生在不同的线程，也能安全地将日志项放入
    asyncio 事件循环的队列中。
    """

    def __init__(self, log_queue: asyncio.Queue):
        """
        初始化处理器。

        Args:
            log_queue (asyncio.Queue): 用于接收日志记录字典的异步队列。
        """
        super().__init__()
        self.log_queue = log_queue
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def emit(self, record: logging.LogRecord):
        """
        当日志被记录时，由 logging 框架调用此方法。

        它会获取正在运行的 asyncio 事件循环，并将一个包含日志详细信息的
        字典放入异步队列。

        Args:
            record (logging.LogRecord): 要处理的日志记录对象。
        """
        if self.loop is None:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                # 如果没有正在运行的事件循环，则无法发送日志
                return

        # 将 LogRecord 的关键信息打包成一个字典，以便消费者可以重建它或直接使用
        log_entry = {
            'name': record.name,
            'msg': record.getMessage(),
            'args': record.args,
            'levelname': record.levelname,
            'levelno': record.levelno,
            'pathname': record.pathname,
            'filename': record.filename,
            'module': record.module,
            'exc_info': record.exc_info,
            'exc_text': record.exc_text,
            'stack_info': record.stack_info,
            'lineno': record.lineno,
            'funcName': record.funcName,
            'created': record.created,
            'msecs': record.msecs,
            'relativeCreated': record.relativeCreated,
            'thread': record.thread,
            'threadName': record.threadName,
            'processName': record.processName,
            'process': record.process,
            'message': record.getMessage(),  # 保留 message 字段以实现向后兼容
        }

        try:
            self.loop.call_soon_threadsafe(self.log_queue.put_nowait, log_entry)
        except Exception:
            # 在队列满或其他罕见情况下，静默失败以避免日志系统本身崩溃
            pass


class Logger:
    """
    一个单例日志记录器类，为整个 Aura 框架提供统一的日志接口。

    通过 `logger` 全局实例来访问。
    """
    _instance: Optional['Logger'] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> 'Logger':
        """
        实现单例模式。如果实例不存在，则创建一个新的。
        """
        if not cls._instance:
            cls._instance = super(Logger, cls).__new__(cls, *args, **kwargs)
            logger_obj = logging.getLogger("AuraFramework")
            logger_obj.setLevel(TRACE_LEVEL_NUM)  # 默认启用所有级别的日志
            logger_obj.propagate = False

            # 设置一个默认的控制台处理器，作为未调用 setup() 时的后备
            if not any(h.name == "console" for h in logger_obj.handlers):
                console_handler = logging.StreamHandler(sys.stdout)
                console_handler.set_name("console")
                console_handler.setLevel(logging.INFO)
                console_formatter = logging.Formatter(
                    '%(asctime)s - %(levelname)-8s - %(message)s',
                    datefmt='%H:%M:%S'
                )
                console_handler.setFormatter(console_formatter)
                logger_obj.addHandler(console_handler)

            cls._instance.logger = logger_obj
        return cls._instance

    def _get_handler(self, name: str) -> Optional[logging.Handler]:
        """按名称查找一个已注册的处理器。"""
        for handler in self.logger.handlers:
            if handler.name == name:
                return handler
        return None

    def setup(self,
              log_dir: Optional[str] = None,
              task_name: Optional[str] = None,
              ui_log_queue: Optional[queue.Queue] = None,
              api_log_queue: Optional[asyncio.Queue] = None,
              console_level: Optional[int] = logging.INFO):
        """
        配置日志记录器。可以多次调用以添加或更改处理器。

        Args:
            log_dir (Optional[str]): 日志文件存放的目录。
            task_name (Optional[str]): 当前任务的名称，用于生成日志文件名。
            ui_log_queue (Optional[queue.Queue]): 用于传统UI（如Tkinter）的日志队列。
            api_log_queue (Optional[asyncio.Queue]): 用于异步UI或API推送的日志队列。
            console_level (Optional[int]): 控制台输出的日志级别。如果设为 `None`，
                则会移除控制台处理器。
        """
        # --- 控制台处理器管理 ---
        console_handler = self._get_handler("console")
        if console_level is None:
            if console_handler:
                self.logger.removeHandler(console_handler)
        elif console_handler:
            console_handler.setLevel(console_level)

        # --- 传统UI队列处理器 ---
        if ui_log_queue and not self._get_handler("ui_queue"):
            queue_handler = QueueLogHandler(ui_log_queue)
            queue_handler.set_name("ui_queue")
            queue_handler.setLevel(logging.DEBUG)
            ui_formatter = logging.Formatter('%(asctime)s - %(levelname)-8s - %(message)s', datefmt='%H:%M:%S')
            queue_handler.setFormatter(ui_formatter)
            self.logger.addHandler(queue_handler)

        # --- 异步API队列处理器 ---
        if api_log_queue and not self._get_handler("api_queue"):
            api_queue_handler = AsyncioQueueHandler(api_log_queue)
            api_queue_handler.set_name("api_queue")
            api_queue_handler.setLevel(logging.DEBUG)
            self.logger.addHandler(api_queue_handler)
            self.info("API 日志流队列已连接。")

        # --- 文件处理器 ---
        if log_dir and task_name:
            old_file_handler = self._get_handler("task_file")
            if old_file_handler:
                self.logger.removeHandler(old_file_handler)
                old_file_handler.close()

            os.makedirs(log_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            base_task_name = os.path.basename(task_name)
            safe_base_name = base_task_name.replace('/', '_').replace('\\', '_')
            log_file_path = os.path.join(log_dir, f"{safe_base_name}_{timestamp}.log")

            file_handler = RotatingFileHandler(
                log_file_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8'
            )
            file_handler.set_name("task_file")
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter(
                '%(asctime)s - %(levelname)-8s - %(name)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s'
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
            self.info(f"文件日志已配置。日志文件: {log_file_path}")

    def update_api_queue(self, new_queue: asyncio.Queue):
        """
        在运行时更新或添加 API 日志队列。

        这对于需要动态建立日志流连接的场景（如 WebSocket 连接）非常有用。

        Args:
            new_queue (asyncio.Queue): 新的异步日志队列。
        """
        api_handler = self._get_handler("api_queue")
        if api_handler and isinstance(api_handler, AsyncioQueueHandler):
            api_handler.log_queue = new_queue
            self.info("API 日志队列已更新。")
        elif new_queue:
            api_queue_handler = AsyncioQueueHandler(new_queue)
            api_queue_handler.set_name("api_queue")
            api_queue_handler.setLevel(logging.DEBUG)
            self.logger.addHandler(api_queue_handler)
            self.info("新的 API 日志流队列已连接。")

    def trace(self, message: str, exc_info: bool = False):
        """记录一条 TRACE 级别的日志。"""
        self.logger.trace(message, exc_info=exc_info) # type: ignore

    def debug(self, message: str):
        """记录一条 DEBUG 级别的日志。"""
        self.logger.debug(message)

    def info(self, message: str):
        """记录一条 INFO 级别的日志。"""
        self.logger.info(message)

    def warning(self, message: str):
        """记录一条 WARNING 级别的日志。"""
        self.logger.warning(message)

    def error(self, message: str, exc_info: bool = False):
        """记录一条 ERROR 级别的日志。"""
        self.logger.error(message, exc_info=exc_info)

    def critical(self, message: str, exc_info: bool = False):
        """记录一条 CRITICAL 级别的日志。"""
        self.logger.critical(message, exc_info=exc_info)


logger = Logger()
"""全局日志记录器实例。"""

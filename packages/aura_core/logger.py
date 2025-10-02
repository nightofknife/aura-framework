# packages/aura_shared_utils/utils/logger.py (Modified with console_level support)

import logging
import os
import queue
import sys
import time
import asyncio
from logging.handlers import RotatingFileHandler
from typing import Optional
import logging
import queue


class QueueLogHandler(logging.Handler):
    """
    一个自定义的日志处理器，它将日志记录发送到一个队列中，
    以便UI线程可以安全地从中消费。
    """

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        """
        当日志被记录时，此方法会被调用。
        它格式化日志消息并将其放入队列。
        """
        log_entry = self.format(record)
        self.log_queue.put(log_entry)




# --- Custom TRACE level setup (unchanged) ---
TRACE_LEVEL_NUM = 5
logging.addLevelName(TRACE_LEVEL_NUM, "TRACE")


def trace(self, message, *args, **kwargs):
    if self.isEnabledFor(TRACE_LEVEL_NUM):
        self._log(TRACE_LEVEL_NUM, message, args, **kwargs)


logging.Logger.trace = trace


# --- End of TRACE setup ---


class AsyncioQueueHandler(logging.Handler):
    """
    A custom logging handler that puts records into an asyncio.Queue.
    """

    def __init__(self, log_queue: asyncio.Queue):
        super().__init__()
        self.log_queue = log_queue
        self.loop = None

    def emit(self, record):
        """
        This method is called by the logging framework for each log record.
        """
        if self.loop is None:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                return

        # 【修复】将一个更完整的日志记录字典放入队列。
        # 最关键的是添加了 record.levelno。
        # 我们也添加了其他字段，以便能完美重建 LogRecord。
        log_entry = {
            'name': record.name,
            'msg': record.getMessage(), # 使用 'msg' 键，更符合 makeLogRecord 的期望
            'args': record.args,
            'levelname': record.levelname,
            'levelno': record.levelno, # <<< 这是最关键的修复
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
        }

        try:
            # 注意：原代码的 'message' 键改为了 'msg'，这更标准。
            # 如果消费者需要 'message'，可以保留两者，但 'msg' 对于 makeLogRecord 更好。
            # 为了向后兼容，我们同时保留 'message'
            log_entry['message'] = log_entry['msg']
            self.loop.call_soon_threadsafe(self.log_queue.put_nowait, log_entry)
        except Exception:
            pass


class Logger:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Logger, cls).__new__(cls, *args, **kwargs)
            logger_obj = logging.getLogger("AuraFramework")
            logger_obj.setLevel(TRACE_LEVEL_NUM)
            logger_obj.propagate = False
            # 【说明】保持默认的控制台处理器，作为未调用 setup 时的后备
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
        for handler in self.logger.handlers:
            if handler.name == name:
                return handler
        return None

    def setup(self,
              log_dir: str = None,
              task_name: str = None,
              ui_log_queue: queue.Queue = None,
              api_log_queue: asyncio.Queue = None,
              console_level: Optional[int] = logging.INFO):  # 【改动】新增 console_level 参数

        # --- 【改动】控制台处理器管理 ---
        console_handler = self._get_handler("console")
        if console_level is None:
            # 如果传入 None，则移除控制台处理器
            if console_handler:
                self.logger.removeHandler(console_handler)
        elif console_handler:
            # 如果处理器存在，则更新其级别
            console_handler.setLevel(console_level)
        # 如果处理器不存在且 console_level 不是 None，它会在 __new__ 中被创建，这里无需操作

        # --- Legacy Tkinter UI Queue Handler (unchanged) ---
        if ui_log_queue and not self._get_handler("ui_queue"):
            queue_handler = QueueLogHandler(ui_log_queue)
            queue_handler.set_name("ui_queue")
            queue_handler.setLevel(logging.DEBUG)
            ui_formatter = logging.Formatter('%(asctime)s - %(levelname)-8s - %(message)s', datefmt='%H:%M:%S')
            queue_handler.setFormatter(ui_formatter)
            self.logger.addHandler(queue_handler)

        # --- API WebSocket Log Streaming Handler ---
        if api_log_queue and not self._get_handler("api_queue"):
            api_queue_handler = AsyncioQueueHandler(api_log_queue)
            api_queue_handler.set_name("api_queue")
            api_queue_handler.setLevel(logging.DEBUG)
            self.logger.addHandler(api_queue_handler)
            self.info("API log streaming queue is connected.")

        # --- File Handler (unchanged) ---
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
            self.info(f"File logging is configured. Log file: {log_file_path}")

    def update_api_queue(self, new_queue: asyncio.Queue):
        """【新增】允许在运行时更新 API 日志队列。"""
        api_handler = self._get_handler("api_queue")
        if api_handler and isinstance(api_handler, AsyncioQueueHandler):
            api_handler.log_queue = new_queue
            self.info("API log queue has been updated.")
        elif new_queue:
            # 如果处理器不存在，则创建一个新的
            api_queue_handler = AsyncioQueueHandler(new_queue)
            api_queue_handler.set_name("api_queue")
            api_queue_handler.setLevel(logging.DEBUG)
            self.logger.addHandler(api_queue_handler)
            self.info("New API log streaming queue is connected.")

    # --- Logging methods (unchanged) ---
    def trace(self, message, exc_info=False):
        self.logger.trace(message, exc_info=exc_info)

    def debug(self, message):
        self.logger.debug(message)

    def info(self, message):
        self.logger.info(message)

    def warning(self, message):
        self.logger.warning(message)

    def error(self, message, exc_info=False):
        self.logger.error(message, exc_info=exc_info)

    def critical(self, message, exc_info=False):
        self.logger.critical(message, exc_info=exc_info)


logger = Logger()

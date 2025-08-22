# packages/aura_shared_utils/utils/logger.py (Modified)

import logging
import os
import queue
import sys
import time
import asyncio
from logging.handlers import RotatingFileHandler

# This is the handler from the old Tkinter UI. It uses a standard thread-safe queue.
from packages.aura_shared_utils.utils.ui_logger import QueueLogHandler

# --- Custom TRACE level setup (unchanged) ---
TRACE_LEVEL_NUM = 5
logging.addLevelName(TRACE_LEVEL_NUM, "TRACE")


def trace(self, message, *args, **kwargs):
    if self.isEnabledFor(TRACE_LEVEL_NUM):
        self._log(TRACE_LEVEL_NUM, message, args, **kwargs)


logging.Logger.trace = trace


# --- End of TRACE setup ---


# --- 【新增】A logging handler to bridge to asyncio ---
class AsyncioQueueHandler(logging.Handler):
    """
    A custom logging handler that puts records into an asyncio.Queue.
    This is the bridge that allows synchronous logging calls from any thread
    to be safely passed to the asynchronous world of the API server.
    """

    def __init__(self, log_queue: asyncio.Queue):
        super().__init__()
        self.log_queue = log_queue
        # We get the event loop once during initialization. This assumes the handler
        # is created in the same thread that will run the asyncio event loop.
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.get_event_loop()

    def emit(self, record):
        """
        This method is called by the logging framework for each log record.
        """
        # Format the record into a string.
        msg = self.format(record)
        # Use `call_soon_threadsafe` to schedule the `put_nowait` call on the
        # event loop. This is the only safe way to interact with an asyncio
        # queue from a different thread.
        self.loop.call_soon_threadsafe(self.log_queue.put_nowait, msg)


class Logger:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Logger, cls).__new__(cls, *args, **kwargs)
            logger_obj = logging.getLogger("AuraFramework")
            logger_obj.setLevel(TRACE_LEVEL_NUM)

            if not logger_obj.handlers:
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

    def _get_handler(self, name: str):
        for handler in self.logger.handlers:
            if handler.name == name:
                return handler
        return None

    def setup(self,
              log_dir: str = None,
              task_name: str = None,
              ui_log_queue: queue.Queue = None,
              api_log_queue: asyncio.Queue = None):  # 【新增】

        # --- Legacy Tkinter UI Queue Handler (unchanged) ---
        if ui_log_queue and not self._get_handler("ui_queue"):
            queue_handler = QueueLogHandler(ui_log_queue)
            queue_handler.set_name("ui_queue")
            queue_handler.setLevel(logging.DEBUG)
            ui_formatter = logging.Formatter('%(asctime)s - %(levelname)-8s - %(message)s', datefmt='%H:%M:%S')
            queue_handler.setFormatter(ui_formatter)
            self.logger.addHandler(queue_handler)

        # --- 【新增】API WebSocket Log Streaming Handler ---
        if api_log_queue and not self._get_handler("api_queue"):
            api_queue_handler = AsyncioQueueHandler(api_log_queue)
            api_queue_handler.set_name("api_queue")
            api_queue_handler.setLevel(logging.DEBUG)  # Stream DEBUG level and up
            api_formatter = logging.Formatter('%(asctime)s - %(levelname)-8s - %(message)s', datefmt='%H:%M:%S')
            api_queue_handler.setFormatter(api_formatter)
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

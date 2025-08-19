# src/utils/logger.py

import logging
import os
import queue
import sys
import time
from logging.handlers import RotatingFileHandler

from packages.aura_shared_utils.utils.ui_logger import QueueLogHandler

# --- 【新增】为标准 logging 库添加自定义的 TRACE 级别 ---
# 1. 定义 TRACE 级别的数值（比 DEBUG=10 更低）
TRACE_LEVEL_NUM = 5
# 2. 注册级别名称和数值
logging.addLevelName(TRACE_LEVEL_NUM, "TRACE")
# 3. 为 Logger 类添加 trace 方法，这样 self.logger.trace() 才能工作
def trace(self, message, *args, **kwargs):
    if self.isEnabledFor(TRACE_LEVEL_NUM):
        # self._log 是 logging.Logger 内部的实际日志记录方法
        self._log(TRACE_LEVEL_NUM, message, args, **kwargs)
# 4. 将新方法绑定到 logging.Logger 类上 (Monkey-patching)
logging.Logger.trace = trace
# --- 新增部分结束 ---


class Logger:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Logger, cls).__new__(cls, *args, **kwargs)
            logger_obj = logging.getLogger("AuraFramework")
            # 【修改】设置最低级别为我们新的 TRACE 级别
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
              ui_log_queue: queue.Queue = None):
        if ui_log_queue and not self._get_handler("ui_queue"):
            queue_handler = QueueLogHandler(ui_log_queue)
            queue_handler.set_name("ui_queue")
            queue_handler.setLevel(logging.DEBUG)
            ui_formatter = logging.Formatter('%(asctime)s - %(levelname)-8s - %(message)s', datefmt='%H:%M:%S')
            queue_handler.setFormatter(ui_formatter)
            self.logger.addHandler(queue_handler)
            self.info("UI日志队列已连接。")

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
            self.info(f"日志系统已配置完成。日志文件位于: {log_file_path}")

    # --- 【新增】添加 trace 方法到你的 Logger 类 ---
    def trace(self, message, exc_info=False):
        """
        记录 TRACE 级别的日志，用于最详细的调试信息。
        """
        self.logger.trace(message, exc_info=exc_info)

    def debug(self, message):
        self.logger.debug(message)

    def info(self, message):
        self.logger.info(message)

    def warning(self, message):
        self.logger.warning(message)

    def error(self, message, exc_info=False):
        self.logger.error(message, exc_info=exc_info)

    def critical(self, message):
        self.logger.critical(message)


# 创建一个全局可用的日志实例
logger = Logger()

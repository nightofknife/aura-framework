# src/utils/logger.py

import logging
import os
import sys
import queue
import time  # 导入 time 模块
from logging.handlers import RotatingFileHandler
from packages.aura_shared_utils.utils.ui_logger import QueueLogHandler


class Logger:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Logger, cls).__new__(cls, *args, **kwargs)
            # 初始化logger
            logger_obj = logging.getLogger("AuraFramework")
            logger_obj.setLevel(logging.DEBUG)

            # 【修改】只在第一次创建时添加控制台处理器
            if not logger_obj.handlers:
                console_handler = logging.StreamHandler(sys.stdout)
                console_handler.set_name("console")  # 给处理器命名以便查找
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
        """辅助方法：根据名称查找一个已存在的处理器。"""
        for handler in self.logger.handlers:
            if handler.name == name:
                return handler
        return None

    def setup(self,
              log_dir: str = None,
              task_name: str = None,
              ui_log_queue: queue.Queue = None):
        """
        【修改后】配置日志记录器，支持叠加配置。
        """
        """
                【修改后】配置日志记录器，支持叠加配置。
                """
        # --- 1. 配置UI队列处理器 (逻辑不变) ---
        if ui_log_queue and not self._get_handler("ui_queue"):
            queue_handler = QueueLogHandler(ui_log_queue)
            queue_handler.set_name("ui_queue")
            queue_handler.setLevel(logging.DEBUG)
            ui_formatter = logging.Formatter('%(asctime)s - %(levelname)-8s - %(message)s', datefmt='%H:%M:%S')
            queue_handler.setFormatter(ui_formatter)
            self.logger.addHandler(queue_handler)
            self.info("UI日志队列已连接。")

        # --- 2. 配置任务文件处理器 (可动态更新) ---
        if log_dir and task_name:
            # a. 移除旧的文件处理器（逻辑不变）
            old_file_handler = self._get_handler("task_file")
            if old_file_handler:
                self.logger.removeHandler(old_file_handler)
                old_file_handler.close()

            # b. 创建并添加新的文件处理器
            os.makedirs(log_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d-%H%M%S")

            # --- 【关键修复】处理包含路径的任务名 ---
            # 1. 从 task_name (可能是 'tasks/battle_loop') 中提取基本名称 ('battle_loop')
            base_task_name = os.path.basename(task_name)
            # 2. (可选但推荐) 对基本名称进行清理，以防万一
            safe_base_name = base_task_name.replace('/', '_').replace('\\', '_')
            # 3. 使用清理后的安全名称构建最终的文件路径
            log_file_path = os.path.join(log_dir, f"{safe_base_name}_{timestamp}.log")
            # --- 修复结束 ---

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

    # debug, info, warning, error, critical 方法保持不变
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

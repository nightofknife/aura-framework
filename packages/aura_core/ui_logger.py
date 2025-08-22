# src/utils/ui_logger.py
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

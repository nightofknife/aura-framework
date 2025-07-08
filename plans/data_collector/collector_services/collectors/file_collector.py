# plans/data_collector/collector_services/collectors/file_collector.py
import os
import time
import threading
from pathlib import Path
from typing import Dict, Any, Callable, Optional
from packages.aura_shared_utils.utils.logger import logger


class FileMonitorTask:
    def __init__(self, file_path: str, callback: Callable, poll_interval: int):
        self.file_path = Path(file_path)
        self.callback = callback
        self.poll_interval = poll_interval
        self.last_modified = None
        self.last_size = None
        self.running = False
        self.thread = None


class FileCollector:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.default_poll_interval = config.get('default_poll_interval', 5)
        self.max_file_size = config.get('max_file_size', 104857600)  # 100MB
        self.active_tasks = {}

    def get_file_info(self, file_path: str) -> Dict[str, Any]:
        """获取文件详细信息"""
        try:
            path = Path(file_path)
            if not path.exists():
                return {
                    'exists': False,
                    'path': str(path.absolute())
                }

            stat = path.stat()
            return {
                'exists': True,
                'path': str(path.absolute()),
                'size': stat.st_size,
                'modified_time': stat.st_mtime,
                'created_time': stat.st_ctime,
                'is_file': path.is_file(),
                'is_directory': path.is_dir(),
                'extension': path.suffix,
                'name': path.name,
                'readable': os.access(path, os.R_OK),
                'writable': os.access(path, os.W_OK)
            }
        except Exception as e:
            logger.error(f"获取文件信息失败: {e}")
            return {
                'exists': False,
                'error': str(e),
                'path': file_path
            }

    def start_monitoring(self, file_path: str, callback: Callable,
                         poll_interval: int = None) -> Optional[FileMonitorTask]:
        """开始监控文件变化"""
        poll_interval = poll_interval or self.default_poll_interval

        try:
            task = FileMonitorTask(file_path, callback, poll_interval)
            task.running = True
            task.thread = threading.Thread(target=self._monitor_loop, args=(task,), daemon=True)
            task.thread.start()

            task_id = id(task)
            self.active_tasks[task_id] = task
            return task

        except Exception as e:
            logger.error(f"启动文件监控失败: {e}")
            return None

    def stop_monitoring(self, task: FileMonitorTask):
        """停止文件监控"""
        if task:
            task.running = False
            task_id = id(task)
            if task_id in self.active_tasks:
                del self.active_tasks[task_id]

    def _monitor_loop(self, task: FileMonitorTask):
        """文件监控循环"""
        logger.info(f"开始监控文件: {task.file_path}")

        while task.running:
            try:
                current_info = self.get_file_info(str(task.file_path))

                if current_info['exists']:
                    current_modified = current_info['modified_time']
                    current_size = current_info['size']

                    # 检查是否有变化
                    if (task.last_modified is None or
                            current_modified != task.last_modified or
                            current_size != task.last_size):

                        change_info = {
                            'file_info': current_info,
                            'change_type': 'created' if task.last_modified is None else 'modified',
                            'previous_size': task.last_size,
                            'current_size': current_size
                        }

                        # 调用回调函数
                        try:
                            task.callback(change_info)
                        except Exception as e:
                            logger.error(f"文件监控回调执行失败: {e}")

                        task.last_modified = current_modified
                        task.last_size = current_size

                time.sleep(task.poll_interval)

            except Exception as e:
                logger.error(f"文件监控出错: {e}")
                time.sleep(task.poll_interval)

        logger.info(f"停止监控文件: {task.file_path}")

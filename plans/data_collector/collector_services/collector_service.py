# plans/data_collector/collector_services/collector_service.py
import threading
from pathlib import Path
from typing import Dict, Any, List

import yaml

from packages.aura_core.api import register_service
from packages.aura_shared_utils.utils.logger import logger
from .collectors.database_collector import DatabaseCollector
from .collectors.file_collector import FileCollector
from .collectors.http_collector import HttpCollector
from .collectors.rss_collector import RssCollector


@register_service(alias="data_collector", public=True)
class DataCollectorService:
    def __init__(self):
        self.config = {}
        self.http_collector = None
        self.file_collector = None
        self.rss_collector = None
        self.database_collector = None
        self._monitoring_tasks = {}  # 存储监控任务
        self._monitoring_threads = {}  # 存储监控线程
        self._load_config_and_init_collectors()

    def _load_config_and_init_collectors(self):
        """加载配置并初始化各个采集器"""
        try:
            plugin_root = Path(__file__).resolve().parents[1]
            config_path = plugin_root / "collector_config.yaml"

            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    self.config = yaml.safe_load(f) or {}
            else:
                logger.warning(f"数据采集插件配置文件未找到: {config_path}")
                self.config = {}

            # 初始化各个采集器
            if self.config.get('http', {}).get('enabled', True):
                self.http_collector = HttpCollector(self.config.get('http', {}))

            if self.config.get('file_monitor', {}).get('enabled', True):
                self.file_collector = FileCollector(self.config.get('file_monitor', {}))

            if self.config.get('rss', {}).get('enabled', True):
                self.rss_collector = RssCollector(self.config.get('rss', {}))

            if self.config.get('database', {}).get('enabled', True):
                self.database_collector = DatabaseCollector(self.config.get('database', {}))

            logger.info("数据采集服务初始化完成")

        except Exception as e:
            logger.error(f"初始化DataCollectorService失败: {e}", exc_info=True)

    # === HTTP采集方法 ===
    def fetch_url(self, url: str, method: str = "GET", headers: Dict = None,
                  data: Any = None, timeout: int = None, **kwargs) -> Dict[str, Any]:
        """获取HTTP数据"""
        if not self.http_collector:
            raise RuntimeError("HTTP采集器未启用")
        return self.http_collector.fetch(url, method, headers, data, timeout, **kwargs)

    def fetch_json(self, url: str, **kwargs) -> Dict[str, Any]:
        """获取JSON API数据"""
        if not self.http_collector:
            raise RuntimeError("HTTP采集器未启用")
        return self.http_collector.fetch_json(url, **kwargs)

    # === 文件监控方法 ===
    def start_file_monitor(self, task_id: str, file_path: str,
                           callback_event: str = None, poll_interval: int = None) -> bool:
        """开始监控文件变化"""
        if not self.file_collector:
            raise RuntimeError("文件采集器未启用")

        if task_id in self._monitoring_tasks:
            logger.warning(f"文件监控任务 '{task_id}' 已存在")
            return False

        def monitor_callback(file_info):
            # 发布事件通知文件变化
            if callback_event:
                try:
                    from packages.aura_core.api import service_registry
                    event_bus = service_registry.get_service_instance('event_bus')
                    from packages.aura_core.event_bus import Event
                    event = Event(
                        name=callback_event,
                        payload=file_info,
                        source="file_monitor"
                    )
                    event_bus.publish(event)
                except Exception as e:
                    logger.error(f"发布文件变化事件失败: {e}")

        task = self.file_collector.start_monitoring(file_path, monitor_callback, poll_interval)
        if task:
            self._monitoring_tasks[task_id] = task
            logger.info(f"文件监控任务 '{task_id}' 已启动")
            return True
        return False

    def stop_file_monitor(self, task_id: str) -> bool:
        """停止文件监控"""
        if task_id not in self._monitoring_tasks:
            logger.warning(f"文件监控任务 '{task_id}' 不存在")
            return False

        task = self._monitoring_tasks.pop(task_id)
        self.file_collector.stop_monitoring(task)
        logger.info(f"文件监控任务 '{task_id}' 已停止")
        return True

    def get_file_info(self, file_path: str) -> Dict[str, Any]:
        """获取文件信息"""
        if not self.file_collector:
            raise RuntimeError("文件采集器未启用")
        return self.file_collector.get_file_info(file_path)

    # === RSS采集方法 ===
    def fetch_rss(self, url: str, max_entries: int = None) -> Dict[str, Any]:
        """获取RSS数据"""
        if not self.rss_collector:
            raise RuntimeError("RSS采集器未启用")
        return self.rss_collector.fetch_feed(url, max_entries)

    def start_rss_monitor(self, task_id: str, url: str,
                          callback_event: str = None, poll_interval: int = None) -> bool:
        """开始监控RSS源"""
        if not self.rss_collector:
            raise RuntimeError("RSS采集器未启用")

        if task_id in self._monitoring_tasks:
            logger.warning(f"RSS监控任务 '{task_id}' 已存在")
            return False

        def rss_callback(feed_data):
            if callback_event:
                try:
                    from packages.aura_core.api import service_registry
                    event_bus = service_registry.get_service_instance('event_bus')
                    from packages.aura_core.event_bus import Event
                    event = Event(
                        name=callback_event,
                        payload=feed_data,
                        source="rss_monitor"
                    )
                    event_bus.publish(event)
                except Exception as e:
                    logger.error(f"发布RSS更新事件失败: {e}")

        # 在新线程中启动RSS监控
        def monitor_thread():
            self.rss_collector.start_monitoring(url, rss_callback, poll_interval)

        thread = threading.Thread(target=monitor_thread, daemon=True)
        thread.start()
        self._monitoring_threads[task_id] = thread
        self._monitoring_tasks[task_id] = {"type": "rss", "url": url}
        logger.info(f"RSS监控任务 '{task_id}' 已启动")
        return True

    # === 数据库操作方法 ===
    def query_database(self, query: str, db_path: str = None, params: tuple = None) -> List[Dict[str, Any]]:
        """查询数据库"""
        if not self.database_collector:
            raise RuntimeError("数据库采集器未启用")
        return self.database_collector.query(query, db_path, params)

    def execute_database(self, query: str, db_path: str = None, params: tuple = None) -> int:
        """执行数据库语句"""
        if not self.database_collector:
            raise RuntimeError("数据库采集器未启用")
        return self.database_collector.execute(query, db_path, params)

    # === 管理方法 ===
    def get_monitoring_status(self) -> Dict[str, Any]:
        """获取所有监控任务状态"""
        return {
            "active_tasks": list(self._monitoring_tasks.keys()),
            "task_details": self._monitoring_tasks.copy()
        }

    def stop_all_monitoring(self):
        """停止所有监控任务"""
        for task_id in list(self._monitoring_tasks.keys()):
            if task_id in self._monitoring_threads:
                # RSS类型的监控任务需要特殊处理
                continue
            else:
                self.stop_file_monitor(task_id)

        # 清理线程
        self._monitoring_threads.clear()
        logger.info("所有监控任务已停止")

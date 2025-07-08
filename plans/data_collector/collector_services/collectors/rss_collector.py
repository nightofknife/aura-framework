# plans/data_collector/collector_services/collectors/rss_collector.py
import time
import threading
from typing import Dict, Any, Callable, Optional, List
from packages.aura_shared_utils.utils.logger import logger

try:
    import feedparser
except ImportError:
    feedparser = None
    logger.warning("feedparser未安装，RSS功能将不可用。请安装: pip install feedparser")


class RssCollector:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.default_poll_interval = config.get('default_poll_interval', 300)  # 5分钟
        self.max_entries = config.get('max_entries', 100)
        self.monitoring_tasks = {}

    def fetch_feed(self, url: str, max_entries: int = None) -> Dict[str, Any]:
        """获取RSS Feed数据"""
        if not feedparser:
            return {
                'success': False,
                'error': 'feedparser模块未安装'
            }

        try:
            feed = feedparser.parse(url)
            max_entries = max_entries or self.max_entries

            result = {
                'success': True,
                'url': url,
                'feed_info': {
                    'title': getattr(feed.feed, 'title', ''),
                    'description': getattr(feed.feed, 'description', ''),
                    'link': getattr(feed.feed, 'link', ''),
                    'updated': getattr(feed.feed, 'updated', ''),
                },
                'entries': []
            }

            for entry in feed.entries[:max_entries]:
                entry_data = {
                    'title': getattr(entry, 'title', ''),
                    'link': getattr(entry, 'link', ''),
                    'description': getattr(entry, 'description', ''),
                    'published': getattr(entry, 'published', ''),
                    'updated': getattr(entry, 'updated', ''),
                    'id': getattr(entry, 'id', ''),
                    'tags': [tag.term for tag in getattr(entry, 'tags', [])]
                }
                result['entries'].append(entry_data)

            return result

        except Exception as e:
            logger.error(f"获取RSS Feed失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'url': url
            }

    def start_monitoring(self, url: str, callback: Callable, poll_interval: int = None):
        """开始监控RSS源（在当前线程中运行）"""
        poll_interval = poll_interval or self.default_poll_interval
        last_entries = set()

        logger.info(f"开始监控RSS源: {url}")

        while True:
            try:
                feed_data = self.fetch_feed(url)

                if feed_data['success']:
                    current_entries = set()
                    new_entries = []

                    for entry in feed_data['entries']:
                        entry_id = entry.get('id') or entry.get('link', '')
                        current_entries.add(entry_id)

                        if entry_id not in last_entries:
                            new_entries.append(entry)

                    if new_entries and last_entries:  # 不在第一次检查时触发
                        callback({
                            'feed_info': feed_data['feed_info'],
                            'new_entries': new_entries,
                            'total_entries': len(feed_data['entries'])
                        })

                    last_entries = current_entries

                time.sleep(poll_interval)

            except Exception as e:
                logger.error(f"RSS监控出错: {e}")
                time.sleep(poll_interval)

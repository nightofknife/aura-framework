# plans/data_collector/collector_services/collectors/http_collector.py
import time
from typing import Dict, Any

import requests

from packages.aura_shared_utils.utils.logger import logger


class HttpCollector:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.timeout = config.get('default_timeout', 30)
        self.retry_times = config.get('default_retry_times', 3)
        self.retry_delay = config.get('default_retry_delay', 5)
        self.default_headers = config.get('default_headers', {})

        # 配置代理
        self.proxies = None
        if config.get('proxy', {}).get('enabled', False):
            proxy_config = config['proxy']
            self.proxies = {
                'http': proxy_config.get('http', ''),
                'https': proxy_config.get('https', '')
            }

    def fetch(self, url: str, method: str = "GET", headers: Dict = None,
              data: Any = None, timeout: int = None, **kwargs) -> Dict[str, Any]:
        """通用HTTP请求方法"""
        headers = {**self.default_headers, **(headers or {})}
        timeout = timeout or self.timeout

        for attempt in range(1, self.retry_times + 1):
            try:
                response = requests.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    data=data,
                    timeout=timeout,
                    proxies=self.proxies,
                    **kwargs
                )

                return {
                    'success': True,
                    'status_code': response.status_code,
                    'headers': dict(response.headers),
                    'content': response.text,
                    'url': response.url,
                    'encoding': response.encoding
                }

            except requests.exceptions.RequestException as e:
                if attempt < self.retry_times:
                    logger.warning(
                        f"HTTP请求失败 (尝试 {attempt}/{self.retry_times}): {e}，{self.retry_delay}秒后重试...")
                    time.sleep(self.retry_delay)
                else:
                    logger.error(f"HTTP请求最终失败: {e}")
                    return {
                        'success': False,
                        'error': str(e),
                        'url': url
                    }

    def fetch_json(self, url: str, **kwargs) -> Dict[str, Any]:
        """获取JSON数据的便捷方法"""
        result = self.fetch(url, **kwargs)
        if result['success']:
            try:
                import json
                result['json'] = json.loads(result['content'])
            except json.JSONDecodeError as e:
                result['success'] = False
                result['error'] = f"JSON解析失败: {e}"
        return result

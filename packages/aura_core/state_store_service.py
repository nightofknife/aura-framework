# packages/aura_core/services/state_store_service.py

import asyncio
import json
import os
from typing import Any, Dict

from packages.aura_core.api import register_service, requires_services
from packages.aura_core.logger import logger
from plans.aura_base.services.config_service import ConfigService


@register_service(alias="state_store", public=True)
@requires_services(config="config")
class StateStoreService:
    """
    管理长期、持久化的上下文状态。
    所有文件I/O操作都是异步且线程安全的。
    """

    def __init__(self, config: ConfigService):
        self._config = config
        self._filepath: str = ""
        self._data: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        """
        异步初始化服务，加载配置文件路径并读取初始状态。
        必须在使用前调用。
        """
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return

            store_config = self._config.get('state_store', {})
            if store_config.get('type') != 'file':
                logger.warning(f"StateStore只支持'file'类型，当前配置为'{store_config.get('type')}'。将禁用。")
                self._filepath = ""
                self._initialized = True
                return

            path = store_config.get('path', './project_state.json')
            self._filepath = os.path.abspath(path)

            await self._load()
            self._initialized = True
            logger.info(f"StateStoreService已初始化，状态文件: {self._filepath}")

    async def _load(self):
        """内部加载方法，必须在锁内调用。"""
        if not self._filepath:
            return
        loop = asyncio.get_running_loop()
        try:
            if os.path.exists(self._filepath):
                with open(self._filepath, 'r', encoding='utf-8') as f:
                    content = await loop.run_in_executor(None, f.read)
                    self._data = json.loads(content)
            else:
                self._data = {}
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"读取状态文件'{self._filepath}'失败: {e}。将使用空状态。")
            self._data = {}

    async def _save(self):
        """内部保存方法，必须在锁内调用。"""
        if not self._filepath:
            return
        loop = asyncio.get_running_loop()
        try:
            os.makedirs(os.path.dirname(self._filepath), exist_ok=True)
            data_to_save = self._data.copy()
            with open(self._filepath, 'w', encoding='utf-8') as f:
                await loop.run_in_executor(None, lambda: json.dump(data_to_save, f, indent=4, ensure_ascii=False))
        except Exception as e:
            logger.error(f"保存状态文件'{self._filepath}'失败: {e}", exc_info=True)

    async def get(self, key: str, default: Any = None) -> Any:
        """从状态存储中获取一个值。"""
        if not self._initialized: await self.initialize()
        return self._data.get(key, default)

    async def set(self, key: str, value: Any):
        """在状态存储中设置一个值，并立即异步保存。"""
        if not self._initialized: await self.initialize()
        async with self._lock:
            self._data[key] = value
            await self._save()

    async def delete(self, key: str):
        """从状态存储中删除一个键，并立即异步保存。"""
        if not self._initialized: await self.initialize()
        async with self._lock:
            if key in self._data:
                del self._data[key]
                await self._save()

    async def get_all_data(self) -> Dict[str, Any]:
        """获取所有状态数据的副本。"""
        if not self._initialized: await self.initialize()
        return self._data.copy()

"""
定义了 `StateStoreService`，一个用于管理持久化状态的核心服务。

该服务提供了一个基于文件的、异步的键值存储。它允许框架的其他部分
和插件持久化数据，使其在不同的任务执行甚至框架重启之间保持不变。
其配置（如文件路径）通过 `ConfigService` 进行管理。
"""
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
    管理一个与文件绑定的、可持久化的上下文状态。

    此类服务通过异步和线程安全的方式与一个 JSON 文件交互，提供
    了对持久化数据的增、删、查、改操作。所有文件 I/O 都在线程池中
    执行，以避免阻塞事件循环。
    """

    def __init__(self, config: ConfigService):
        """
        初始化状态存储服务。

        Args:
            config (ConfigService): 注入的配置服务实例，用于获取状态文件的路径等配置。
        """
        self._config = config
        self._filepath: str = ""
        self._data: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        """
        异步初始化服务。

        此方法会从配置中读取状态文件的路径，然后异步加载文件内容到内存中。
        这是一个幂等操作，且必须在调用任何其他方法之前被成功执行。
        """
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return

            store_config = self._config.get('state_store', {})
            if store_config.get('type') != 'file':
                logger.warning(f"StateStore 只支持 'file' 类型，当前配置为 '{store_config.get('type')}'。服务将被禁用。")
                self._filepath = ""
                self._initialized = True
                return

            path = store_config.get('path', './project_state.json')
            self._filepath = os.path.abspath(path)

            await self._load()
            self._initialized = True
            logger.info(f"StateStoreService 已初始化，状态文件: {self._filepath}")

    async def _load(self):
        """内部加载方法，负责从文件读取数据。必须在锁的保护下调用。"""
        if not self._filepath:
            return
        loop = asyncio.get_running_loop()
        try:
            if os.path.exists(self._filepath):
                with open(self._filepath, 'r', encoding='utf-8') as f:
                    content = await loop.run_in_executor(None, f.read)
                    self._data = json.loads(content) if content else {}
            else:
                self._data = {}
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"读取状态文件 '{self._filepath}' 失败: {e}。将使用空状态。")
            self._data = {}

    async def _save(self):
        """内部保存方法，负责将数据写入文件。必须在锁的保护下调用。"""
        if not self._filepath:
            return
        loop = asyncio.get_running_loop()
        try:
            os.makedirs(os.path.dirname(self._filepath), exist_ok=True)
            data_to_save = self._data.copy()
            with open(self._filepath, 'w', encoding='utf-8') as f:
                await loop.run_in_executor(None, lambda: json.dump(data_to_save, f, indent=4, ensure_ascii=False))
        except Exception as e:
            logger.error(f"保存状态文件 '{self._filepath}' 失败: {e}", exc_info=True)

    async def get(self, key: str, default: Any = None) -> Any:
        """
        从状态存储中异步获取一个值。

        Args:
            key (str): 要获取的键。
            default (Any): 如果键不存在时返回的默认值。

        Returns:
            Any: 查找到的值，或默认值。
        """
        if not self._initialized: await self.initialize()
        return self._data.get(key, default)

    async def set(self, key: str, value: Any):
        """
        在状态存储中设置一个值，并立即异步保存到文件。

        Args:
            key (str): 要设置的键。
            value (Any): 要设置的值。
        """
        if not self._initialized: await self.initialize()
        async with self._lock:
            self._data[key] = value
            await self._save()

    async def delete(self, key: str):
        """
        从状态存储中删除一个键，并立即异步保存到文件。

        Args:
            key (str): 要删除的键。
        """
        if not self._initialized: await self.initialize()
        async with self._lock:
            if key in self._data:
                del self._data[key]
                await self._save()

    async def get_all_data(self) -> Dict[str, Any]:
        """
        异步获取所有状态数据的副本。

        Returns:
            Dict[str, Any]: 包含所有状态数据的字典副本。
        """
        if not self._initialized: await self.initialize()
        return self._data.copy()

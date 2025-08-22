import asyncio
import json
import os
from typing import Any, Dict

from packages.aura_core.logger import logger


class PersistentContext:
    """
    【Async Refactor】负责管理一个与文件绑定的、可持久化的上下文。
    所有文件I/O操作现在都是异步的，以避免阻塞事件循环。
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._data: Dict[str, Any] = {}
        # The initial load can remain synchronous as it happens during setup, not in the event loop.
        self._sync_load()

    def _sync_load(self):
        """同步从JSON文件加载数据到内存中。仅用于初始化。"""
        try:
            if os.path.exists(self.filepath):
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    self._data = json.load(f)
                logger.debug(f"已从 '{os.path.basename(self.filepath)}' 同步加载长期上下文。")
            else:
                self._data = {}
        except Exception as e:
            logger.error(f"同步加载长期上下文文件 '{self.filepath}' 失败: {e}")
            self._data = {}

    async def load(self):
        """异步从JSON文件加载数据到内存中。"""
        loop = asyncio.get_running_loop()
        try:
            self._data = await loop.run_in_executor(None, self._sync_load_internal)
            logger.info(f"已从 '{os.path.basename(self.filepath)}' 异步加载长期上下文。")
        except Exception as e:
            logger.error(f"异步加载长期上下文文件 '{self.filepath}' 失败: {e}")
            self._data = {}

    def _sync_load_internal(self) -> Dict[str, Any]:
        """内部同步加载逻辑，用于线程池。"""
        if os.path.exists(self.filepath):
            with open(self.filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    async def save(self):
        """将内存中的数据异步保存回JSON文件。"""
        loop = asyncio.get_running_loop()
        try:
            # 复制一份数据以确保线程安全
            data_to_save = self._data.copy()
            await loop.run_in_executor(None, self._sync_save_internal, data_to_save)
            logger.info(f"长期上下文已成功异步保存到 '{os.path.basename(self.filepath)}'。")
            return True
        except Exception as e:
            logger.error(f"异步保存长期上下文文件 '{self.filepath}' 失败: {e}")
            return False

    def _sync_save_internal(self, data: Dict[str, Any]):
        """内部同步保存逻辑，用于线程池。"""
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def set(self, key: str, value: Any):
        """在内存中设置一个值。注意：这不会立即保存到文件。"""
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """从内存中获取一个值。"""
        return self._data.get(key, default)

    def get_all_data(self) -> Dict[str, Any]:
        """返回所有内存中的数据。"""
        return self._data.copy()

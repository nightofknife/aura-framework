# packages/aura_core/persistent_context.py (Refactored)
import asyncio
import json
import os
from typing import Any, Dict

from packages.aura_core.logger import logger


class PersistentContext:
    """
    【Async Refactor - Corrected】负责管理一个与文件绑定的、可持久化的上下文。
    所有文件I/O操作都是异步且线程安全的，构造函数是非阻塞的。
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._data: Dict[str, Any] = {}
        # 【新增】为所有I/O操作添加一个异步锁，以防止竞争条件
        self._lock = asyncio.Lock()

    @classmethod
    async def create(cls, filepath: str) -> "PersistentContext":
        """
        【新增】异步工厂方法，用于创建并初始化一个 PersistentContext 实例。
        这是推荐的实例化方式。
        """
        instance = cls(filepath)
        await instance.load()
        return instance

    async def load(self):
        """异步从JSON文件加载数据到内存中，此操作是线程安全的。"""
        async with self._lock:
            loop = asyncio.get_running_loop()
            try:
                # 【修正】直接将加载的数据赋值给 self._data
                self._data = await loop.run_in_executor(None, self._sync_load_internal)
                logger.debug(f"已从 '{os.path.basename(self.filepath)}' 异步加载长期上下文。")
            except Exception as e:
                logger.error(f"异步加载长期上下文文件 '{self.filepath}' 失败: {e}")
                self._data = {}

    def _sync_load_internal(self) -> Dict[str, Any]:
        """【简化】内部同步加载逻辑，用于线程池。现在是唯一的同步加载实现。"""
        try:
            if os.path.exists(self.filepath):
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"读取长期上下文文件 '{self.filepath}' 时出错 (可能是空文件或已损坏): {e}。将视为空白上下文。")
        return {}

    async def save(self):
        """将内存中的数据异步保存回JSON文件，此操作是线程安全的。"""
        async with self._lock:
            loop = asyncio.get_running_loop()
            try:
                # 复制一份数据以确保在等待执行器时，主线程中的数据修改不会影响保存内容
                data_to_save = self._data.copy()
                await loop.run_in_executor(None, self._sync_save_internal, data_to_save)
                logger.info(f"长期上下文已成功异步保存到 '{os.path.basename(self.filepath)}'。")
                return True
            except Exception as e:
                logger.error(f"异步保存长期上下文文件 '{self.filepath}' 失败: {e}")
                return False

    def _sync_save_internal(self, data: Dict[str, Any]):
        """内部同步保存逻辑，用于线程池。"""
        # 【新增】确保目录存在
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def set(self, key: str, value: Any):
        """在内存中设置一个值。注意：这不会立即保存到文件。"""
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """从内存中获取一个值。"""
        return self._data.get(key, default)

    def get_all_data(self) -> Dict[str, Any]:
        """返回所有内存中数据的副本。"""
        return self._data.copy()


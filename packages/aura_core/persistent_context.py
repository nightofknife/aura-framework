# -*- coding: utf-8 -*-
"""提供一个用于管理持久化上下文的类。

此模块的核心是 `PersistentContext` 类，它负责将一个字典形式的上下文
数据持久化到 JSON 文件中。这对于需要在应用程序重启后依然保留的状态
信息（例如，用户设置、设备状态等）非常有用。

该类被设计为异步优先，并确保所有文件 I/O 操作都是线程安全的。
"""
import asyncio
import json
import os
from typing import Any, Dict

from packages.aura_core.logger import logger


class PersistentContext:
    """负责管理一个与文件绑定的、可持久化的上下文。

    此类通过异步方法从 JSON 文件加载数据到内存字典中，并能将内存中的
    数据异步地保存回文件。所有的文件操作都通过一个异步锁 (`asyncio.Lock`)
    来保护，以防止在并发环境中出现竞争条件。

    推荐使用异步工厂方法 `create()` 来实例化此类，以确保实例在返回前
    已经完成了初始的数据加载。

    Attributes:
        filepath (str): 绑定的 JSON 文件的路径。
    """

    def __init__(self, filepath: str):
        """初始化 PersistentContext。

        注意：这是一个非阻塞的构造函数。实际的文件加载应通过调用 `load()`
        或使用 `create()` 工厂方法来完成。

        Args:
            filepath (str): 上下文数据要持久化到的文件路径。
        """
        self.filepath = filepath
        self._data: Dict[str, Any] = {}
        self._lock = asyncio.Lock()

    @classmethod
    async def create(cls, filepath: str) -> "PersistentContext":
        """异步工厂方法，用于创建并初始化一个 PersistentContext 实例。

        这是推荐的实例化方式，因为它确保在返回实例之前，已经尝试从
        文件中异步加载了数据。

        Args:
            filepath (str): 上下文数据文件的路径。

        Returns:
            一个已完成初始加载的 `PersistentContext` 实例。
        """
        instance = cls(filepath)
        await instance.load()
        return instance

    async def load(self):
        """异步、线程安全地从 JSON 文件加载数据到内存中。

        如果文件不存在、为空或格式损坏，它会记录一个警告并初始化为空上下文，
        而不会抛出异常。
        """
        async with self._lock:
            loop = asyncio.get_running_loop()
            try:
                self._data = await loop.run_in_executor(None, self._sync_load_internal)
                logger.debug(f"已从 '{os.path.basename(self.filepath)}' 异步加载长期上下文。")
            except Exception as e:
                logger.error(f"异步加载长期上下文文件 '{self.filepath}' 失败: {e}")
                self._data = {}

    def _sync_load_internal(self) -> Dict[str, Any]:
        """(私有) 供线程池调用的内部同步加载逻辑。"""
        try:
            if os.path.exists(self.filepath):
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"读取长期上下文文件 '{self.filepath}' 时出错 (可能是空文件或已损坏): {e}。将视为空白上下文。")
        return {}

    async def save(self):
        """将内存中的数据异步、线程安全地保存回 JSON 文件。

        Returns:
            bool: 如果保存成功则返回 True，否则返回 False。
        """
        async with self._lock:
            loop = asyncio.get_running_loop()
            try:
                data_to_save = self._data.copy()
                await loop.run_in_executor(None, self._sync_save_internal, data_to_save)
                logger.info(f"长期上下文已成功异步保存到 '{os.path.basename(self.filepath)}'。")
                return True
            except Exception as e:
                logger.error(f"异步保存长期上下文文件 '{self.filepath}' 失败: {e}")
                return False

    def _sync_save_internal(self, data: Dict[str, Any]):
        """(私有) 供线程池调用的内部同步保存逻辑。"""
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def set(self, key: str, value: Any):
        """在内存中设置一个键值对。

        注意：此操作不会立即将数据保存到文件，需要另行调用 `save()` 方法。

        Args:
            key (str): 要设置的键。
            value (Any): 要设置的值。
        """
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """从内存中获取一个键对应的值。

        Args:
            key (str): 要获取的键。
            default (Any, optional): 如果键不存在时返回的默认值。默认为 None。

        Returns:
            Any: 键对应的值，如果不存在则返回 `default`。
        """
        return self._data.get(key, default)

    def get_all_data(self) -> Dict[str, Any]:
        """返回内存中所有数据的浅拷贝副本。

        Returns:
            一个包含所有上下文数据的字典。
        """
        return self._data.copy()


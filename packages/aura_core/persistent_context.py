"""
提供 `PersistentContext` 类，用于管理与 JSON 文件绑定的持久化数据存储。

该模块的核心是 `PersistentContext` 类，它实现了一个完全异步的、
线程安全的键值存储。数据在内存中进行操作，并可以异步地从文件加载或
保存到文件。所有文件 I/O 操作都在线程池中执行，以避免阻塞事件循环。
这对于需要在任务执行之间保持状态的场景非常有用。
"""
import asyncio
import json
import os
from typing import Any, Dict, Type, TypeVar

from packages.aura_core.logger import logger

T = TypeVar('T', bound='PersistentContext')


class PersistentContext:
    """
    负责管理一个与 JSON 文件绑定的、可持久化的上下文。

    此类将数据存储在内存中的一个字典里，并提供了异步方法来从文件系统
    加载数据和向文件系统保存数据。所有的文件 I/O 操作都通过 `asyncio.Lock`
    来保证异步安全，防止并发读写导致的数据损坏。

    推荐使用 `PersistentContext.create()` 工厂方法来实例化，因为它会
    确保在返回实例之前，数据已从文件中成功加载。
    """

    def __init__(self, filepath: str):
        """
        初始化 PersistentContext 实例。

        这是一个非阻塞的构造函数。请注意，它只设置文件路径和锁，
        并不会实际读取文件。请使用 `create()` 类方法或手动调用 `load()`
        来加载数据。

        Args:
            filepath (str): 关联的 JSON 文件的路径。
        """
        self.filepath = filepath
        self._data: Dict[str, Any] = {}
        self._lock = asyncio.Lock()

    @classmethod
    async def create(cls: Type[T], filepath: str) -> T:
        """
        异步工厂方法，用于创建并初始化一个 PersistentContext 实例。

        这是推荐的实例化方式，因为它会返回一个已经加载了文件数据的实例。

        Args:
            filepath (str): 关联的 JSON 文件的路径。

        Returns:
            PersistentContext: 一个新的、已加载数据的实例。
        """
        instance = cls(filepath)
        await instance.load()
        return instance

    async def load(self):
        """
        异步地从 JSON 文件加载数据到内存中。

        此操作是原子和异步安全的。它会覆盖当前内存中的所有数据。
        如果文件不存在或解析失败，内存中的数据将被清空为一个空字典。
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
        """内部同步加载逻辑，供 `load` 方法在线程池中调用。"""
        try:
            if os.path.exists(self.filepath):
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"读取长期上下文文件 '{self.filepath}' 时出错 (可能是空文件或已损坏): {e}。将视为空白上下文。")
        return {}

    async def save(self) -> bool:
        """
        将内存中的数据异步地保存回 JSON 文件。

        此操作是原子和异步安全的。它会覆盖整个文件。

        Returns:
            bool: 如果保存成功则返回 True，否则返回 False。
        """
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
        """内部同步保存逻辑，供 `save` 方法在线程池中调用。"""
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def set(self, key: str, value: Any):
        """
        在内存中设置一个键值对。

        注意：此操作只修改内存中的数据，并不会立即保存到文件。
        需要显式调用 `save()` 方法来持久化更改。

        Args:
            key (str): 要设置的键。
            value (Any): 要设置的值。
        """
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """
        从内存中获取一个键对应的值。

        Args:
            key (str): 要获取的键。
            default (Any): 如果键不存在时返回的默认值。

        Returns:
            Any: 键对应的值，如果不存在则为 `default`。
        """
        return self._data.get(key, default)

    def get_all_data(self) -> Dict[str, Any]:
        """
        返回所有内存中数据的副本。

        返回的是一个浅拷贝，以防止外部代码意外修改内部状态。

        Returns:
            Dict[str, Any]: 包含所有数据的字典副本。
        """
        return self._data.copy()


# packages/aura_core/persistent_context.py
import json
import os
from typing import Any, Dict

from packages.aura_shared_utils.utils.logger import logger


class PersistentContext:
    """
    负责管理一个与文件绑定的、可持久化的上下文。
    数据以JSON格式存储。
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self):
        """从JSON文件加载数据到内存中。如果文件不存在，则初始化为空。"""
        try:
            if os.path.exists(self.filepath):
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    self._data = json.load(f)
                logger.info(f"已从 '{os.path.basename(self.filepath)}' 加载长期上下文。")
            else:
                logger.info("未找到长期上下文文件，将使用空上下文。")
                self._data = {}
        except Exception as e:
            logger.error(f"加载长期上下文文件 '{self.filepath}' 失败: {e}")
            self._data = {}

    def save(self):
        """将内存中的数据保存回JSON文件。"""
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=4, ensure_ascii=False)
            logger.info(f"长期上下文已成功保存到 '{os.path.basename(self.filepath)}'。")
            return True
        except Exception as e:
            logger.error(f"保存长期上下文文件 '{self.filepath}' 失败: {e}")
            return False

    def set(self, key: str, value: Any):
        """在内存中设置一个值。注意：这不会立即保存到文件。"""
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """从内存中获取一个值。"""
        return self._data.get(key, default)

    def get_all_data(self) -> Dict[str, Any]:
        """返回所有内存中的数据。"""
        return self._data

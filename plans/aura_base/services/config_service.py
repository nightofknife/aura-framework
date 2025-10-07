"""
提供了一个分层的、具有上下文隔离能力的配置服务 `ConfigService`。

该模块的核心是 `ConfigService` 类，它负责加载和管理来自不同来源的配置信息，
包括环境变量、全局配置文件和特定于方案（Plan）的配置文件。

一个关键特性是它使用 `contextvars.ContextVar` (`current_plan_name`) 来
动态地感知当前正在执行的是哪个方案。这使得 `get` 方法能够构建一个
正确的配置查找链，从而实现了方案间的配置隔离，避免了配置串扰问题。
"""
import os
from collections import ChainMap
from contextvars import ContextVar
from pathlib import Path
from typing import Dict, Any, Optional

import yaml

from packages.aura_core.api import register_service
from packages.aura_core.logger import logger

current_plan_name: ContextVar[Optional[str]] = ContextVar('current_plan_name', default=None)
"""
一个上下文变量，用于在任务执行期间隐式地传递当前方案的名称。

这使得 `ConfigService` 可以在不知道具体任务的情况下，自动为 `get` 方法
应用正确的方案配置。
"""

@register_service(alias="config", public=True)
class ConfigService:
    """
    一个分层的、具有上下文隔离能力的配置服务。

    它按以下优先级顺序聚合配置：
    1.  环境变量 (及 `.env` 文件)，以 `AURA_` 开头。
    2.  项目根目录下的全局 `config.yaml` 文件。
    3.  当前正在执行的方案（Plan）目录下的 `config.yaml` 文件。

    通过使用 `ContextVar`，它能够根据当前的执行上下文自动切换方案配置，
    从而实现配置的隔离。
    """

    def __init__(self):
        """
        初始化配置服务。

        此方法会设置用于存储不同层级配置的内部字典。
        """
        self._env_config: Dict[str, Any] = {}
        self._global_config: Dict[str, Any] = {}
        self._plan_configs: Dict[str, Dict[str, Any]] = {}
        logger.info("配置服务 v4.0 (上下文隔离) 已初始化。")

    def load_environment_configs(self, base_path: Path):
        """
        加载环境变量和全局配置文件。

        此方法会：
        - 如果安装了 `python-dotenv`，则加载项目根目录下的 `.env` 文件。
        - 读取所有以 `AURA_` 开头的环境变量。
        - 加载项目根目录下的 `config.yaml` 文件。

        Args:
            base_path (Path): 项目的根目录路径。
        """
        try:
            from dotenv import load_dotenv
            dotenv_path = base_path / '.env'
            if dotenv_path.is_file():
                load_dotenv(dotenv_path=dotenv_path, override=True)
                logger.info(f"已从 '{dotenv_path}' 加载环境变量。")
        except ImportError:
            logger.warning("未安装 'python-dotenv' 库，无法加载 .env 文件。请运行 'pip install python-dotenv'。")
        except Exception as e:
            logger.error(f"加载 .env 文件时出错: {e}")

        for key, value in os.environ.items():
            if key.upper().startswith('AURA_'):
                config_key = key.upper().replace('AURA_', '').lower().replace('_', '.')
                self._set_nested_key(self._env_config, config_key, value)

        if self._env_config:
            logger.debug(f"已加载 {len(self._env_config)} 个环境变量配置。")

        global_config_path = base_path / 'config.yaml'
        if global_config_path.is_file():
            try:
                with open(global_config_path, 'r', encoding='utf-8') as f:
                    self._global_config.update(yaml.safe_load(f) or {})
                logger.info(f"已加载全局配置文件: '{global_config_path}'")
            except Exception as e:
                logger.error(f"加载全局配置文件 '{global_config_path}' 失败: {e}")

    def register_plan_config(self, plan_name: str, config_data: dict):
        """
        为指定的方案注册其配置数据。

        这些配置数据会被存储在以方案名称为键的独立命名空间下。

        Args:
            plan_name (str): 方案的名称。
            config_data (dict): 从该方案的 `config.yaml` 文件中解析出的数据。
        """
        if isinstance(config_data, dict):
            self._plan_configs[plan_name] = config_data
            logger.debug(f"已为方案包 '{plan_name}' 注册隔离的配置。")

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        从动态构建的配置链中获取一个配置项的值。

        它会根据 `current_plan_name` 上下文变量来决定是否包含特定方案的配置，
        然后按照“环境 -> 全局 -> 方案”的优先级顺序进行查找。

        Args:
            key_path (str): 要获取的配置项的路径，使用点（.）分隔，例如 `logging.level`。
            default (Any): 如果找不到对应的配置项，则返回此默认值。

        Returns:
            Any: 查找到的配置值，或指定的默认值。
        """
        plan_name = current_plan_name.get()
        maps_to_chain = [self._env_config, self._global_config]
        if plan_name and plan_name in self._plan_configs:
            maps_to_chain.append(self._plan_configs[plan_name])

        config_chain = ChainMap(*maps_to_chain)

        keys = key_path.split('.')
        current_level: Any = config_chain
        try:
            for key in keys:
                if not isinstance(current_level, (dict, ChainMap)):
                    return default
                current_level = current_level[key]
            return current_level
        except KeyError:
            return default

    def _set_nested_key(self, d: dict, key_path: str, value: Any):
        """一个辅助方法，用于将点分隔的键路径设置到嵌套字典中。"""
        keys = key_path.split('.')
        for key in keys[:-1]:
            d = d.setdefault(key, {})
        d[keys[-1]] = value

    def _deep_merge(self, destination: dict, source: dict):
        """一个辅助方法，用于深度合并两个字典。"""
        for key, value in source.items():
            if isinstance(value, dict) and key in destination and isinstance(destination[key], dict):
                self._deep_merge(destination[key], value)
            else:
                destination[key] = value

    def get_state_store_config(self) -> Dict[str, Any]:
        """
        获取长期状态存储（StateStore）的特定配置。

        Returns:
            Dict[str, Any]: 包含 `type` 和 `path` 的状态存储配置字典。
        """
        return self.get('state_store', {'type': 'file', 'path': './project_state.json'})

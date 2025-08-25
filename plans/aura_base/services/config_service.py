# plans/aura_base/services/config_service.py (分层配置 v3.0)

import os
from collections import ChainMap
from pathlib import Path
from typing import Dict, Any

import yaml

from packages.aura_core.api import register_service
from packages.aura_core.logger import logger


@register_service(alias="config", public=True)
class ConfigService:
    """
    【分层配置 v3.0】配置服务。
    - 支持 .env 文件中的环境变量。
    - 支持项目根目录的全局 config.yaml。
    - 支持各插件内的 config.yaml 作为默认值。
    - 使用 ChainMap 实现高效、动态的配置查找。
    - get() 方法支持点状路径 (dot-notation) 访问。
    """

    def __init__(self):
        # 配置层级，优先级从高到低
        self._env_config: Dict[str, Any] = {}  # 1. 来自 .env 和环境变量 (最高)
        self._global_config: Dict[str, Any] = {}  # 2. 来自项目根目录的 config.yaml
        self._plan_configs: Dict[str, Any] = {}  # 3. 来自所有方案包的 config.yaml (合并)

        # ChainMap 作为统一的配置访问入口
        self.config_chain = ChainMap(
            self._env_config,
            self._global_config,
            self._plan_configs
        )
        logger.info("ConfigService 已初始化。")

    def load_environment_configs(self, base_path: Path):
        """
        由 Scheduler 在启动时调用，加载 .env 和全局 config.yaml。
        """
        # 1. 加载 .env 文件
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

        # 将所有以 'AURA_' 开头的环境变量加载到配置中
        for key, value in os.environ.items():
            if key.upper().startswith('AURA_'):
                # 将 AURA_DATABASE_USER 转换为 database.user
                config_key = key.upper().replace('AURA_', '').lower().replace('_', '.')
                self._set_nested_key(self._env_config, config_key, value)

        if self._env_config:
            logger.debug(f"已加载 {len(self._env_config)} 个环境变量配置。")

        # 2. 加载全局 config.yaml
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
        由 Scheduler 调用，注册方案包的配置。
        这里我们将所有方案包的配置合并到一个层级，以简化逻辑。
        如果需要方案包级别的覆盖，可以在全局 config.yaml 中按方案包名称嵌套。
        """
        if isinstance(config_data, dict):
            # 使用深层合并，避免覆盖整个顶级键
            self._deep_merge(self._plan_configs, config_data)
            logger.debug(f"已为方案包 '{plan_name}' 注册默认配置。")

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        从合并后的配置中获取值，支持点状路径(dot-notation)访问。
        查找顺序: 环境变量 -> 全局 config.yaml -> 插件 config.yaml
        """
        keys = key_path.split('.')
        current_level = self.config_chain
        try:
            for key in keys:
                if not isinstance(current_level, (dict, ChainMap)):
                    return default
                current_level = current_level[key]
            return current_level
        except KeyError:
            return default

    def _set_nested_key(self, d: dict, key_path: str, value: Any):
        """辅助函数，用于通过点状路径设置字典中的值"""
        keys = key_path.split('.')
        for key in keys[:-1]:
            d = d.setdefault(key, {})
        d[keys[-1]] = value

    def _deep_merge(self, destination: dict, source: dict):
        """递归地合并字典"""
        for key, value in source.items():
            if isinstance(value, dict) and key in destination and isinstance(destination[key], dict):
                self._deep_merge(destination[key], value)
            else:
                destination[key] = value

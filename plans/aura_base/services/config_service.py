# plans/aura_base/services/config_service.py (v4.0 with Context Isolation)

import os
from collections import ChainMap
from contextvars import ContextVar
from pathlib import Path
from typing import Dict, Any, Optional

import yaml

from packages.aura_core.api import register_service
from packages.aura_core.logger import logger

# 【修复】引入 ContextVar，用于在任务执行期间隐式传递当前方案的名称。
current_plan_name: ContextVar[Optional[str]] = ContextVar('current_plan_name', default=None)


@register_service(alias="config", public=True)
class ConfigService:
    """
    【分层配置 v4.0 - 上下文隔离】
    - 使用 ContextVar 来感知当前的执行方案，实现配置的自动隔离。
    - 每个方案的配置现在存储在独立的命名空间下，解决了配置串扰问题。
    - get() 方法会根据上下文动态构建配置查找链。
    """

    def __init__(self):
        # 配置层级，优先级从高到低
        self._env_config: Dict[str, Any] = {}  # 1. 来自 .env 和环境变量 (最高)
        self._global_config: Dict[str, Any] = {}  # 2. 来自项目根目录的 config.yaml

        # 【修复】将 _plan_configs 改为字典的字典，按方案名隔离存储。
        # 结构: { "plan_name_1": { ...config... }, "plan_name_2": { ...config... } }
        self._plan_configs: Dict[str, Dict[str, Any]] = {}

        # 【修复】不再使用固定的 ChainMap。将在 get() 方法中动态创建。
        logger.info("ConfigService v4.0 (Context Isolation) 已初始化。")

    def load_environment_configs(self, base_path: Path):
        # ... 此方法内容不变 ...
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
        【修复】注册方案包的配置到其独立的命名空间下。
        不再进行合并，而是直接赋值。
        """
        if isinstance(config_data, dict):
            self._plan_configs[plan_name] = config_data
            logger.debug(f"已为方案包 '{plan_name}' 注册隔离的配置。")

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        【修复】从动态构建的配置链中获取值。
        查找顺序: 环境变量 -> 全局 config -> 当前方案的 config
        """
        # 1. 从 contextvar 获取当前正在执行的方案名称
        plan_name = current_plan_name.get()
        # print(f"% {plan_name}")
        # print(f"% {self._env_config} {self._global_config}")
        # 2. 根据 plan_name 动态构建查找链
        maps_to_chain = [self._env_config, self._global_config]
        if plan_name and plan_name in self._plan_configs:
            maps_to_chain.append(self._plan_configs[plan_name])
        # print(f"% {maps_to_chain}")
        config_chain = ChainMap(*maps_to_chain)

        # 3. 在动态链中查找值
        keys = key_path.split('.')
        current_level = config_chain
        try:
            for key in keys:
                if not isinstance(current_level, (dict, ChainMap)):
                    return default
                current_level = current_level[key]
            return current_level
        except KeyError:
            return default

    # ... _set_nested_key 和 _deep_merge 方法保持不变，尽管 _deep_merge 不再被 register_plan_config 使用 ...
    def _set_nested_key(self, d: dict, key_path: str, value: Any):
        keys = key_path.split('.')
        for key in keys[:-1]:
            d = d.setdefault(key, {})
        d[keys[-1]] = value

    def _deep_merge(self, destination: dict, source: dict):
        for key, value in source.items():
            if isinstance(value, dict) and key in destination and isinstance(destination[key], dict):
                self._deep_merge(destination[key], value)
            else:
                destination[key] = value


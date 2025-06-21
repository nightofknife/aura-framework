# packages/aura_base/services/config_service.py (最终架构版 v2.0)

from pathlib import Path
import yaml
from typing import Dict, Any
from collections import ChainMap  # 【【【核心修正 1/4：导入ChainMap】】】

from packages.aura_core.api import register_service
from packages.aura_shared_utils.utils.logger import logger


@register_service(alias="config", public=True)
class ConfigService:
    """
    【最终架构版 v2.0】配置服务。
    - 支持 系统 -> 用户 -> 基础方案 -> 活动方案 的四层配置覆盖。
    - 使用 ChainMap 实现高效、动态的配置查找。
    - get() 方法支持点状路径 (dot-notation) 访问。
    """

    def __init__(self):
        self._system_config: Dict[str, Any] = {}
        self._user_config: Dict[str, Any] = {}
        self._all_plan_configs: Dict[str, Dict[str, Any]] = {}
        self._active_plan_name: str | None = None

        # 【【【核心修正 2/4：使用ChainMap作为统一的配置访问入口】】】
        # 初始状态下，只包含系统和用户配置
        self._load_initial_configs()
        self.active_config = ChainMap(self._user_config, self._system_config)

    def _load_initial_configs(self):
        # 假设项目根目录在 site-packages/packages/.. 上三层
        # 根据你的项目结构，这个路径可能需要微调
        try:
            base_path = Path(__file__).resolve().parents[3]
            system_config_path = base_path / 'config' / 'system.yaml'
            user_config_path = base_path / 'config' / 'user.yaml'

            if system_config_path.exists():
                self._system_config = self._load_yaml(system_config_path)
                logger.info("已加载系统配置 (system.yaml)。")

            if user_config_path.exists():
                self._user_config = self._load_yaml(user_config_path)
                logger.info("已加载用户配置 (user.yaml)。")
        except IndexError:
            logger.warning("无法自动确定项目根目录来加载系统/用户配置。")

    def register_plan_config(self, plan_name: str, config_data: dict):
        """由Scheduler调用，注册所有方案包的配置。"""
        self._all_plan_configs[plan_name] = config_data or {}
        logger.info(f"已为方案包 '{plan_name}' 注册配置。")

    def set_active_plan(self, plan_name: str):
        """
        由Orchestrator调用，设置当前活动的方案包，并重建配置查找链。
        """
        if plan_name == self._active_plan_name:
            return

        self._active_plan_name = plan_name

        active_plan_config = self._all_plan_configs.get(plan_name, {})

        # 定义一个基础配置包的名称，用于回退
        base_plan_name = 'aura_base'
        base_config = self._all_plan_configs.get(base_plan_name, {})

        # 【【【核心修正 3/4：重建ChainMap，实现四层覆盖】】】
        # 查找顺序: 活动方案 -> 基础方案 -> 用户配置 -> 系统配置
        self.active_config.maps = [
            active_plan_config,
            base_config,
            self._user_config,
            self._system_config
        ]

        logger.debug(f"已将活动配置切换为方案包: '{plan_name}'。")

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"加载YAML文件 '{path}' 失败: {e}")
            return {}

    def get(self, key_path: str, default: Any = None) -> Any:
        """从合并后的配置中获取值，支持点状路径(dot-notation)访问。"""
        keys = key_path.split('.')
        current_level = self.active_config
        try:
            for key in keys:
                # 【【【增加的健壮性检查】】】
                if not isinstance(current_level, (dict, ChainMap)):
                    logger.warning(f"尝试在非字典对象上查找键 '{key}'，路径 '{key_path}' 解析失败。")
                    return default
                current_level = current_level[key]
            return current_level
        except KeyError:
            return default

    @property
    def active_plan_config(self) -> dict:
        """
        为了向后兼容，提供一个只读的、合并后的当前配置视图。
        """
        return self.active_config

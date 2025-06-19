# packages/aura_system_services/services/config_service.py

from pathlib import Path
import yaml
from typing import Dict, Any

from packages.aura_shared_utils.utils.logger import logger


class ConfigService:
    """
    【最终架构版】配置服务。
    负责加载和管理系统的多层配置，并能按需切换当前活动的方案包配置。
    """

    def __init__(self):
        self.system: Dict[str, Any] = {}
        self.user: Dict[str, Any] = {}

        # 【核心修改 #1】从单一的 self.plan 变成一个存储所有方案配置的字典
        self._all_plan_configs: Dict[str, Dict[str, Any]] = {}

        # 【核心修改 #2】当前活动的方案包配置
        self.active_plan_config: Dict[str, Any] = {}

        self._load_initial_configs()

    def _load_initial_configs(self):
        """加载系统和用户配置文件（如果存在）。"""
        base_path = Path(__file__).resolve().parents[3]
        system_config_path = base_path / 'config' / 'system.yaml'
        user_config_path = base_path / 'config' / 'user.yaml'

        if system_config_path.exists():
            self.system = self._load_yaml(system_config_path)
            logger.info("已加载系统配置 (system.yaml)。")

        if user_config_path.exists():
            self.user = self._load_yaml(user_config_path)
            logger.info("已加载用户配置 (user.yaml)。")

    def register_plan_config(self, plan_name: str, plan_dir: Path):
        """
        【新方法】加载并“注册”一个方案包的配置，而不是直接覆盖。
        这应该由 Scheduler 在启动时为所有方案包调用。
        """
        plan_config_path = plan_dir / 'config.yaml'
        if plan_config_path.exists():
            config_data = self._load_yaml(plan_config_path)
            self._all_plan_configs[plan_name] = config_data
            logger.info(f"已为方案包 '{plan_name}' 注册配置。")
        else:
            self._all_plan_configs[plan_name] = {}
            logger.debug(f"方案包 '{plan_name}' 没有找到 config.yaml，注册为空配置。")

    def set_active_plan(self, plan_name: str):
        """
        【新方法】设置当前活动的方案包。
        这应该由 Orchestrator 在执行任务前调用。
        """
        if plan_name in self._all_plan_configs:
            self.active_plan_config = self._all_plan_configs[plan_name]
            logger.debug(f"已将活动配置切换为方案包: '{plan_name}'。")
        else:
            logger.warning(f"尝试激活一个未注册的方案包配置: '{plan_name}'。将使用空配置。")
            self.active_plan_config = {}

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        """一个安全的YAML加载器。"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"加载YAML文件 '{path}' 失败: {e}")
            return {}

    def get(self, key: str, default: Any = None) -> Any:
        """
        【核心修改 #3】按优先级获取配置项，现在从 active_plan_config 读取。
        """
        return self.active_plan_config.get(key, self.user.get(key, self.system.get(key, default)))


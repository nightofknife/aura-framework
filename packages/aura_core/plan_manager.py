# packages/aura_core/plan_manager.py (New File)
import asyncio
from pathlib import Path
from typing import Dict, List, Optional

from .logger import logger
from .orchestrator import Orchestrator
from .plugin_manager import PluginManager


class PlanManager:
    """
    【New】顶层管理器，负责初始化和管理所有可执行的方案（Plans）。
    它使用 PluginManager 来加载所有插件，然后为 'plan' 类型的插件创建 Orchestrator 实例。
    这是应用程序（例如 API 服务器）与方案执行核心交互的主要入口点。
    """

    def __init__(self, base_dir: str, pause_event: asyncio.Event):
        self.base_path = Path(base_dir)
        self.pause_event = pause_event
        self.plugin_manager = PluginManager(self.base_path)
        self.plans: Dict[str, Orchestrator] = {}

    def initialize(self):
        """
        执行完整的初始化流程：加载插件，然后准备方案。
        """
        logger.info("======= PlanManager: 开始初始化 =======")
        # 1. 使用 PluginManager 加载所有插件的定义和代码
        self.plugin_manager.load_all_plugins()

        # 2. 遍历已加载的插件，为 'plan' 类型的插件创建 Orchestrator
        logger.info("--- 正在为已加载的方案创建 Orchestrator 实例 ---")
        self.plans.clear()
        for plugin_def in self.plugin_manager.plugin_registry.values():
            if plugin_def.plugin_type == 'plan':
                plan_name = plugin_def.path.name
                if plan_name not in self.plans:
                    logger.info(f"  -> 创建 Orchestrator for plan: '{plan_name}'")
                    self.plans[plan_name] = Orchestrator(
                        base_dir=str(self.base_path),
                        plan_name=plan_name,
                        pause_event=self.pause_event
                    )
        logger.info(f"======= PlanManager: 初始化完成，{len(self.plans)} 个方案已准备就绪 =======")

    def get_plan(self, plan_name: str) -> Optional[Orchestrator]:
        """
        获取指定方案的 Orchestrator 实例。
        """
        return self.plans.get(plan_name)

    def list_plans(self) -> List[str]:
        """
        列出所有已加载并准备就绪的方案名称。
        """
        return list(self.plans.keys())


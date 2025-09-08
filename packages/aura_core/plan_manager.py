# packages/aura_core/plan_manager.py (修正版)

import asyncio
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .logger import logger
from .orchestrator import Orchestrator
from .plugin_manager import PluginManager
from .state_planner import StateMap, StatePlanner


class PlanManager:
    """
    【修改】顶层管理器，负责初始化和管理所有方案（Plans）及其专属资源（如状态规划器）。
    """

    def __init__(self, base_dir: str, pause_event: Optional[asyncio.Event]):
        self.base_path = Path(base_dir)
        self.pause_event = pause_event
        self.plugin_manager = PluginManager(self.base_path)
        self.plans: Dict[str, Orchestrator] = {}

    def initialize(self):
        """
        【修正版】执行完整的初始化流程，确保 Orchestrator 和 StatePlanner 的依赖关系正确建立。
        """
        logger.info("======= PlanManager: 开始初始化 =======")
        self.plugin_manager.load_all_plugins()

        logger.info("--- 正在为已加载的方案创建 Orchestrator 实例 ---")
        self.plans.clear()
        for plugin_def in self.plugin_manager.plugin_registry.values():
            if plugin_def.plugin_type == 'plan':
                plan_name = plugin_def.path.name
                plan_path = plugin_def.path

                # --- 【修复】步骤 1: 先创建 Orchestrator 实例 ---
                # 此时 state_planner 暂时为 None
                logger.info(f"  -> 创建 Orchestrator for plan: '{plan_name}'")
                orchestrator = Orchestrator(
                    base_dir=str(self.base_path),
                    plan_name=plan_name,
                    pause_event=self.pause_event,
                    state_planner=None
                )
                self.plans[plan_name] = orchestrator

                # --- 【修复】步骤 2: 检查并创建 StatePlanner，将 Orchestrator 注入 ---
                state_map_path = plan_path / 'states_map.yaml'
                if state_map_path.is_file():
                    try:
                        logger.info(f"  -> 发现方案 '{plan_name}' 的状态地图，正在初始化规划器...")
                        with open(state_map_path, 'r', encoding='utf-8') as f:
                            data = yaml.safe_load(f)
                        if data and isinstance(data.get('states'), dict) and isinstance(data.get('transitions'), list):
                            state_map = StateMap(data)
                            # 【核心修复】在创建 StatePlanner 时，传入刚刚创建的 orchestrator
                            state_planner_instance = StatePlanner(state_map, orchestrator)

                            # 【修复】步骤 3: 将创建好的 planner 回填到 orchestrator 实例中
                            orchestrator.state_planner = state_planner_instance
                        else:
                            logger.warning(f"  -> 状态地图 '{state_map_path}' 为空或格式不正确，已跳过。")
                    except Exception as e:
                        logger.error(f"  -> 加载方案 '{plan_name}' 的状态地图失败: {e}", exc_info=True)

        logger.info(f"======= PlanManager: 初始化完成，{len(self.plans)} 个方案已准备就绪 =======")

    def get_plan(self, plan_name: str) -> Optional[Orchestrator]:
        return self.plans.get(plan_name)

    def list_plans(self) -> List[str]:
        return list(self.plans.keys())


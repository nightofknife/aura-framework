# -*- coding: utf-8 -*-
"""Aura 框架的顶层方案（Plan）管理器。

此模块定义了 `PlanManager` 类，它是管理所有自动化方案（Plans）的
核心协调者。它负责发现、加载和初始化每个 Plan，并为它们创建专属的
资源，如 `Orchestrator` 和 `StatePlanner`。
"""
import asyncio
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .logger import logger
from .orchestrator import Orchestrator
from .plugin_manager import PluginManager
from .state_planner import StateMap, StatePlanner


class PlanManager:
    """顶层管理器，负责初始化和管理所有方案及其专属资源。

    `PlanManager` 与 `PluginManager` 紧密协作，首先加载所有插件，
    然后为每个类型为 'plan' 的插件创建一个对应的 `Orchestrator` 实例。
    如果 Plan 包含状态地图 (`states_map.yaml`)，它还会为其创建并
    关联一个 `StatePlanner` 实例。

    Attributes:
        plugin_manager (PluginManager): 用于加载所有插件的插件管理器实例。
        plans (Dict[str, Orchestrator]): 一个字典，存储所有已加载的 Plan
            的名称到其对应的 `Orchestrator` 实例的映射。
    """

    def __init__(self, base_dir: str, pause_event: Optional[asyncio.Event]):
        """初始化 PlanManager。

        Args:
            base_dir (str): 项目的基础目录路径。
            pause_event (Optional[asyncio.Event]): 用于暂停/恢复任务执行的
                全局事件，将传递给所有 `Orchestrator`。
        """
        self.base_path = Path(base_dir)
        self.pause_event = pause_event
        self.plugin_manager = PluginManager(self.base_path)
        self.plans: Dict[str, Orchestrator] = {}

    def initialize(self):
        """执行完整的初始化流程。

        此方法会：
        1.  调用 `PluginManager` 加载所有插件。
        2.  遍历所有已加载的 'plan' 类型插件。
        3.  为每个 Plan 创建一个 `Orchestrator` 实例。
        4.  检查 Plan 是否有 `states_map.yaml`，如果有，则为其创建
            `StatePlanner` 并回填到对应的 `Orchestrator` 中。
        """
        logger.info("======= PlanManager: 开始初始化 =======")
        self.plugin_manager.load_all_plugins()

        logger.info("--- 正在为已加载的方案创建 Orchestrator 实例 ---")
        self.plans.clear()
        for plugin_def in self.plugin_manager.plugin_registry.values():
            if plugin_def.plugin_type == 'plan':
                plan_name = plugin_def.path.name
                plan_path = plugin_def.path

                # 步骤 1: 先创建 Orchestrator 实例，此时 state_planner 暂时为 None
                logger.info(f"  -> 创建 Orchestrator for plan: '{plan_name}'")
                orchestrator = Orchestrator(
                    base_dir=str(self.base_path),
                    plan_name=plan_name,
                    pause_event=self.pause_event,
                    state_planner=None
                )
                self.plans[plan_name] = orchestrator

                # 步骤 2: 检查并创建 StatePlanner，将 Orchestrator 注入
                state_map_path = plan_path / 'states_map.yaml'
                if state_map_path.is_file():
                    try:
                        logger.info(f"  -> 发现方案 '{plan_name}' 的状态地图，正在初始化规划器...")
                        with open(state_map_path, 'r', encoding='utf-8') as f:
                            data = yaml.safe_load(f)
                        if data and isinstance(data.get('states'), dict) and isinstance(data.get('transitions'), list):
                            state_map = StateMap(data)
                            # 在创建 StatePlanner 时，传入刚刚创建的 orchestrator
                            state_planner_instance = StatePlanner(state_map, orchestrator)

                            # 步骤 3: 将创建好的 planner 回填到 orchestrator 实例中
                            orchestrator.state_planner = state_planner_instance
                        else:
                            logger.warning(f"  -> 状态地图 '{state_map_path}' 为空或格式不正确，已跳过。")
                    except Exception as e:
                        logger.error(f"  -> 加载方案 '{plan_name}' 的状态地图失败: {e}", exc_info=True)

        logger.info(f"======= PlanManager: 初始化完成，{len(self.plans)} 个方案已准备就绪 =======")

    def get_plan(self, plan_name: str) -> Optional[Orchestrator]:
        """根据名称获取一个已加载的 Plan 的 Orchestrator。

        Args:
            plan_name (str): Plan 的名称。

        Returns:
            对应的 `Orchestrator` 实例，如果不存在则返回 None。
        """
        return self.plans.get(plan_name)

    def list_plans(self) -> List[str]:
        """获取所有已加载的 Plan 的名称列表。

        Returns:
            一个包含所有 Plan 名称的字符串列表。
        """
        return list(self.plans.keys())


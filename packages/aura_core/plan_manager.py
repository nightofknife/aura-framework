"""
定义了 `PlanManager`，这是 Aura 框架中负责管理所有方案（Plan）的顶层组件。

`PlanManager` 的职责是发现、加载和初始化所有可用的自动化方案。它利用
`PluginManager` 来将方案作为一种特殊的插件进行加载。对于每个加载的方案，
它会创建一个专属的 `Orchestrator` 实例来负责该方案内部的任务执行。
此外，如果方案包含状态定义（`states_map.yaml`），它还会负责创建并关联
一个 `StatePlanner` 实例。
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
    """
    顶层管理器，负责初始化和管理所有方案（Plans）及其专属资源（如状态规划器）。

    它作为所有方案的入口点，维护一个从方案名称到其对应 `Orchestrator` 实例的映射。
    """

    def __init__(self, base_dir: str, pause_event: Optional[asyncio.Event]):
        """
        初始化方案管理器。

        Args:
            base_dir (str): 项目的基础目录，用于扫描插件和方案。
            pause_event (Optional[asyncio.Event]): 一个全局事件，用于暂停和恢复所有任务。
                它将被传递给每个创建的 `Orchestrator`。
        """
        self.base_path = Path(base_dir)
        self.pause_event = pause_event
        self.plugin_manager = PluginManager(self.base_path)
        self.plans: Dict[str, Orchestrator] = {}

    def initialize(self):
        """
        执行完整的初始化流程。

        该方法会：
        1.  使用 `PluginManager` 加载所有插件。
        2.  遍历所有类型为 'plan' 的插件。
        3.  为每个方案创建一个 `Orchestrator` 实例。
        4.  检查方案目录中是否存在 `states_map.yaml` 文件。
        5.  如果存在，则创建一个 `StatePlanner` 实例，并将其与对应的
            `Orchestrator` 相互关联，以建立状态规划能力。
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
                logger.info(f"  -> 正在为方案 '{plan_name}' 创建编排器...")
                orchestrator = Orchestrator(
                    base_dir=str(self.base_path),
                    plan_name=plan_name,
                    pause_event=self.pause_event,
                    state_planner=None
                )
                self.plans[plan_name] = orchestrator

                # 步骤 2: 检查并创建 StatePlanner，并将 Orchestrator 注入
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
        """
        根据名称获取一个已初始化的方案的 `Orchestrator` 实例。

        Args:
            plan_name (str): 方案的名称。

        Returns:
            Optional[Orchestrator]: 如果方案存在，则返回其 `Orchestrator` 实例，否则返回 None。
        """
        return self.plans.get(plan_name)

    def list_plans(self) -> List[str]:
        """
        返回所有已加载和初始化的方案的名称列表。

        Returns:
            List[str]: 一个包含所有方案名称的列表。
        """
        return list(self.plans.keys())


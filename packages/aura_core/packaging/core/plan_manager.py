# -*- coding: utf-8 -*-
"""Aura 框架的顶层方案（Plan）管理器。

此模块定义了 `PlanManager` 类，它是管理所有自动化方案（Plans）的
核心协调者。它负责发现、加载和初始化每个 Plan，并为它们创建专属的
资源，如 `Orchestrator` 和 `StatePlanner`。

✅ 修复：移除旧的PluginManager系统，统一使用PackageManager。
"""
import asyncio
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from packages.aura_core.observability.logging.core_logger import logger
from packages.aura_core.scheduler.orchestrator import Orchestrator
from .package_manager import PackageManager  # ✅ 只使用新系统
from packages.aura_core.context.state.planner import StateMap, StatePlanner


class PlanManager:
    """顶层管理器，负责初始化和管理所有方案及其专属资源。

    `PlanManager` 与 `PackageManager` 紧密协作，首先加载所有包，
    然后为每个类型为 'plan' 的包创建一个对应的 `Orchestrator` 实例。
    如果 Plan 包含状态地图 (`states_map.yaml`)，它还会为其创建并
    关联一个 `StatePlanner` 实例。

    Attributes:
        package_manager (PackageManager): 用于加载所有包的包管理器实例。
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

        # ✅ 统一使用新的manifest系统
        logger.info("Using PackageManager for plan management")
        self.package_manager = PackageManager(
            packages_dir=self.base_path / "packages",
            plans_dir=self.base_path / "plans"
        )

        self.plans: Dict[str, Orchestrator] = {}

    def initialize(self):
        """执行完整的初始化流程。

        此方法会：
        1.  调用 `PackageManager` 加载所有包。
        2.  遍历所有已加载的 'plan' 类型包。
        3.  为每个 Plan 创建一个 `Orchestrator` 实例。
        4.  检查 Plan 是否有 `states_map.yaml`，如果有，则为其创建
            `StatePlanner` 并回填到对应的 `Orchestrator` 中。
        """
        logger.info("======= PlanManager: 开始初始化 =======")

        # ✅ 统一使用PackageManager
        self._initialize_with_package_manager()

        logger.info(f"======= PlanManager: 初始化完成，{len(self.plans)} 个方案已准备就绪 =======")

    def _initialize_with_package_manager(self):
        """使用新的 PackageManager 初始化方案。"""
        logger.info("--- 使用 PackageManager 加载包 ---")
        self.package_manager.load_all_packages()

        logger.info("--- 正在为已加载的方案创建 Orchestrator 实例 ---")
        self.plans.clear()

        # Get all loaded packages
        for package_id, manifest in self.package_manager.loaded_packages.items():
            # Only process plan packages (those in plans/ directory)
            # manifest.path is the package directory
            if manifest.path.parent.name != "plans":
                continue

            plan_name = manifest.path.name
            plan_path = manifest.path
            config_data = self._load_plan_config(plan_path)

            # Note: hooks are not yet adapted for PackageManager
            # For now, skip hook execution in new system
            # TODO: Adapt hooks to work with manifest-based packages

            # Create Orchestrator instance
            logger.info(f"  -> 创建 Orchestrator for plan: '{plan_name}'")
            orchestrator = Orchestrator(
                base_dir=str(self.base_path),
                plan_name=plan_name,
                pause_event=self.pause_event,
                state_planner=None,
                loaded_package=manifest  # Pass the manifest
            )
            self.plans[plan_name] = orchestrator

            # Check and create StatePlanner
            state_map_path = plan_path / 'states_map.yaml'
            if state_map_path.is_file():
                try:
                    logger.info(f"  -> 发现方案 '{plan_name}' 的状态地图，正在初始化规划器...")
                    with open(state_map_path, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)
                    if data and isinstance(data.get('states'), dict) and isinstance(data.get('transitions'), list):
                        state_map = StateMap(data)
                        state_planner_instance = StatePlanner(state_map, orchestrator)
                        orchestrator.state_planner = state_planner_instance
                    else:
                        logger.warning(f"  -> 状态地图 '{state_map_path}' 为空或格式不正确，已跳过。")
                except Exception as e:
                    logger.error(f"  -> 加载方案 '{plan_name}' 的状态地图失败: {e}", exc_info=True)


    def _load_plan_config(self, plan_path: Path) -> Dict:
        config_path = plan_path / 'config.yaml'
        if not config_path.is_file():
            return {}
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load plan config '{config_path}': {e}")
            return {}


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

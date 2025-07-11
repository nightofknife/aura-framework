# packages/aura_core/orchestrator.py (已修复Bug)

import threading
from pathlib import Path
from typing import Dict, Any, Optional
from typing import TYPE_CHECKING

from packages.aura_shared_utils.utils.logger import logger
from .action_injector import ActionInjector
from .api import ACTION_REGISTRY
from .context_manager import ContextManager
# 【修复】导入 ActionInjector 和 Context
from .engine import ExecutionEngine
from .event_bus import Event
from .task_loader import TaskLoader

if TYPE_CHECKING:
    pass


class Orchestrator:
    """
    【重构后】方案级的任务编排器。
    职责：
    1. 协调 TaskLoader 和 ContextManager，为任务执行准备好所有资源。
    2. 实例化并启动 ExecutionEngine 来执行任务。
    3. 提供与方案内资源（文件、任务、上下文）交互的稳定接口。
    """

    def __init__(self, base_dir: str, plan_name: str, pause_event: threading.Event):
        self.plan_name = plan_name
        self.current_plan_path = Path(base_dir) / 'plans' / plan_name
        self.pause_event = pause_event
        self.context_manager = ContextManager(self.plan_name, self.current_plan_path)
        self.task_loader = TaskLoader(self.plan_name, self.current_plan_path)

    def execute_task(self, task_name_in_plan: str, triggering_event: Optional[Event] = None) -> Any:
        full_task_id = f"{self.plan_name}/{task_name_in_plan}"
        task_data = self.task_loader.get_task_data(task_name_in_plan)
        if not task_data:
            logger.error(f"找不到任务定义: '{full_task_id}'")
            raise ValueError(f"Task definition not found: {full_task_id}")
        context = self.context_manager.create_context(full_task_id, triggering_event)
        engine = ExecutionEngine(context=context, orchestrator=self, pause_event=self.pause_event)
        return engine.run(task_data, full_task_id)

    def load_task_data(self, full_task_id: str) -> Optional[Dict]:
        plan_name, task_name_in_plan = full_task_id.split('/', 1)
        if plan_name == self.plan_name:
            return self.task_loader.get_task_data(task_name_in_plan)
        else:
            logger.error(f"Orchestrator for '{self.plan_name}' cannot load task for other plan: '{full_task_id}'")
            return None

    # 【【【 Bug修复点 1/2 】】】
    def perform_condition_check(self, condition_data: dict) -> bool:
        """
        【修正版】执行一个只读的条件检查 Action。
        现在使用 ActionInjector，不再依赖 Engine 的私有方法。
        """
        action_name = condition_data.get('action')
        if not action_name:
            return False

        action_def = ACTION_REGISTRY.get(action_name)
        if not action_def or not action_def.read_only:
            logger.warning(f"条件检查 '{action_name}' 不存在或是非只读的，已跳过。")
            return False

        try:
            # 创建一个临时的、轻量级的上下文和引擎实例
            context = self.context_manager.create_context(f"condition_check/{action_name}")
            engine = ExecutionEngine(context, self)
            injector = ActionInjector(context, engine)

            # 使用注入器来执行 action
            result = injector.execute(action_name, condition_data.get('params', {}))
            return bool(result)
        except Exception as e:
            logger.error(f"条件检查 '{action_name}' 失败: {e}", exc_info=True)
            return False

    # 【【【 Bug修复点 2/2 】】】
    def inspect_step(self, task_name_in_plan: str, step_index: int) -> Any:
        """
        【修正版】检查单个步骤的执行结果。
        现在使用 ActionInjector，不再依赖 Engine 的私有方法。
        """
        task_data = self.task_loader.get_task_data(task_name_in_plan)
        if not task_data:
            raise FileNotFoundError(f"找不到任务 '{task_name_in_plan}'。")

        steps = task_data.get('steps', [])
        if not (0 <= step_index < len(steps)):
            raise IndexError(f"步骤索引 {step_index} 超出范围。")

        step_data = steps[step_index]
        action_name = step_data.get('action')

        # 如果步骤没有action，则无法检查，可以返回步骤本身的信息
        if not action_name:
            return {"status": "no_action", "message": "该步骤没有可执行的action。", "step_data": step_data}

        try:
            # 创建一个特殊的、用于检查的上下文和引擎实例
            context = self.context_manager.create_context(f"inspect/{self.plan_name}/{task_name_in_plan}")
            context.set("__is_inspect_mode__", True)
            engine = ExecutionEngine(context, self)
            injector = ActionInjector(context, engine)

            # 使用注入器来执行该步骤的 action
            logger.info(f"正在检查步骤 '{step_data.get('name', step_index)}' 的 action: '{action_name}'")
            result = injector.execute(action_name, step_data.get('params', {}))
            return result
        except Exception as e:
            logger.error(f"检查步骤时发生严重错误: {e}", exc_info=True)
            raise

    # --- 以下是代理到辅助服务的方法，保持API稳定 ---

    @property
    def task_definitions(self) -> Dict[str, Any]:
        return self.task_loader.get_all_task_definitions()

    def get_persistent_context_data(self) -> dict:
        return self.context_manager.get_persistent_context_data()

    def save_persistent_context_data(self, data: dict):
        self.context_manager.save_persistent_context_data(data)

    def get_file_content(self, relative_path: str) -> str:
        full_path = (self.current_plan_path / relative_path).resolve()
        if self.current_plan_path.resolve() not in full_path.parents:
            raise PermissionError(f"禁止访问方案包外部的文件: {relative_path}")
        if not full_path.is_file():
            raise FileNotFoundError(f"在方案 '{self.plan_name}' 中找不到文件: {relative_path}")
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"读取文件 '{full_path}' 失败: {e}")
            raise

    def get_file_content_bytes(self, relative_path: str) -> bytes:
        full_path = (self.current_plan_path / relative_path).resolve()
        if self.current_plan_path.resolve() not in full_path.parents:
            raise PermissionError(f"禁止访问方案包外部的文件: {relative_path}")
        if not full_path.is_file():
            raise FileNotFoundError(f"在方案 '{self.plan_name}' 中找不到文件: {relative_path}")
        try:
            with open(full_path, 'rb') as f:
                return f.read()
        except Exception as e:
            logger.error(f"读取二进制文件 '{full_path}' 失败: {e}")
            raise

    def save_file_content(self, relative_path: str, content: str):
        full_path = (self.current_plan_path / relative_path).resolve()
        if self.current_plan_path.resolve() not in full_path.parents:
            raise PermissionError(f"禁止在方案包外部写入文件: {relative_path}")
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"文件已保存: {full_path}")
        except Exception as e:
            logger.error(f"保存文件 '{full_path}' 失败: {e}")
            raise

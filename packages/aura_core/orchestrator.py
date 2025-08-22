import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

from packages.aura_core.logger import logger
from .action_injector import ActionInjector
from .api import ACTION_REGISTRY
from .context_manager import ContextManager
from .engine import ExecutionEngine
from .event_bus import Event
from .task_loader import TaskLoader


class Orchestrator:
    """
    【Async Refactor】方案级的异步任务编排器。
    所有执行方法都已异步化。
    """

    def __init__(self, base_dir: str, plan_name: str, pause_event: asyncio.Event):
        self.plan_name = plan_name
        self.current_plan_path = Path(base_dir) / 'plans' / plan_name
        self.pause_event = pause_event
        self.context_manager = ContextManager(self.plan_name, self.current_plan_path)
        self.task_loader = TaskLoader(self.plan_name, self.current_plan_path)

    async def execute_task(self, task_name_in_plan: str, triggering_event: Optional[Event] = None) -> Any:
        """
        异步执行一个任务，并能处理 go_task 跳转信号。
        """
        current_task_in_plan = task_name_in_plan
        last_result = None

        while current_task_in_plan:
            full_task_id = f"{self.plan_name}/{current_task_in_plan}"
            task_data = self.task_loader.get_task_data(current_task_in_plan)

            if not task_data:
                raise ValueError(f"Task definition not found: {full_task_id}")

            # 【修正】必须 await create_context 调用
            context = await self.context_manager.create_context(full_task_id, triggering_event)
            engine = ExecutionEngine(context=context, orchestrator=self, pause_event=self.pause_event)

            result = await engine.run(task_data, full_task_id)
            last_result = result

            if result.get('status') == 'go_task' and result.get('next_task'):
                next_full_task_id = result['next_task']
                next_plan_name, next_task_in_plan = next_full_task_id.split('/', 1)

                if next_plan_name != self.plan_name:
                    logger.error(f"go_task 不支持跨方案跳转: 从 '{self.plan_name}' 到 '{next_plan_name}'")
                    break

                current_task_in_plan = next_task_in_plan
                triggering_event = None
            else:
                current_task_in_plan = None

        return last_result

    def load_task_data(self, full_task_id: str) -> Optional[Dict]:
        # ... (此方法逻辑不变) ...
        plan_name, task_name_in_plan = full_task_id.split('/', 1)
        if plan_name == self.plan_name:
            return self.task_loader.get_task_data(task_name_in_plan)
        logger.error(f"Orchestrator for '{self.plan_name}' cannot load task for other plan: '{full_task_id}'")
        return None

    async def perform_condition_check(self, condition_data: dict) -> bool:
        """异步执行一个只读的条件检查 Action。"""
        action_name = condition_data.get('action')
        if not action_name:
            return False

        action_def = ACTION_REGISTRY.get(action_name)
        if not action_def or not action_def.read_only:
            logger.warning(f"条件检查 '{action_name}' 不存在或是非只读的，已跳过。")
            return False

        try:
            # 【修正】必须 await create_context 调用
            context = await self.context_manager.create_context(f"condition_check/{action_name}")
            engine = ExecutionEngine(context, self, self.pause_event)
            injector = ActionInjector(context, engine)
            result = await injector.execute(action_name, condition_data.get('params', {}))
            return bool(result)
        except Exception as e:
            logger.error(f"条件检查 '{action_name}' 失败: {e}", exc_info=True)
            return False

    async def inspect_step(self, task_name_in_plan: str, step_index: int) -> Any:
        """异步检查单个步骤的执行结果。"""
        task_data = self.task_loader.get_task_data(task_name_in_plan)
        if not task_data:
            raise FileNotFoundError(f"找不到任务 '{task_name_in_plan}'。")

        steps = task_data.get('steps', [])
        if not (0 <= step_index < len(steps)):
            raise IndexError(f"步骤索引 {step_index} 超出范围。")

        step_data = steps[step_index]
        action_name = step_data.get('action')
        if not action_name:
            return {"status": "no_action", "message": "该步骤没有可执行的action。", "step_data": step_data}

        try:
            # 【修正】必须 await create_context 调用
            context = await self.context_manager.create_context(f"inspect/{self.plan_name}/{task_name_in_plan}")
            context.set("__is_inspect_mode__", True)
            engine = ExecutionEngine(context, self, self.pause_event)
            injector = ActionInjector(context, engine)

            logger.info(f"正在检查步骤 '{step_data.get('name', step_index)}' 的 action: '{action_name}'")
            return await injector.execute(action_name, step_data.get('params', {}))
        except Exception as e:
            logger.error(f"检查步骤时发生严重错误: {e}", exc_info=True)
            raise

    # ... (所有文件代理方法保持不变) ...
    @property
    def task_definitions(self) -> Dict[str, Any]:
        return self.task_loader.get_all_task_definitions()

    def get_persistent_context_data(self) -> dict:
        return self.context_manager.get_persistent_context_data()

    def save_persistent_context_data(self, data: dict):
        self.context_manager.save_persistent_context_data(data)

    def get_file_content(self, relative_path: str) -> str:
        full_path = (self.current_plan_path / relative_path).resolve()
        if self.current_plan_path.resolve() not in full_path.parents: raise PermissionError(
            f"禁止访问方案包外部的文件: {relative_path}")
        if not full_path.is_file(): raise FileNotFoundError(f"在方案 '{self.plan_name}' 中找不到文件: {relative_path}")
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()

    def get_file_content_bytes(self, relative_path: str) -> bytes:
        full_path = (self.current_plan_path / relative_path).resolve()
        if self.current_plan_path.resolve() not in full_path.parents: raise PermissionError(
            f"禁止访问方案包外部的文件: {relative_path}")
        if not full_path.is_file(): raise FileNotFoundError(f"在方案 '{self.plan_name}' 中找不到文件: {relative_path}")
        with open(full_path, 'rb') as f:
            return f.read()

    def save_file_content(self, relative_path: str, content: str):
        full_path = (self.current_plan_path / relative_path).resolve()
        if self.current_plan_path.resolve() not in full_path.parents: raise PermissionError(
            f"禁止在方案包外部写入文件: {relative_path}")
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f: f.write(content)

# packages/aura_core/orchestrator.py (多任务格式支持版)

import threading
from typing import Dict, Any, Optional
from pathlib import Path

from packages.aura_core.engine import ExecutionEngine
from packages.aura_core.context import Context
from packages.aura_core.api import service_registry, ACTION_REGISTRY
from packages.aura_core.persistent_context import PersistentContext
from packages.aura_shared_utils.utils.logger import logger
from packages.aura_core.event_bus import Event
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.aura_core.scheduler import Scheduler


class Orchestrator:
    """
    一个纯粹的、无状态的任务执行工具。
    不再拥有任何常驻服务或线程，仅在被调用时为单个任务执行提供上下文。
    """

    # 【【【核心修改 1/2】】】
    def __init__(self, base_dir: str, plan_name: str, pause_event: threading.Event, scheduler: 'Scheduler'):
        """
        初始化一个特定方案的执行上下文工具。
        :param base_dir: 项目基础路径
        :param plan_name: 当前方案名称
        :param pause_event: 全局暂停事件（由Scheduler管理）
        :param scheduler: 核心调度器实例
        """
        self.base_dir = Path(base_dir)
        self.plan_name = plan_name
        self.plans_dir = self.base_dir / 'plans'
        self.current_plan_path = self.plans_dir / plan_name
        self.pause_event = pause_event
        self.scheduler = scheduler  # 持有调度器实例

    def setup_and_run(self, task_name_in_plan: str, triggering_event: Optional[Event] = None):
        """兼容旧式调用的入口点"""
        return self.execute_task(task_name_in_plan, triggering_event)

    # 【【【核心修改 2/2】】】
    def execute_task(self, task_name_in_plan: str, triggering_event: Optional[Event] = None):
        """
        【修改版】执行单个任务的核心方法。
        :param task_name_in_plan: 任务在方案内的ID (例如 'login' 或 'user/create')
        :param triggering_event: （可选）触发此任务的事件
        """
        full_task_id = f"{self.plan_name}/{task_name_in_plan}"

        # 任务定义现在完全由 Scheduler 提供
        task_data = self.scheduler.all_tasks_definitions.get(full_task_id)

        if not task_data:
            logger.error(f"找不到任务定义: '{full_task_id}'")
            raise ValueError(f"Task definition not found: {full_task_id}")

        context = Context(triggering_event=triggering_event)
        self._initialize_context(context, triggering_event, full_task_id)
        engine = ExecutionEngine(context=context, orchestrator=self, pause_event=self.pause_event)
        return engine.run(task_data, full_task_id)

    def _initialize_context(self, context: Context, triggering_event: Optional[Event], task_id: str):
        persistent_context_path = self.current_plan_path / 'persistent_context.json'
        persistent_context = PersistentContext(str(persistent_context_path))
        context.set('persistent_context', persistent_context)
        for key, value in persistent_context.get_all_data().items():
            context.set(key, value)
        try:
            config_service = service_registry.get_service_instance('config')
            config_service.set_active_plan(self.plan_name)
            context.set('config', config_service.active_plan_config)
        except Exception:
            context.set('config', {})
        context.set('log', logger)
        debug_dir = self.current_plan_path / 'debug_screenshots'
        debug_dir.mkdir(parents=True, exist_ok=True)
        context.set('debug_dir', str(debug_dir))
        context.set('__task_name__', task_id)
        context.set('__plan_name__', self.plan_name)
        if triggering_event:
            context.set('event', triggering_event)

    def load_task_data(self, task_id: str) -> Dict | None:
        """供Engine调用的任务数据获取方法，直接从scheduler获取"""
        return self.scheduler.all_tasks_definitions.get(task_id)

    def get_persistent_context_data(self) -> dict:
        pc = PersistentContext(str(self.current_plan_path / 'persistent_context.json'))
        return pc.get_all_data()

    def save_persistent_context_data(self, data: dict):
        pc = PersistentContext(str(self.current_plan_path / 'persistent_context.json'))
        pc._data.clear()
        for key, value in data.items(): pc.set(key, value)
        pc.save()

    def get_file_content(self, relative_path: str) -> str:
        full_path = (self.current_plan_path / relative_path).resolve()
        if self.current_plan_path.resolve() not in full_path.parents: raise PermissionError(
            f"禁止访问方案包外部的文件: {relative_path}")
        if not full_path.is_file(): raise FileNotFoundError(f"在方案 '{self.plan_name}' 中找不到文件: {relative_path}")
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"读取文件 '{full_path}' 失败: {e}"); raise

    def get_file_content_bytes(self, relative_path: str) -> bytes:
        full_path = (self.current_plan_path / relative_path).resolve()
        if self.current_plan_path.resolve() not in full_path.parents: raise PermissionError(
            f"禁止访问方案包外部的文件: {relative_path}")
        if not full_path.is_file(): raise FileNotFoundError(f"在方案 '{self.plan_name}' 中找不到文件: {relative_path}")
        try:
            with open(full_path, 'rb') as f:
                return f.read()
        except Exception as e:
            logger.error(f"读取二进制文件 '{full_path}' 失败: {e}"); raise

    def save_file_content(self, relative_path: str, content: str):
        full_path = (self.current_plan_path / relative_path).resolve()
        if self.current_plan_path.resolve() not in full_path.parents: raise PermissionError(
            f"禁止在方案包外部写入文件: {relative_path}")
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"文件已保存: {full_path}")
        except Exception as e:
            logger.error(f"保存文件 '{full_path}' 失败: {e}"); raise

    def inspect_step(self, task_name_in_plan: str, step_index: int) -> Any:
        full_task_id = f"{self.plan_name}/{task_name_in_plan}"
        task_data = self.scheduler.all_tasks_definitions.get(full_task_id)
        if not task_data: raise FileNotFoundError(f"找不到任务 '{task_name_in_plan}'。")
        context = Context()
        context.set("__is_inspect_mode__", True)
        engine = ExecutionEngine(context=context, orchestrator=self)
        steps = task_data.get('steps', [])
        if not (0 <= step_index < len(steps)): raise IndexError(f"步骤索引 {step_index} 超出范围。")
        step_data = steps[step_index]
        try:
            rendered_params = engine._render_params(step_data.get('params', {}))
            result = engine.run_step(step_data, rendered_params)
            return result
        except Exception as e:
            logger.error(f"检查步骤时发生严重错误: {e}", exc_info=True); raise

    def perform_condition_check(self, condition_data: dict) -> bool:
        action_name = condition_data.get('action')
        if not action_name: return False
        action_def = ACTION_REGISTRY.get(action_name)
        if not action_def or not action_def.read_only: return False
        try:
            context = Context()
            engine = ExecutionEngine(context=context, orchestrator=self)
            params = engine._render_params(condition_data.get('params', {}))
            result = engine.injector.execute_action(action_name, params)
            return bool(result)
        except Exception as e:
            logger.error(f"条件检查失败: {e}", exc_info=True); return False

    @property
    def task_definitions(self) -> Dict[str, Any]:
        plan_tasks = {}
        prefix = f"{self.plan_name}/"
        for task_id, task_data in self.scheduler.all_tasks_definitions.items():
            if task_id.startswith(prefix):
                relative_name = task_id[len(prefix):]
                plan_tasks[relative_name] = task_data
        return plan_tasks

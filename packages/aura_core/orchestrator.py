# packages/aura_core/orchestrator.py (V4 - 纯工具化)

import threading
from typing import Dict, Any, Optional
from pathlib import Path

from packages.aura_core.engine import ExecutionEngine
from packages.aura_core.context import Context
from packages.aura_core.api import service_registry
from packages.aura_core.persistent_context import PersistentContext
from packages.aura_shared_utils.utils.logger import logger
from packages.aura_core.event_bus import Event


class Orchestrator:
    """
    【最终职责】一个纯粹的、无状态的任务执行工具。
    不再拥有任何常驻服务或线程，仅在被调用时为单个任务执行提供上下文。
    """

    def __init__(self, base_dir: str, plan_name: str, pause_event: threading.Event):
        """
        初始化一个特定方案的执行上下文工具。
        :param base_dir: 项目基础路径
        :param plan_name: 当前方案名称
        :param pause_event: 全局暂停事件（由Scheduler管理）
        """
        self.base_dir = Path(base_dir)
        self.plan_name = plan_name
        self.plans_dir = self.base_dir / 'plans'
        self.current_plan_path = self.plans_dir / plan_name
        self.pause_event = pause_event

        # 注意：不再有任何全局服务实例化或任务定义加载
        # 这些都由Scheduler负责

    def setup_and_run(self, task_name: str, triggering_event: Optional[Event] = None):
        """
        【向后兼容】执行单个任务的入口，兼容Scheduler的旧式调用。
        """
        self.execute_task(task_name, triggering_event)

    def execute_task(self, task_name: str, triggering_event: Optional[Event] = None):
        """
        执行单个任务的核心方法。
        :param task_name: 任务名称（相对于方案的路径）
        :param triggering_event: （可选）触发此任务的事件
        """
        # 通过Scheduler的全局任务字典获取任务数据
        full_task_id = f"{self.plan_name}/{task_name}"

        # 从Scheduler获取任务定义
        try:
            scheduler = service_registry.get_service_instance('scheduler')
            task_data = scheduler.all_tasks_definitions.get(full_task_id)
        except Exception:
            # 如果Scheduler服务不可用，尝试直接加载（向后兼容）
            task_data = self._load_task_data_directly(task_name)

        if not task_data:
            logger.error(f"找不到任务定义: '{full_task_id}'")
            return

        # 1. 创建独立的上下文
        context = Context(triggering_event=triggering_event)

        # 2. 填充上下文基础信息
        self._initialize_context(context, triggering_event, full_task_id)

        # 3. 创建执行引擎
        engine = ExecutionEngine(
            context=context,
            orchestrator=self,
            pause_event=self.pause_event
        )

        # 4. 执行任务
        engine.run(task_data, full_task_id)

    def _initialize_context(self, context: Context, triggering_event: Optional[Event], task_id: str):
        """初始化任务执行上下文"""
        # 持久化上下文
        persistent_context_path = self.current_plan_path / 'persistent_context.json'
        persistent_context = PersistentContext(str(persistent_context_path))
        context.set('persistent_context', persistent_context)
        for key, value in persistent_context.get_all_data().items():
            context.set(key, value)

        # 配置服务
        try:
            config_service = service_registry.get_service_instance('config')
            config_service.set_active_plan(self.plan_name)
            context.set('config', config_service.active_plan_config)
        except Exception:
            context.set('config', {})

        # 基础设施
        context.set('log', logger)
        debug_dir = self.current_plan_path / 'debug_screenshots'
        debug_dir.mkdir(parents=True, exist_ok=True)
        context.set('debug_dir', str(debug_dir))

        # 任务元数据
        context.set('__task_name__', task_id)
        context.set('__plan_name__', self.plan_name)
        if triggering_event:
            context.set('event', triggering_event)

    def _load_task_data_directly(self, task_name: str) -> Dict | None:
        """直接从文件系统加载任务数据（向后兼容）"""
        tasks_dir = self.current_plan_path / "tasks"
        task_file = tasks_dir / f"{task_name}.yaml"

        if not task_file.exists():
            # 尝试作为路径
            task_file = tasks_dir / f"{task_name}"
            if task_file.is_dir():
                return None
            if not task_file.suffix:
                task_file = task_file.with_suffix('.yaml')

        if not task_file.exists():
            return None

        try:
            import yaml
            with open(task_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"加载任务文件 '{task_file}' 失败: {e}")
            return None

    def load_task_data(self, task_id: str) -> Dict | None:
        """供Engine调用的任务数据获取方法"""
        try:
            scheduler = service_registry.get_service_instance('scheduler')
            return scheduler.all_tasks_definitions.get(task_id)
        except Exception:
            # 向后兼容：如果是本方案的任务，尝试直接加载
            if task_id.startswith(f"{self.plan_name}/"):
                task_name = task_id[len(self.plan_name) + 1:]
                return self._load_task_data_directly(task_name)
            return None

    # === 保留的辅助方法（供外部API调用）===

    def get_persistent_context_data(self) -> dict:
        pc = PersistentContext(str(self.current_plan_path / 'persistent_context.json'))
        return pc.get_all_data()

    def save_persistent_context_data(self, data: dict):
        pc = PersistentContext(str(self.current_plan_path / 'persistent_context.json'))
        pc._data.clear()
        for key, value in data.items():
            pc.set(key, value)
        pc.save()

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

    def inspect_step(self, task_name: str, step_index: int) -> Any:
        """检查步骤（供外部API调用）"""
        task_data = self._load_task_data_directly(task_name)
        if not task_data:
            raise FileNotFoundError(f"找不到任务 '{task_name}'。")

        context = Context()
        context.set("__is_inspect_mode__", True)

        engine = ExecutionEngine(context=context, orchestrator=self)

        steps = task_data.get('steps', [])
        if not (0 <= step_index < len(steps)):
            raise IndexError(f"步骤索引 {step_index} 超出范围。")

        step_data = steps[step_index]
        try:
            rendered_params = engine._render_params(step_data.get('params', {}))
            result = engine.run_step(step_data, rendered_params)
            return result
        except Exception as e:
            logger.error(f"检查步骤时发生严重错误: {e}", exc_info=True)
            raise

    # === 向后兼容的方法存根 ===

    def perform_condition_check(self, condition_data: dict) -> bool:
        """向后兼容：条件检查"""
        from packages.aura_core.api import ACTION_REGISTRY
        action_name = condition_data.get('action')
        if not action_name:
            return False

        action_def = ACTION_REGISTRY.get(action_name)
        if not action_def or not action_def.read_only:
            return False

        try:
            context = Context()
            engine = ExecutionEngine(context=context, orchestrator=self)
            params = engine._render_params(condition_data.get('params', {}))
            result = engine.injector.execute_action(action_name, params)
            return bool(result)
        except Exception as e:
            logger.error(f"条件检查失败: {e}", exc_info=True)
            return False

    @property
    def task_definitions(self) -> Dict[str, Any]:
        """向后兼容：提供任务定义访问"""
        try:
            scheduler = service_registry.get_service_instance('scheduler')
            # 返回本方案的任务定义
            plan_tasks = {}
            prefix = f"{self.plan_name}/"
            for task_id, task_data in scheduler.all_tasks_definitions.items():
                if task_id.startswith(prefix):
                    relative_name = task_id[len(prefix):]
                    plan_tasks[relative_name] = task_data
            return plan_tasks
        except Exception:
            return {}

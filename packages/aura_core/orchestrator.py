# packages/aura_core/orchestrator.py (Refactored)
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

from .logger import logger
from .action_injector import ActionInjector
from .api import ACTION_REGISTRY
from .context_manager import ContextManager
from .engine import ExecutionEngine, JumpSignal
from .event_bus import Event
from .state_planner import StatePlanner
from .task_loader import TaskLoader
from .context import Context
from plans.aura_base.services.config_service import current_plan_name

class Orchestrator:
    """
    【Refactored】负责单个方案（Plan）内任务的编排、执行和生命周期管理。
    - 修正了所有 I/O 操作为异步非阻塞。
    - 移除了过时的 inspect_step 方法。
    - 统一了代码风格和异步实践。
    """

    def __init__(self, base_dir: str, plan_name: str, pause_event: asyncio.Event, state_planner: Optional[StatePlanner] = None):
        self.plan_name = plan_name
        self.current_plan_path = Path(base_dir) / 'plans' / plan_name
        self.pause_event = pause_event
        self.context_manager = ContextManager(self.plan_name, self.current_plan_path)
        self.task_loader = TaskLoader(self.plan_name, self.current_plan_path)
        self.state_planner = state_planner

    async def execute_task(
        self,
        task_name_in_plan: str,
        triggering_event: Optional[Event] = None,
        initial_data: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        异步执行一个任务，并处理任务链（go_task）和任务级失败（on_failure）。
        """
        # 【修复】在任务执行前，设置当前方案的配置上下文。
        # self.plan_name 在 __init__ 中被设置，所以这里总是正确的。
        token = current_plan_name.set(self.plan_name)
        logger.debug(f"Configuration context set to: '{self.plan_name}'")

        try:
            current_task_in_plan = task_name_in_plan
            last_result:Any = None
            # 捕获任务链中第一个任务的上下文，用于可能的 on_failure 处理器
            original_context = None

            while current_task_in_plan:
                full_task_id = f"{self.plan_name}/{current_task_in_plan}"
                task_data = self.task_loader.get_task_data(current_task_in_plan)

                if not task_data:
                    raise ValueError(f"Task definition not found: {full_task_id}")

                context_initial_data = initial_data if original_context is None else None
                context = await self.context_manager.create_context(
                    full_task_id,
                    triggering_event,
                    initial_data=context_initial_data
                )
                if original_context is None:
                    original_context = context

                engine = ExecutionEngine(context=context, orchestrator=self, pause_event=self.pause_event)
                result_from_engine: Dict[str, Any] = {}
                try:
                    result_from_engine = await engine.run(task_data, full_task_id)
                except JumpSignal as e:
                    logger.info(f"Orchestrator caught JumpSignal: type={e.type}, target={e.target}")
                    result = {'status': e.type, 'next_task': e.target}
                except Exception as e:
                    logger.critical(
                        f"Orchestrator caught unhandled exception for task '{full_task_id}': {e}",
                        exc_info=True)
                    result = {'status': 'error',
                              'error_details': {'node_id': 'orchestrator', 'message': str(e), 'type': type(e).__name__}}

                if result_from_engine.get('status') == 'success':
                    returns_template = task_data.get('returns')
                    final_return_value = None
                    if returns_template is not None:  # 修正：检查 not None
                        try:
                            injector = ActionInjector(context, engine)
                            final_return_value = await injector.render_return_value(returns_template)
                            logger.debug(
                                f"任务 '{full_task_id}' 显式返回值: {repr(final_return_value)} (来自模板: '{returns_template}')")
                        except Exception as e:
                            logger.error(f"渲染任务 '{full_task_id}' 的返回值失败: {e}")
                            raise ValueError(f"无法渲染返回值: {returns_template}") from e

                    # 【核心修改】统一成功返回值的格式
                    last_result = {
                        'status': 'success',
                        'returns': final_return_value if returns_template is not None else True
                    }
                else:
                    last_result = result_from_engine
                # --- 逻辑结束 ---

                # --- 任务级 on_failure 处理 ---
                if isinstance(last_result, dict) and last_result.get(
                        'status') == 'error' and 'on_failure' in task_data:
                    await self._run_failure_handler(task_data['on_failure'], original_context,
                                                    last_result.get('error_details'))
                    current_task_in_plan = None
                    continue

                # --- go_task 处理 ---
                if isinstance(last_result, dict) and last_result.get('status') == 'go_task' and last_result.get(
                        'next_task'):
                    next_full_task_id = last_result['next_task']
                    if '/' not in next_full_task_id:
                        next_plan_name = self.plan_name
                        next_task_in_plan = next_full_task_id
                    else:
                        next_plan_name, next_task_in_plan = next_full_task_id.split('/', 1)

                    if next_plan_name != self.plan_name:
                        logger.error(f"go_task不支持跨方案跳转: from '{self.plan_name}' to '{next_plan_name}'")
                        break

                    logger.info(f"Jumping from task '{current_task_in_plan}' to '{next_task_in_plan}'...")
                    current_task_in_plan = next_task_in_plan
                    triggering_event = None
                else:
                    current_task_in_plan = None

            return last_result

        finally:
            # 【修复】无论任务成功与否，都必须重置上下文，以防污染其他任务。
            current_plan_name.reset(token)
            logger.debug(f"Configuration context reset (was: '{self.plan_name}')")

    async def _run_failure_handler(self, failure_data: Dict, original_context: Context, error_details: Optional[Dict]):
        """在隔离的上下文中执行任务级的 on_failure 处理器。"""
        logger.error("Task execution failed. Running on_failure handler...")

        failure_context = original_context.fork()
        if error_details:
            failure_context.set('error', error_details)

        failure_handler_steps_list = failure_data.get('do')
        if not isinstance(failure_handler_steps_list, list):
            logger.warning("Task 'on_failure' block is missing a 'do' list. No handler action taken.")
            return

        # 【修正】复用引擎的线性列表转换逻辑，保持一致性
        handler_task_data = {'steps': ExecutionEngine._convert_linear_list_to_dag(failure_handler_steps_list)}
        engine = ExecutionEngine(context=failure_context, orchestrator=self, pause_event=self.pause_event)

        try:
            await engine.run(handler_task_data, "on_failure_handler")
            logger.info("on_failure handler execution finished.")
        except Exception as e:
            logger.critical(f"!! CRITICAL: The on_failure handler itself failed to execute: {e}", exc_info=True)

    def load_task_data(self, full_task_id: str) -> Optional[Dict]:
        """为 'run_task' action 提供加载子任务定义的服务。"""
        try:
            plan_name, task_name_in_plan = full_task_id.split('/', 1)
            if plan_name == self.plan_name:
                return self.task_loader.get_task_data(task_name_in_plan)
            logger.error(f"Orchestrator for '{self.plan_name}' cannot load task for other plan: '{full_task_id}'")
        except ValueError:
            logger.error(f"Invalid full_task_id format for loading: '{full_task_id}'")
        return None

    async def perform_condition_check(self, condition_data: dict) -> bool:
        """异步执行一个只读的条件检查 Action，用于方案的触发条件等。"""
        action_name = condition_data.get('action')
        if not action_name: return False

        action_def = ACTION_REGISTRY.get(action_name.lower())
        if not action_def or not action_def.read_only:
            logger.warning(f"Condition check '{action_name}' does not exist or is not read-only. Skipped.")
            return False

        try:
            # 使用一个临时的、隔离的上下文进行检查
            context = await self.context_manager.create_context(f"condition_check/{action_name}")
            injector = ActionInjector(context, engine=None)  # 条件检查不需要完整的引擎
            result = await injector.execute(action_name, condition_data.get('params', {}))
            return bool(result)
        except Exception as e:
            logger.error(f"Condition check '{action_name}' failed: {e}", exc_info=True)
            return False

    # 【移除】移除了过时的 inspect_step 方法

    # --- File and Context Proxy Methods ---

    @property
    def task_definitions(self) -> Dict[str, Any]:
        return self.task_loader.get_all_task_definitions()

    async def get_persistent_context_data(self) -> dict:
        """【修正】代理方法现在是异步的。"""
        return await self.context_manager.get_persistent_context_data()

    async def save_persistent_context_data(self, data: dict):
        """【修正】代理方法现在是异步的。"""
        await self.context_manager.save_persistent_context_data(data)

    def _validate_path(self, relative_path: str) -> Path:
        """内部辅助方法，用于验证和解析路径，防止路径遍历攻击。"""
        full_path = (self.current_plan_path / relative_path).resolve()
        # 安全检查：确保解析后的路径仍然在方案目录内
        if self.current_plan_path.resolve() not in full_path.parents:
            raise PermissionError(f"Access to files outside the plan package is forbidden: {relative_path}")
        return full_path

    async def get_file_content(self, relative_path: str) -> str:
        """【修正】异步、非阻塞地读取方案内的文件内容。"""
        full_path = self._validate_path(relative_path)

        def read_file():
            if not full_path.is_file():
                raise FileNotFoundError(f"File not found in plan '{self.plan_name}': {relative_path}")
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, read_file)

    async def get_file_content_bytes(self, relative_path: str) -> bytes:
        """【修正】异步、非阻塞地读取方案内的文件字节内容。"""
        full_path = self._validate_path(relative_path)

        def read_file_bytes():
            if not full_path.is_file():
                raise FileNotFoundError(f"File not found in plan '{self.plan_name}': {relative_path}")
            with open(full_path, 'rb') as f:
                return f.read()

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, read_file_bytes)

    async def save_file_content(self, relative_path: str, content: Any):
        """【修正】异步、非阻塞地向方案内的文件写入内容。"""
        full_path = self._validate_path(relative_path)

        def write_file():
            full_path.parent.mkdir(parents=True, exist_ok=True)
            mode = 'wb' if isinstance(content, bytes) else 'w'
            encoding = None if isinstance(content, bytes) else 'utf-8'
            with open(full_path, mode, encoding=encoding) as f:
                f.write(content)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, write_file)


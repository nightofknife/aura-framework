# packages/aura_core/orchestrator.py (FINAL CORRECTED VERSION)

import asyncio
import time
from pathlib import Path
from typing import Dict, Any, Optional

from plans.aura_base.services.config_service import current_plan_name
from .action_injector import ActionInjector
from .api import ACTION_REGISTRY, service_registry
from .context import Context
from .context_manager import ContextManager
from .engine import ExecutionEngine, JumpSignal
from .event_bus import Event
from .logger import logger
from .state_planner import StatePlanner
from .task_loader import TaskLoader


class Orchestrator:
    def __init__(self, base_dir: str, plan_name: str, pause_event: asyncio.Event,
                 state_planner: Optional[StatePlanner] = None):
        self.plan_name = plan_name
        self.current_plan_path = Path(base_dir) / 'plans' / plan_name
        self.pause_event = pause_event
        self.context_manager = ContextManager(self.plan_name, self.current_plan_path)
        self.task_loader = TaskLoader(self.plan_name, self.current_plan_path)
        self.state_planner = state_planner
        self.event_bus = service_registry.get_service_instance('event_bus')

    async def execute_task(
            self,
            task_name_in_plan: str,
            triggering_event: Optional[Event] = None,
            initial_data: Optional[Dict[str, Any]] = None
    ) -> Any:
        token = current_plan_name.set(self.plan_name)
        logger.debug(f"Configuration context set to: '{self.plan_name}'")

        current_task_in_plan = task_name_in_plan
        last_result: Any = None
        original_context = None
        task_start_time = time.time()

        # --- FIX: Added 'await' ---
        await self.event_bus.publish(Event(
            name='task.started',
            payload={
                'plan_name': self.plan_name,
                'task_name': task_name_in_plan,
                'start_time': task_start_time,
                'initial_context': initial_data or {}
            }
        ))

        final_status = 'unknown'
        try:
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

                async def step_event_callback(event_name: str, payload: Dict):
                    payload['plan_name'] = self.plan_name
                    payload['task_name'] = task_name_in_plan
                    # --- FIX: Added 'await' ---
                    await self.event_bus.publish(Event(name=event_name, payload=payload))

                engine = ExecutionEngine(
                    context=context,
                    orchestrator=self,
                    pause_event=self.pause_event,
                    event_callback=step_event_callback
                )

                result_from_engine: Dict[str, Any] = {}
                try:
                    result_from_engine = await engine.run(task_data, full_task_id)
                except JumpSignal as e:
                    logger.info(f"Orchestrator caught JumpSignal: type={e.type}, target={e.target}")
                    result_from_engine = {'status': e.type, 'next_task': e.target}
                except Exception as e:
                    logger.critical(
                        f"Orchestrator caught unhandled exception for task '{full_task_id}': {e}",
                        exc_info=True)
                    result_from_engine = {'status': 'error',
                                          'error_details': {'node_id': 'orchestrator', 'message': str(e),
                                                            'type': type(e).__name__}}

                if result_from_engine.get('status') == 'success':
                    returns_template = task_data.get('returns')
                    final_return_value = None
                    if returns_template is not None:
                        try:
                            injector = ActionInjector(context, engine)
                            final_return_value = await injector.render_return_value(returns_template)
                        except Exception as e:
                            logger.error(f"渲染任务 '{full_task_id}' 的返回值失败: {e}")
                            raise ValueError(f"无法渲染返回值: {returns_template}") from e
                    last_result = {
                        'status': 'success',
                        'returns': final_return_value if returns_template is not None else True
                    }
                else:
                    last_result = result_from_engine

                if isinstance(last_result, dict) and last_result.get('status') == 'error' and 'on_failure' in task_data:
                    await self._run_failure_handler(task_data['on_failure'], original_context,
                                                    last_result.get('error_details'))
                    current_task_in_plan = None
                    continue

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

            final_status = last_result.get('status', 'error') if isinstance(last_result, dict) else 'success'

        except Exception as e:
            final_status = 'failed'
            last_result = {'status': 'error', 'message': str(e)}
            logger.critical(f"Task execution failed at orchestrator level for '{task_name_in_plan}': {e}",
                            exc_info=True)

        finally:
            # --- FIX: Added 'await' ---
            await self.event_bus.publish(Event(
                name='task.finished',
                payload={
                    'plan_name': self.plan_name,
                    'task_name': task_name_in_plan,
                    'end_time': time.time(),
                    'duration': time.time() - task_start_time,
                    'final_status': final_status,
                    'final_result': last_result
                }
            ))
            current_plan_name.reset(token)
            logger.debug(f"Configuration context reset (was: '{self.plan_name}')")

        return last_result

    # ... (The rest of the Orchestrator methods remain unchanged) ...
    async def _run_failure_handler(self, failure_data: Dict, original_context: Context, error_details: Optional[Dict]):
        logger.error("Task execution failed. Running on_failure handler...")
        failure_context = original_context.fork()
        if error_details:
            failure_context.set('error', error_details)
        failure_handler_steps_list = failure_data.get('do')
        if not isinstance(failure_handler_steps_list, list):
            logger.warning("Task 'on_failure' block is missing a 'do' list. No handler action taken.")
            return
        handler_task_data = {'steps': ExecutionEngine._convert_linear_list_to_dag(failure_handler_steps_list)}
        engine = ExecutionEngine(context=failure_context, orchestrator=self, pause_event=self.pause_event)
        try:
            await engine.run(handler_task_data, "on_failure_handler")
            logger.info("on_failure handler execution finished.")
        except Exception as e:
            logger.critical(f"!! CRITICAL: The on_failure handler itself failed to execute: {e}", exc_info=True)

    def load_task_data(self, full_task_id: str) -> Optional[Dict]:
        try:
            plan_name, task_name_in_plan = full_task_id.split('/', 1)
            if plan_name == self.plan_name:
                return self.task_loader.get_task_data(task_name_in_plan)
            logger.error(f"Orchestrator for '{self.plan_name}' cannot load task for other plan: '{full_task_id}'")
        except ValueError:
            logger.error(f"Invalid full_task_id format for loading: '{full_task_id}'")
        return None

    async def perform_condition_check(self, condition_data: dict) -> bool:
        action_name = condition_data.get('action')
        if not action_name: return False
        action_def = ACTION_REGISTRY.get(action_name.lower())
        if not action_def or not action_def.read_only:
            logger.warning(f"条件检查 '{action_name}' 不存在或非只读，已跳过。")
            return False
        try:
            context = await self.context_manager.create_context(f"condition_check/{action_name}")
            engine = ExecutionEngine(context=context, orchestrator=self, pause_event=self.pause_event)
            result = await engine._execute_single_action_step(condition_data)
            return bool(result)
        except Exception as e:
            logger.error(f"条件检查 '{action_name}' 失败: {e}", exc_info=False)
            return False

    @property
    def task_definitions(self) -> Dict[str, Any]:
        return self.task_loader.get_all_task_definitions()

    async def get_persistent_context_data(self) -> dict:
        return await self.context_manager.get_persistent_context_data()

    async def save_persistent_context_data(self, data: dict):
        await self.context_manager.save_persistent_context_data(data)

    def _validate_path(self, relative_path: str) -> Path:
        full_path = (self.current_plan_path / relative_path).resolve()
        if self.current_plan_path.resolve() not in full_path.parents:
            raise PermissionError(f"Access to files outside the plan package is forbidden: {relative_path}")
        return full_path

    async def get_file_content(self, relative_path: str) -> str:
        full_path = self._validate_path(relative_path)

        def read_file():
            if not full_path.is_file():
                raise FileNotFoundError(f"File not found in plan '{self.plan_name}': {relative_path}")
            return full_path.read_text('utf-8')

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, read_file)

    async def get_file_content_bytes(self, relative_path: str) -> bytes:
        full_path = self._validate_path(relative_path)

        def read_file_bytes():
            if not full_path.is_file():
                raise FileNotFoundError(f"File not found in plan '{self.plan_name}': {relative_path}")
            return full_path.read_bytes()

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, read_file_bytes)

    async def save_file_content(self, relative_path: str, content: Any):
        full_path = self._validate_path(relative_path)

        def write_file():
            full_path.parent.mkdir(parents=True, exist_ok=True)
            mode = 'wb' if isinstance(content, bytes) else 'w'
            encoding = None if isinstance(content, bytes) else 'utf-8'
            with open(full_path, mode, encoding=encoding) as f:
                f.write(content)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, write_file)

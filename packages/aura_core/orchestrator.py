import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

from .logger import logger
from .action_injector import ActionInjector
from .api import ACTION_REGISTRY
from .context_manager import ContextManager
from .engine import ExecutionEngine, JumpSignal
from .event_bus import Event
from .task_loader import TaskLoader
from .context import Context


class Orchestrator:
    """
    【Advanced Flow Refactor - Stage 1】
    Orchestrator now handles task-level 'on_failure' blocks and JumpSignal exceptions
    from the new engine.
    """

    def __init__(self, base_dir: str, plan_name: str, pause_event: asyncio.Event):
        self.plan_name = plan_name
        self.current_plan_path = Path(base_dir) / 'plans' / plan_name
        self.pause_event = pause_event
        self.context_manager = ContextManager(self.plan_name, self.current_plan_path)
        self.task_loader = TaskLoader(self.plan_name, self.current_plan_path)

    async def execute_task(self, task_name_in_plan: str, triggering_event: Optional[Event] = None) -> Any:
        """
        Asynchronously executes a task, handling go_task jumps and task-level failures.
        """
        current_task_in_plan = task_name_in_plan
        last_result = None
        original_context = None

        while current_task_in_plan:
            full_task_id = f"{self.plan_name}/{current_task_in_plan}"
            task_data = self.task_loader.get_task_data(current_task_in_plan)

            if not task_data:
                raise ValueError(f"Task definition not found: {full_task_id}")

            context = await self.context_manager.create_context(full_task_id, triggering_event)
            if original_context is None:
                original_context = context  # Save the context of the very first task in the chain

            engine = ExecutionEngine(context=context, orchestrator=self, pause_event=self.pause_event)

            try:
                result = await engine.run(task_data, full_task_id)
            except JumpSignal as e:
                logger.info(f"Caught JumpSignal: type={e.type}, target={e.target}")
                result = {'status': e.type, 'next_task': e.target}
            except Exception as e:
                logger.critical(
                    f"Orchestrator caught unhandled exception during task execution for '{full_task_id}': {e}",
                    exc_info=True)
                result = {'status': 'error',
                          'error_details': {'node_id': 'orchestrator', 'message': str(e), 'type': type(e).__name__}}

            last_result = result

            # --- Task-level on_failure handling ---
            if result.get('status') == 'error' and 'on_failure' in task_data:
                await self._run_failure_handler(task_data['on_failure'], original_context, result.get('error_details'))
                # The task remains failed, but the handler has run.
                current_task_in_plan = None  # Stop execution chain after failure handler
                continue

            # --- go_task handling ---
            if result.get('status') == 'go_task' and result.get('next_task'):
                next_full_task_id = result['next_task']

                # Check if the jump is within the same plan
                if '/' not in next_full_task_id:
                    # Assume jump within the same plan if no plan name is specified
                    next_plan_name = self.plan_name
                    next_task_in_plan = next_full_task_id
                else:
                    next_plan_name, next_task_in_plan = next_full_task_id.split('/', 1)

                if next_plan_name != self.plan_name:
                    logger.error(
                        f"go_task does not support cross-plan jumps: from '{self.plan_name}' to '{next_plan_name}'")
                    break

                logger.info(f"Jumping from task '{current_task_in_plan}' to '{next_task_in_plan}'...")
                current_task_in_plan = next_task_in_plan
                triggering_event = None  # Subsequent tasks in a chain don't re-use the initial event
            else:
                current_task_in_plan = None

        return last_result

    async def _run_failure_handler(self, failure_data: Dict, original_context: Context, error_details: Optional[Dict]):
        """Executes the on_failure block in a new, forked context."""
        logger.error("Task execution failed. Running on_failure handler...")

        # Fork the original context and inject the error details
        failure_context = original_context.fork()
        if error_details:
            failure_context.set('error', error_details)

        # The failure handler itself is a mini-task, defined by a 'do' block
        # which is a list of steps. We convert it to a dict for the engine.
        failure_handler_steps_list = failure_data.get('do')
        if not isinstance(failure_handler_steps_list, list):
            logger.warning("Task 'on_failure' block is missing or not a 'do' list. No handler action taken.")
            return

        # Convert the list to a compatible DAG format for the engine
        handler_task_data = {
            'steps': {f"__failure_step_{i}": step for i, step in enumerate(failure_handler_steps_list)}}
        engine = ExecutionEngine(context=failure_context, orchestrator=self, pause_event=self.pause_event)

        try:
            await engine.run(handler_task_data, "on_failure_handler")
            logger.info("on_failure handler execution finished.")
        except Exception as e:
            logger.critical(f"!! CRITICAL: The on_failure handler itself failed to execute: {e}", exc_info=True)

    def load_task_data(self, full_task_id: str) -> Optional[Dict]:
        """Loads task data for a given full task ID."""
        plan_name, task_name_in_plan = full_task_id.split('/', 1)
        if plan_name == self.plan_name:
            return self.task_loader.get_task_data(task_name_in_plan)
        logger.error(f"Orchestrator for '{self.plan_name}' cannot load task for other plan: '{full_task_id}'")
        return None

    async def perform_condition_check(self, condition_data: dict) -> bool:
        """Asynchronously executes a read-only condition check Action."""
        action_name = condition_data.get('action')
        if not action_name:
            return False

        action_def = ACTION_REGISTRY.get(action_name.lower())
        if not action_def or not action_def.read_only:
            logger.warning(f"Condition check '{action_name}' does not exist or is not read-only. Skipped.")
            return False

        try:
            context = await self.context_manager.create_context(f"condition_check/{action_name}")
            engine = ExecutionEngine(context, self, self.pause_event)
            injector = ActionInjector(context, engine)
            result = await injector.execute(action_name, condition_data.get('params', {}))
            return bool(result)
        except Exception as e:
            logger.error(f"Condition check '{action_name}' failed: {e}", exc_info=True)
            return False

    async def inspect_step(self, task_name_in_plan: str, step_index: int) -> Any:
        """Asynchronously inspects the execution result of a single step."""
        task_data = self.task_loader.get_task_data(task_name_in_plan)
        if not task_data:
            raise FileNotFoundError(f"Task '{task_name_in_plan}' not found.")

        steps = task_data.get('steps', [])
        if not isinstance(steps, list):
            raise TypeError("Step inspection is only supported for legacy list-based tasks.")

        if not (0 <= step_index < len(steps)):
            raise IndexError(f"Step index {step_index} is out of bounds.")

        step_data = steps[step_index]
        action_name = step_data.get('action')
        if not action_name:
            return {"status": "no_action", "message": "This step has no executable action.", "step_data": step_data}

        try:
            context = await self.context_manager.create_context(f"inspect/{self.plan_name}/{task_name_in_plan}")
            context.set("__is_inspect_mode__", True)
            engine = ExecutionEngine(context, self, self.pause_event)
            injector = ActionInjector(context, engine)

            logger.info(f"Inspecting step '{step_data.get('name', step_index)}' with action: '{action_name}'")
            return await injector.execute(action_name, step_data.get('params', {}))
        except Exception as e:
            logger.error(f"Critical error during step inspection: {e}", exc_info=True)
            raise

    # --- File and Context Proxy Methods ---

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
            raise PermissionError(f"Access to files outside the plan package is forbidden: {relative_path}")
        if not full_path.is_file():
            raise FileNotFoundError(f"File not found in plan '{self.plan_name}': {relative_path}")
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()

    def get_file_content_bytes(self, relative_path: str) -> bytes:
        full_path = (self.current_plan_path / relative_path).resolve()
        if self.current_plan_path.resolve() not in full_path.parents:
            raise PermissionError(f"Access to files outside the plan package is forbidden: {relative_path}")
        if not full_path.is_file():
            raise FileNotFoundError(f"File not found in plan '{self.plan_name}': {relative_path}")
        with open(full_path, 'rb') as f:
            return f.read()

    def save_file_content(self, relative_path: str, content: str):
        full_path = (self.current_plan_path / relative_path).resolve()
        if self.current_plan_path.resolve() not in full_path.parents:
            raise PermissionError(f"Writing files outside the plan package is forbidden: {relative_path}")
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)

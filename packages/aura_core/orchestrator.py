# packages/aura_core/orchestrator.py

import asyncio
import time
from pathlib import Path
from typing import Dict, Any, Optional

from packages.aura_core.template_renderer import TemplateRenderer
from plans.aura_base.services.config_service import current_plan_name
from .action_injector import ActionInjector
from .api import service_registry
from .context import ExecutionContext
from .engine import ExecutionEngine, JumpSignal
from .event_bus import Event
from .logger import logger
from .state_planner import StatePlanner
from .task_loader import TaskLoader
from .state_store_service import StateStoreService


class Orchestrator:
    def __init__(self, base_dir: str, plan_name: str, pause_event: asyncio.Event,
                 state_planner: Optional[StatePlanner] = None):
        self.plan_name = plan_name
        self.current_plan_path = Path(base_dir) / 'plans' / plan_name
        self.pause_event = pause_event
        self.task_loader = TaskLoader(self.plan_name, self.current_plan_path)
        self.state_planner = state_planner
        self.event_bus = service_registry.get_service_instance('event_bus')
        self.state_store: StateStoreService = service_registry.get_service_instance('state_store')

    async def execute_task(
            self,
            task_name_in_plan: str,
            triggering_event: Optional[Event] = None,
            initial_data: Optional[Dict[str, Any]] = None
    ) -> Any:
        token = current_plan_name.set(self.plan_name)
        logger.debug(f"Configuration context set to: '{self.plan_name}'")

        task_start_time = time.time()
        await self.event_bus.publish(Event(
            name='task.started',
            payload={'plan_name': self.plan_name, 'task_name': task_name_in_plan, 'start_time': task_start_time,
                     'initial_context': initial_data or {}}
        ))

        final_status = 'unknown'
        final_result = None

        try:
            full_task_id = f"{self.plan_name}/{task_name_in_plan}"
            task_data = self.task_loader.get_task_data(task_name_in_plan)
            if not task_data:
                raise ValueError(f"Task definition not found: {full_task_id}")

            # 1. 创建根执行上下文
            root_context = ExecutionContext(initial_data=initial_data)

            # 2. 创建并运行引擎
            async def step_event_callback(event_name: str, payload: Dict):
                payload['plan_name'] = self.plan_name
                payload['task_name'] = task_name_in_plan
                await self.event_bus.publish(Event(name=event_name, payload=payload))

            engine = ExecutionEngine(
                orchestrator=self,
                pause_event=self.pause_event,
                event_callback=step_event_callback
            )

            # 引擎现在返回最终的上下文
            final_context = await engine.run(task_data, full_task_id, root_context)

            # 3. 从最终上下文中计算返回值
            returns_template = task_data.get('returns')
            if returns_template is not None:
                try:
                    renderer = TemplateRenderer(final_context, self.state_store)
                    final_result = await renderer.render(returns_template)
                except Exception as e:
                    logger.error(f"渲染任务 '{full_task_id}' 的返回值失败: {e}")
                    raise ValueError(f"无法渲染返回值: {returns_template}") from e
            else:
                final_result = True  # 默认成功返回True

            # 4. 确定最终状态
            final_status = 'success'
            for node_result in final_context.data['nodes'].values():
                if node_result.get('run_state', {}).get('status') == 'FAILED':
                    final_status = 'failed'
                    break

        except Exception as e:
            final_status = 'error'
            final_result = {'status': 'error', 'message': str(e)}
            logger.critical(f"Task execution failed at orchestrator level for '{task_name_in_plan}': {e}",
                            exc_info=True)

        finally:
            await self.event_bus.publish(Event(
                name='task.finished',
                payload={
                    'plan_name': self.plan_name, 'task_name': task_name_in_plan, 'end_time': time.time(),
                    'duration': time.time() - task_start_time, 'final_status': final_status,
                    'final_result': final_result
                }
            ))
            current_plan_name.reset(token)
            logger.debug(f"Configuration context reset (was: '{self.plan_name}')")

        return final_result

    # ... (其他Orchestrator方法保持不变, 比如 perform_condition_check, get_file_content 等)
    # 注意: perform_condition_check 也需要更新以使用新上下文模型
    async def perform_condition_check(self, condition_data: dict) -> bool:
        action_name = condition_data.get('action')
        if not action_name: return False

        try:
            # 为条件检查创建一个临时的、空的上下文
            temp_context = ExecutionContext()
            renderer = TemplateRenderer(temp_context, self.state_store)
            injector = ActionInjector(temp_context, self, renderer)

            result = await injector.execute(action_name, condition_data.get('params', {}))
            return bool(result)
        except Exception as e:
            logger.error(f"条件检查 '{action_name}' 失败: {e}", exc_info=False)
            return False

    # ... (其他文件操作方法不变)
    def load_task_data(self, full_task_id: str) -> Optional[Dict]:
        try:
            plan_name, task_name_in_plan = full_task_id.split('/', 1)
            if plan_name == self.plan_name:
                return self.task_loader.get_task_data(task_name_in_plan)
            logger.error(f"Orchestrator for '{self.plan_name}' cannot load task for other plan: '{full_task_id}'")
        except ValueError:
            logger.error(f"Invalid full_task_id format for loading: '{full_task_id}'")
        return None

    @property
    def task_definitions(self) -> Dict[str, Any]:
        return self.task_loader.get_all_task_definitions()

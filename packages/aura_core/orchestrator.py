# packages/aura_core/orchestrator.py

import asyncio
import time
import traceback
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
        # [NEW] 添加 services 属性，供 Engine 使用
        self.services = service_registry.get_all_services()


    async def execute_task(
            self,
            task_name_in_plan: str,
            triggering_event: Optional[Event] = None,
            # [MODIFIED] 将 initial_data 重命名为 inputs 以符合新架构
            inputs: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        执行一个任务并返回一个标准化的 TFR (Task Final Result) 对象。
        """
        token = current_plan_name.set(self.plan_name)
        logger.debug(f"Configuration context set to: '{self.plan_name}'")

        task_start_time = time.time()
        await self.event_bus.publish(Event(
            name='task.started',
            # [MODIFIED] 更新 payload key
            payload={'plan_name': self.plan_name, 'task_name': task_name_in_plan, 'start_time': task_start_time,
                     'inputs': inputs or {}}
        ))

        # 初始化TFR的各个部分
        final_status = 'UNKNOWN'
        user_data = None
        framework_data = None
        error_details = None

        try:
            full_task_id = f"{self.plan_name}/{task_name_in_plan}"
            task_data = self.task_loader.get_task_data(task_name_in_plan)
            if not task_data:
                raise ValueError(f"Task definition not found: {full_task_id}")

            # [MODIFIED] 使用 inputs 初始化 ExecutionContext
            # triggering_event 可以在未来用于填充 'initial' 数据
            root_context = ExecutionContext(inputs=inputs)

            async def step_event_callback(event_name: str, payload: Dict):
                payload['plan_name'] = self.plan_name
                payload['task_name'] = task_name_in_plan
                await self.event_bus.publish(Event(name=event_name, payload=payload))

            engine = ExecutionEngine(
                orchestrator=self,
                pause_event=self.pause_event,
                event_callback=step_event_callback
            )

            final_context = await engine.run(task_data, full_task_id, root_context)

            # ... (后续代码无重大逻辑变更)
            framework_data = final_context.data

            is_failed = False
            for node_result in framework_data.get('nodes', {}).values():
                run_state = node_result.get('run_state', {})
                if run_state.get('status') == 'FAILED':
                    final_status = 'FAILED'
                    error_details = run_state.get('error', {'message': 'A node failed.'})
                    if 'node_id' in node_result.get('run_state', {}):
                        error_details['node_id'] = node_result['run_state']['node_id']
                    is_failed = True
                    break

            if not is_failed:
                final_status = 'SUCCESS'

            if final_status == 'SUCCESS':
                returns_template = task_data.get('returns')
                if returns_template is not None:
                    try:
                        renderer = TemplateRenderer(final_context, self.state_store)
                        user_data = await renderer.render(returns_template)
                    except Exception as e:
                        raise ValueError(f"无法渲染返回值: {returns_template}") from e
                else:
                    user_data = True

        except Exception as e:
            final_status = 'ERROR'
            error_details = {'message': str(e), 'type': type(e).__name__}
            if getattr(self, 'debug_mode', False):
                error_details['traceback'] = traceback.format_exc()
            logger.critical(f"Task execution failed at orchestrator level for '{task_name_in_plan}': {e}",
                            exc_info=True)

        finally:
            tfr_object = {
                'status': final_status,
                'user_data': user_data,
                'framework_data': framework_data,
                'error': error_details
            }

            await self.event_bus.publish(Event(
                name='task.finished',
                payload={
                    'plan_name': self.plan_name, 'task_name': task_name_in_plan, 'end_time': time.time(),
                    'duration': time.time() - task_start_time, 'final_status': final_status,
                    'final_result': tfr_object
                }
            ))
            current_plan_name.reset(token)
            logger.debug(f"Configuration context reset (was: '{self.plan_name}')")

        return tfr_object


    async def perform_condition_check(self, condition_data: dict) -> bool:
        action_name = condition_data.get('action')
        if not action_name: return False

        try:
            temp_context = ExecutionContext()
            renderer = TemplateRenderer(temp_context, self.state_store)
            # [MODIFIED] 确保 ActionInjector 初始化时传递 services
            injector = ActionInjector(temp_context, self, renderer, self.services)

            result = await injector.execute(action_name, condition_data.get('params', {}))
            return bool(result)
        except Exception as e:
            logger.error(f"条件检查 '{action_name}' 失败: {e}", exc_info=False)
            return False

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

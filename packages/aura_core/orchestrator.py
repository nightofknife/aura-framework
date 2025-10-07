"""
定义了 `Orchestrator`（编排器），这是负责管理和执行单个方案（Plan）内任务的组件。

`Orchestrator` 是方案级别的执行协调者。每个方案（Plan）在加载时都会
拥有一个专属的 `Orchestrator` 实例。它位于 `ExecutionManager` 和 `ExecutionEngine`
之间，起着承上启下的作用。

主要职责:
- **任务加载**: 拥有一个 `TaskLoader` 实例，负责加载和缓存其方案内的所有任务定义。
- **执行入口**: 提供 `execute_task` 方法，作为执行方案内任何任务的统一入口。
- **上下文创建**: 为即将执行的任务创建初始的 `ExecutionContext`。
- **引擎实例化**: 在执行任务时，动态创建一个 `ExecutionEngine` 实例来处理该任务的
  DAG（有向无环图）执行。
- **结果标准化**: 将 `ExecutionEngine` 的执行结果包装成一个标准的 TFR
  （Task Final Result）对象，其中包含状态、用户数据、框架数据和错误信息。
- **事件发布**: 在任务开始和结束时，通过 `EventBus` 发布相应的事件。
- **条件检查**: 提供 `perform_condition_check` 方法，用于执行临时的、无状态的
  条件检查，这主要被 `InterruptService` 用于评估中断条件。
"""
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
from .engine import ExecutionEngine
from .event_bus import Event
from .logger import logger
from .state_planner import StatePlanner
from .task_loader import TaskLoader
from .state_store_service import StateStoreService


class Orchestrator:
    """
    方案级别的编排器，负责管理和执行单个方案内的所有任务。
    """
    def __init__(self, base_dir: str, plan_name: str, pause_event: asyncio.Event,
                 state_planner: Optional[StatePlanner] = None):
        """
        初始化一个方案的编排器。

        Args:
            base_dir (str): 项目的基础目录路径。
            plan_name (str): 此编排器负责的方案的名称。
            pause_event (asyncio.Event): 一个全局事件，用于暂停和恢复任务执行。
            state_planner (Optional[StatePlanner]): 与此方案关联的状态规划器实例。
        """
        self.plan_name = plan_name
        self.current_plan_path = Path(base_dir) / 'plans' / plan_name
        self.pause_event = pause_event
        self.task_loader = TaskLoader(self.plan_name, self.current_plan_path)
        self.state_planner = state_planner
        self.event_bus = service_registry.get_service_instance('event_bus')
        self.state_store: StateStoreService = service_registry.get_service_instance('state_store')
        self.services = service_registry.get_all_services()


    async def execute_task(
            self,
            task_name_in_plan: str,
            triggering_event: Optional[Event] = None,
            inputs: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        执行一个任务并返回一个标准化的 TFR (Task Final Result) 对象。

        这是编排器的核心方法。它处理任务的整个生命周期，从加载定义到
        执行，再到结果的格式化和事件发布。

        Args:
            task_name_in_plan (str): 要在当前方案中执行的任务的名称。
            triggering_event (Optional[Event]): 触发此任务执行的事件（如果有）。
            inputs (Optional[Dict[str, Any]]): 传递给任务的输入参数，
                通常在任务作为子任务被调用时使用。

        Returns:
            Dict[str, Any]: 一个标准化的 TFR 字典，包含以下键：
                - 'status': 'SUCCESS', 'FAILED', 或 'ERROR'。
                - 'user_data': 任务 `returns` 块渲染后的用户友好结果。
                - 'framework_data': 包含所有节点输出的完整执行上下文数据。
                - 'error': 如果任务失败，则包含错误详情。
        """
        token = current_plan_name.set(self.plan_name)
        logger.debug(f"配置上下文已设置为: '{self.plan_name}'")

        task_start_time = time.time()
        await self.event_bus.publish(Event(
            name='task.started',
            payload={'plan_name': self.plan_name, 'task_name': task_name_in_plan, 'start_time': task_start_time,
                     'inputs': inputs or {}}
        ))

        final_status = 'UNKNOWN'
        user_data = None
        framework_data = None
        error_details = None

        try:
            full_task_id = f"{self.plan_name}/{task_name_in_plan}"
            task_data = self.task_loader.get_task_data(task_name_in_plan)
            if not task_data:
                raise ValueError(f"找不到任务定义: {full_task_id}")

            root_context = ExecutionContext(inputs=inputs)

            async def step_event_callback(event_name: str, payload: Dict[str, Any]):
                payload['plan_name'] = self.plan_name
                payload['task_name'] = task_name_in_plan
                await self.event_bus.publish(Event(name=event_name, payload=payload))

            engine = ExecutionEngine(
                orchestrator=self,
                pause_event=self.pause_event,
                event_callback=step_event_callback
            )

            final_context = await engine.run(task_data, full_task_id, root_context)

            framework_data = final_context.data

            is_failed = False
            for node_result in framework_data.get('nodes', {}).values():
                run_state = node_result.get('run_state', {})
                if run_state.get('status') == 'FAILED':
                    final_status = 'FAILED'
                    error_details = run_state.get('error', {'message': '一个节点执行失败。'})
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
                    # 如果没有 'returns' 块，默认成功结果为 True
                    user_data = True

        except Exception as e:
            final_status = 'ERROR'
            error_details = {'message': str(e), 'type': type(e).__name__}
            if getattr(self, 'debug_mode', False):
                error_details['traceback'] = traceback.format_exc()
            logger.critical(f"任务 '{task_name_in_plan}' 在编排器层面执行失败: {e}",
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
            logger.debug(f"配置上下文已重置 (之前是: '{self.plan_name}')")

        return tfr_object


    async def perform_condition_check(self, condition_data: dict) -> bool:
        """
        执行一个临时的、无状态的条件检查。

        此方法用于快速执行一个在 `condition` 块中定义的 Action，并返回其布尔结果。
        它主要被 `InterruptService` 用来评估中断条件是否满足。

        Args:
            condition_data (dict): 定义了要执行的 `action` 及其 `params` 的字典。

        Returns:
            bool: 条件检查的结果。如果 Action 执行失败或未定义，则返回 False。
        """
        action_name = condition_data.get('action')
        if not action_name: return False

        try:
            temp_context = ExecutionContext()
            renderer = TemplateRenderer(temp_context, self.state_store)
            injector = ActionInjector(temp_context, self, renderer, self.services)

            result = await injector.execute(action_name, condition_data.get('params', {}))
            return bool(result)
        except Exception as e:
            logger.error(f"条件检查 '{action_name}' 失败: {e}", exc_info=False)
            return False

    def load_task_data(self, full_task_id: str) -> Optional[Dict[str, Any]]:
        """
        加载指定任务的定义数据。

        Args:
            full_task_id (str): 任务的完全限定ID，格式为 `plan_name/task_name`。

        Returns:
            Optional[Dict[str, Any]]: 任务的定义字典，如果找不到则返回 None。
        """
        try:
            plan_name, task_name_in_plan = full_task_id.split('/', 1)
            if plan_name == self.plan_name:
                return self.task_loader.get_task_data(task_name_in_plan)
            logger.error(f"'{self.plan_name}' 的编排器不能加载其他方案的任务: '{full_task_id}'")
        except ValueError:
            logger.error(f"加载任务时使用了无效的 full_task_id 格式: '{full_task_id}'")
        return None

    @property
    def task_definitions(self) -> Dict[str, Any]:
        """
        返回此方案中所有已加载的任务定义的字典。

        Returns:
            Dict[str, Any]: 一个从任务名称映射到其定义数据的字典。
        """
        return self.task_loader.get_all_task_definitions()

# -*- coding: utf-8 -*-
"""Aura 框架的编排器（Orchestrator）。

`Orchestrator` 是与单个自动化方案（Plan）绑定的核心组件。每个 Plan
在加载时都会拥有一个自己的 Orchestrator 实例。它负责该 Plan 内部
所有任务（Task）的执行生命周期管理。

主要职责:
- **任务执行**: 作为任务执行的入口点，负责加载任务定义、初始化执行上下文，
  并启动 `ExecutionEngine` 来运行任务。
- **生命周期事件**: 在任务开始和结束时，发布相应的事件到事件总线。
- **结果封装**: 将任务的执行结果封装成一个标准化的 TFR (Task Final Result)
  对象，其中包含状态、用户数据、框架数据和错误信息。
- **条件检查**: 提供 `perform_condition_check` 方法，用于执行中断规则或
  任务中的条件判断。
- **沙箱化文件系统访问**: 提供了一系列异步的文件和目录操作方法
  （如读、写、创建、删除、重命名），这些操作都被严格限制在当前 Plan
  的目录内，以确保安全性。
"""
import asyncio
import os
import time
import traceback
from pathlib import Path
from typing import Dict, Any, Optional
import aiofiles
import aioshutil
import yaml

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
    """管理和执行单个 Plan 内所有任务的编排器。"""
    def __init__(self, base_dir: str, plan_name: str, pause_event: asyncio.Event,
                 state_planner: Optional[StatePlanner] = None):
        """初始化 Orchestrator。

        Args:
            base_dir (str): 项目的基础目录路径。
            plan_name (str): 此编排器关联的 Plan 的名称。
            pause_event (asyncio.Event): 用于暂停/恢复任务执行的全局事件。
            state_planner (Optional[StatePlanner]): 与此 Plan 关联的状态规划器实例。
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
            inputs: Optional[Dict[str, Any]] = None,
            parent_cid: Optional[str] = None  # ✅ 新增参数
    ) -> Dict[str, Any]:
        """执行一个任务并返回一个标准化的 TFR (Task Final Result) 对象。

        这是任务执行的主要入口。它会设置上下文，发布生命周期事件，
        调用执行引擎，并最终封装和返回 TFR。

        Args:
            task_name_in_plan (str): 在当前 Plan 内的任务名称。
            triggering_event (Optional[Event]): 触发此次任务执行的事件（如有）。
            inputs (Optional[Dict[str, Any]]): 传递给任务的输入参数。

        Returns:
            一个包含任务执行最终结果的字典 (TFR)。
        """
        token = current_plan_name.set(self.plan_name)
        logger.debug(f"Configuration context set to: '{self.plan_name}'")

        task_start_time = time.time()
        _run_ms = int(task_start_time * 1000)
        run_id = f"{self.plan_name}/{task_name_in_plan}:{_run_ms}"

        await self.event_bus.publish(Event(
            name='task.started',
            payload={
                'run_id': run_id,
                'cid': parent_cid,
                'plan_name': self.plan_name,
                'task_name': task_name_in_plan,
                'start_time': task_start_time,
                'inputs': inputs or {}
            }
        ))

        final_status = 'UNKNOWN'
        user_data = None
        framework_data = None
        error_details = None

        try:
            full_task_id = f"{self.plan_name}/{task_name_in_plan}"
            task_data = self.task_loader.get_task_data(task_name_in_plan)
            if not task_data:
                raise ValueError(f"Task definition not found: {full_task_id}")

            root_context = ExecutionContext(inputs=inputs)

            async def step_event_callback(event_name: str, payload: Dict):
                payload['run_id'] = run_id
                payload['cid'] = parent_cid
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
                    'run_id': run_id,
                    'cid': parent_cid,
                    'plan_name': self.plan_name, 'task_name': task_name_in_plan,
                    'end_time': time.time(),
                    'duration': time.time() - task_start_time,
                    'final_status': final_status,
                    'final_result': tfr_object
                }
            ))
            current_plan_name.reset(token)
            logger.debug(f"Configuration context reset (was: '{self.plan_name}')")

        return tfr_object


    async def perform_condition_check(self, condition_data: dict) -> bool:
        """执行一个条件检查。

        这通常用于评估中断规则的 `condition` 块。

        Args:
            condition_data (dict): 包含 `action` 和 `params` 的条件定义。

        Returns:
            bool: 条件检查的结果，True 或 False。
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

    def load_task_data(self, full_task_id: str) -> Optional[Dict]:
        """加载指定任务的定义数据。

        Args:
            full_task_id (str): 任务的完全限定ID (e.g., "my_plan/my_task")。

        Returns:
            包含任务定义的字典，如果找不到则返回 None。
        """
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
        """获取此 Plan 中所有已加载的任务定义。"""
        return self.task_loader.get_all_task_definitions()

    def _resolve_and_validate_path(self, relative_path: str) -> Path:
        """(私有) 将相对路径解析为绝对路径，并进行安全检查以防止路径穿越。"""
        safe_relative_path = os.path.normpath(relative_path)
        if safe_relative_path.startswith(('..', '/')):
            raise ValueError(f"不安全的路径: '{relative_path}'。禁止访问父目录或绝对路径。")

        full_path = self.current_plan_path.joinpath(safe_relative_path).resolve()

        if not str(full_path).startswith(str(self.current_plan_path.resolve())):
            raise ValueError(f"路径穿越攻击被阻止: '{relative_path}' 解析到了 Plan 目录之外。")

        return full_path

    async def get_file_content(self, relative_path: str) -> str:
        """异步、安全地读取 Plan 目录内的一个文件内容（文本模式）。"""
        file_path = self._resolve_and_validate_path(relative_path)
        if not file_path.is_file():
            raise FileNotFoundError(f"文件未找到: '{relative_path}'")

        async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
            return await f.read()

    async def get_file_content_bytes(self, relative_path: str) -> bytes:
        """异步、安全地读取 Plan 目录内的一个文件内容（二进制模式）。"""
        file_path = self._resolve_and_validate_path(relative_path)
        if not file_path.is_file():
            raise FileNotFoundError(f"文件未找到: '{relative_path}'")

        async with aiofiles.open(file_path, mode='rb') as f:
            return await f.read()

    async def save_file_content(self, relative_path: str, content: Any):
        """异步、安全地向 Plan 目录内的一个文件写入内容。

        如果内容是字典或列表，则自动保存为 YAML 格式；否则保存为文本。
        如果文件是字节流，则以二进制模式写入。
        """
        file_path = self._resolve_and_validate_path(relative_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(file_path, mode='w', encoding='utf-8') as f:
            if isinstance(content, (dict, list)):
                loop = asyncio.get_running_loop()
                yaml_str = await loop.run_in_executor(
                    None,
                    lambda: yaml.dump(content, allow_unicode=True, sort_keys=False, indent=2)
                )
                await f.write(yaml_str)
            elif isinstance(content, bytes):
                async with aiofiles.open(file_path, mode='wb') as bf:
                    await bf.write(content)
            else:
                await f.write(str(content))

    async def create_directory(self, relative_path: str):
        """异步、安全地在 Plan 目录内创建一个新目录。"""
        dir_path = self._resolve_and_validate_path(relative_path)
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"目录已创建: {dir_path}")

    async def create_file(self, relative_path: str, content: str = ""):
        """异步、安全地在 Plan 目录内创建一个新文件。"""
        file_path = self._resolve_and_validate_path(relative_path)
        await self.save_file_content(relative_path, content)
        logger.info(f"文件已创建: {file_path}")

    async def rename_path(self, old_relative_path: str, new_relative_path: str):
        """异步、安全地在 Plan 目录内重命名一个文件或目录。"""
        old_path = self._resolve_and_validate_path(old_relative_path)
        new_path = self._resolve_and_validate_path(new_relative_path)

        if not old_path.exists():
            raise FileNotFoundError(f"源路径不存在: '{old_relative_path}'")
        if new_path.exists():
            raise FileExistsError(f"目标路径已存在: '{new_relative_path}'")

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, os.rename, old_path, new_path)
        logger.info(f"路径已重命名: 从 '{old_relative_path}' 到 '{new_relative_path}'")

    async def delete_path(self, relative_path: str):
        """异步、安全地删除 Plan 目录内的一个文件或目录（如果是目录则递归删除）。"""
        path_to_delete = self._resolve_and_validate_path(relative_path)

        if not path_to_delete.exists():
            logger.warning(f"尝试删除不存在的路径: '{relative_path}'，操作被跳过。")
            return

        if path_to_delete.is_file():
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, os.remove, path_to_delete)
            logger.info(f"文件已删除: {path_to_delete}")
        elif path_to_delete.is_dir():
            await aioshutil.rmtree(path_to_delete)
            logger.info(f"目录已递归删除: {path_to_delete}")

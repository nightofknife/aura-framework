# packages/aura_core/orchestrator.py

import asyncio
import os
import time
import traceback
from pathlib import Path
from typing import Dict, Any, Optional
import aiofiles
import aioshutil
import os
import yaml
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
        _run_ms = int(task_start_time * 1000)
        run_id = f"{self.plan_name}/{task_name_in_plan}:{_run_ms}"

        await self.event_bus.publish(Event(
            name='task.started',
            payload={
                'run_id': run_id,
                'plan_name': self.plan_name,
                'task_name': task_name_in_plan,
                'start_time': task_start_time,
                'inputs': inputs or {}
            }
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
                # 附加 run_id / plan / task，便于聚合
                payload['run_id'] = run_id
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
                    'run_id': run_id,
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

    def _resolve_and_validate_path(self, relative_path: str) -> Path:
        """
        将相对路径解析为绝对路径，并进行安全检查，防止路径穿越。
        """
        # 规范化路径，移除 '..' 等
        safe_relative_path = os.path.normpath(relative_path)
        if safe_relative_path.startswith(('..', '/')):
            raise ValueError(f"不安全的路径: '{relative_path}'。禁止访问父目录或绝对路径。")

        # 解析为绝对路径
        full_path = self.current_plan_path.joinpath(safe_relative_path).resolve()

        # 再次确认解析后的路径是否仍在 plan 目录内
        if not str(full_path).startswith(str(self.current_plan_path.resolve())):
            raise ValueError(f"路径穿越攻击被阻止: '{relative_path}' 解析到了 Plan 目录之外。")

        return full_path

    async def get_file_content(self, relative_path: str) -> str:
        """异步读取文件内容 (文本模式)。"""
        file_path = self._resolve_and_validate_path(relative_path)
        if not file_path.is_file():
            raise FileNotFoundError(f"文件未找到: '{relative_path}'")

        async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
            return await f.read()

    async def get_file_content_bytes(self, relative_path: str) -> bytes:
        """异步读取文件内容 (二进制模式)。"""
        file_path = self._resolve_and_validate_path(relative_path)
        if not file_path.is_file():
            raise FileNotFoundError(f"文件未找到: '{relative_path}'")

        async with aiofiles.open(file_path, mode='rb') as f:
            return await f.read()

    async def save_file_content(self, relative_path: str, content: Any):
        """
        异步保存文件内容。
        如果内容是字典或列表，则保存为 YAML；否则保存为文本。
        """
        file_path = self._resolve_and_validate_path(relative_path)

        # 确保父目录存在
        file_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(file_path, mode='w', encoding='utf-8') as f:
            if isinstance(content, (dict, list)):
                # 使用异步方式写入 YAML (通过线程池)
                loop = asyncio.get_running_loop()
                yaml_str = await loop.run_in_executor(
                    None,
                    lambda: yaml.dump(content, allow_unicode=True, sort_keys=False, indent=2)
                )
                await f.write(yaml_str)
            elif isinstance(content, bytes):
                # 如果是 bytes，需要以二进制模式打开
                async with aiofiles.open(file_path, mode='wb') as bf:
                    await bf.write(content)
            else:
                await f.write(str(content))

    async def create_directory(self, relative_path: str):
        """异步创建目录。"""
        dir_path = self._resolve_and_validate_path(relative_path)
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"目录已创建: {dir_path}")

    async def create_file(self, relative_path: str, content: str = ""):
        """异步创建空文件或带内容的文件。"""
        file_path = self._resolve_and_validate_path(relative_path)
        # 调用已有的 save_file_content 方法
        await self.save_file_content(relative_path, content)
        logger.info(f"文件已创建: {file_path}")

    async def rename_path(self, old_relative_path: str, new_relative_path: str):
        """异步重命名文件或目录。"""
        old_path = self._resolve_and_validate_path(old_relative_path)
        new_path = self._resolve_and_validate_path(new_relative_path)

        if not old_path.exists():
            raise FileNotFoundError(f"源路径不存在: '{old_relative_path}'")
        if new_path.exists():
            raise FileExistsError(f"目标路径已存在: '{new_relative_path}'")

        # aiofiles 没有 rename，使用 os.rename 放入线程池
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, os.rename, old_path, new_path)
        logger.info(f"路径已重命名: 从 '{old_relative_path}' 到 '{new_relative_path}'")

    async def delete_path(self, relative_path: str):
        """异步删除文件或目录 (递归删除)。"""
        path_to_delete = self._resolve_and_validate_path(relative_path)

        if not path_to_delete.exists():
            # 如果不存在，可以认为是幂等的，直接返回
            logger.warning(f"尝试删除不存在的路径: '{relative_path}'，操作被跳过。")
            return

        if path_to_delete.is_file():
            # aiofiles 没有 delete，使用 os.remove 放入线程池
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, os.remove, path_to_delete)
            logger.info(f"文件已删除: {path_to_delete}")
        elif path_to_delete.is_dir():
            # 使用 aioshutil 进行异步递归删除
            await aioshutil.rmtree(path_to_delete)
            logger.info(f"目录已递归删除: {path_to_delete}")

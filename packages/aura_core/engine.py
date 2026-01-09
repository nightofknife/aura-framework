# -*- coding: utf-8 -*-
"""Aura 框架的核心执行引擎。

该模块定义了 `ExecutionEngine` 类，它负责管理单个任务（Task）的完整执行
生命周期。引擎将任务的步骤（Steps）解析为一个有向无环图（DAG），并根据
依赖关系、条件逻辑和循环配置来调度和执行图中的每个节点（Node）。

主要职责:
- **图构建**: 将任务定义中的 `steps` 解析成依赖关系图。
- **DAG 调度**: 实现一个异步调度器，根据依赖满足情况来执行准备就绪的节点。
- **上下文管理**: 为每个节点创建和管理其独立的执行上下文（`ExecutionContext`），
  支持并行分支的上下文分叉（fork）和合并（merge）。
- **节点执行**: 调用 `ActionInjector` 来执行每个节点中定义的 `action`。
- **循环处理**: 支持 `for_each`, `times`, `while` 等多种循环模式。
- **状态管理**: 跟踪每个节点（`StepState`）和整个任务的执行状态。
- **事件与回调**: 在节点的生命周期事件（如开始、成功、失败）上触发回调。
- **异常处理**: 捕获和处理执行过程中的各种异常，包括控制流异常。
"""
import asyncio
import time
import traceback
import uuid
from collections import deque
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Callable, Coroutine

from packages.aura_core.logger import logger
from packages.aura_core.config_loader import get_config_value
from .action_injector import ActionInjector
from .api import service_registry
from .context import ExecutionContext
from .exceptions import StopTaskException, JumpSignal
from .state_store_service import StateStoreService
from .template_renderer import TemplateRenderer

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .orchestrator import Orchestrator


class StepState(Enum):
    """表示任务中一个步骤（节点）的执行状态。"""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ExecutionEngine:
    """负责单个任务的图构建、调度和执行的核心引擎。

    每个任务在运行时都会创建一个独立的 `ExecutionEngine` 实例。
    """

    def __init__(self, orchestrator: 'Orchestrator', pause_event: asyncio.Event,
                 event_callback: Optional[Callable] = None):
        """初始化执行引擎。

        Args:
            orchestrator: 父级 Orchestrator 实例，用于访问共享资源。
            pause_event: 一个全局的 `asyncio.Event`，用于暂停/恢复任务执行。
            event_callback: 一个可选的回调函数，用于在引擎执行过程中发送事件。
        """
        self.orchestrator = orchestrator
        self.pause_event = pause_event
        self.engine_id = str(uuid.uuid4())[:8]
        self.event_callback = event_callback
        self.debug_mode = getattr(orchestrator, 'debug_mode', True)
        self.services = getattr(orchestrator, 'services', {})
        self.default_node_timeout = float(get_config_value("execution.default_node_timeout_sec", 0) or 0)

        # 核心状态
        self.nodes: Dict[str, Dict] = {}
        self.dependencies: Dict[str, Any] = {}
        self.reverse_dependencies: Dict[str, Set[str]] = {}
        self.step_states: Dict[str, StepState] = {}
        self.ready_queue: deque[str] = deque()
        self._ready_set: Set[str] = set()

        # 上下文管理
        self.root_context: Optional[ExecutionContext] = None
        self.node_contexts: Dict[str, ExecutionContext] = {}

        # 异步任务管理
        self.running_tasks: Set[asyncio.Task] = set()
        self.completion_event: Optional[asyncio.Event] = None

        # 依赖的服务
        self.state_store: StateStoreService = self.services.get('state_store')
        self.VALID_DEPENDENCY_STATUSES = {'success', 'failed', 'running', 'skipped'}

        # ===== 新增：goto + label 机制 =====
        self.label_to_node: Dict[str, str] = {}  # label -> node_id 映射
        self.node_goto_jumps: Dict[str, int] = {}  # 跟踪每个 goto 的跳转次数

        # ===== 新增：节点元数据 =====
        self.node_metadata: Dict[str, Dict[str, Any]] = {}  # node_id -> metadata
        # metadata 包含：execution_count, retry_count, first_executed_at, last_executed_at

    async def _check_pause(self):
        if not self.pause_event:
            return
        if not self.pause_event.is_set():
            await self.pause_event.wait()


    async def run(self, task_data: Dict[str, Any], task_name: str, root_context: ExecutionContext) -> ExecutionContext:
        """执行一个任务的主入口点。

        此方法会构建依赖图，启动 DAG 调度器，并等待所有节点执行完毕。

        Args:
            task_data: 任务的完整定义字典。
            task_name: 任务的名称。
            root_context: 本次任务运行的根执行上下文。

        Returns:
            执行完毕后，包含了所有节点结果的最终根执行上下文。
        """
        task_display_name = task_data.get('meta', {}).get('title', task_name)
        logger.info(f"======= 开始执行任务: {task_display_name} =======")

        self.root_context = root_context
        steps = task_data.get('steps', {})
        if not isinstance(steps, dict) or not steps:
            logger.info('任务中没有可执行的步骤。')
            return self.root_context

        try:
            self._build_graph(steps)
            await self._run_dag_scheduler()
        except (JumpSignal, StopTaskException):
            pass
        except Exception as e:
            logger.error(f"!! 任务 '{task_name}' 在图构建或调度时发生严重错误: {e}", exc_info=True)
            for node_id, state in self.step_states.items():
                if state == StepState.PENDING:
                    self.step_states[node_id] = StepState.FAILED
                    error_info = {"type": type(e).__name__, "message": str(e)}
                    if self.debug_mode:
                        error_info["traceback"] = traceback.format_exc()
                    run_state = self._create_run_state(StepState.FAILED, time.time(), error=error_info)
                    self.root_context.add_node_result(node_id, {"run_state": run_state})

        final_status = 'success'
        for state in self.step_states.values():
            if state == StepState.FAILED:
                final_status = 'failed'
                break

        logger.info(f"======= 任务 '{task_display_name}' 执行结束 (最终状态: {final_status}) =======")
        return self.root_context

    def _build_graph(self, steps_dict: Dict[str, Any]):
        """(私有) 从任务步骤定义中构建依赖图。"""
        self.nodes = steps_dict
        all_node_ids = set(self.nodes.keys())

        # ===== 新增：收集标签 =====
        for node_id, node_data in self.nodes.items():
            label = node_data.get('label')
            if label:
                if label in self.label_to_node:
                    raise ValueError(f"标签 '{label}' 重复定义：节点 '{node_id}' 和 '{self.label_to_node[label]}'")
                self.label_to_node[label] = node_id

        # 构建依赖图
        for node_id, node_data in self.nodes.items():
            self.step_states[node_id] = StepState.PENDING
            self.reverse_dependencies.setdefault(node_id, set())

            # 初始化节点元数据
            self.node_metadata[node_id] = {
                'execution_count': 0,
                'retry_count': 0,
                'first_executed_at': None,
                'last_executed_at': None
            }

            deps_struct = node_data.get('depends_on', [])
            self.dependencies[node_id] = deps_struct

            all_deps = self._get_all_deps_from_struct(deps_struct)
            for dep_id in all_deps:
                if dep_id not in all_node_ids:
                    raise KeyError(f"节点 '{node_id}' 引用了未定义的依赖: '{dep_id}'")
                self.reverse_dependencies.setdefault(dep_id, set()).add(node_id)

            if node_id in all_deps:
                raise ValueError(f"检测到循环依赖: 节点 '{node_id}' 直接或间接依赖于自身。")

    def _get_all_deps_from_struct(self, struct: Any) -> Set[str]:
        """(私有) 递归地从复杂的依赖结构中提取所有节点 ID。"""
        deps = set()
        if isinstance(struct, str):
            if not struct.startswith("when:"):
                deps.add(struct)
        elif isinstance(struct, list):
            for item in struct:
                deps.update(self._get_all_deps_from_struct(item))
        elif isinstance(struct, dict):
            if 'and' in struct:
                deps.update(self._get_all_deps_from_struct(struct['and']))
            elif 'or' in struct:
                deps.update(self._get_all_deps_from_struct(struct['or']))
            elif 'not' in struct:
                deps.update(self._get_all_deps_from_struct(struct['not']))
            else:
                deps.update(struct.keys())
        return deps

    async def _run_dag_scheduler(self):
        """(??????) ???????????????DAG ???????????????????????????????????????????????????"""
        self.completion_event = asyncio.Event()
        await self._schedule_ready_nodes()

        if not self.running_tasks and self.nodes:
            if all(state == StepState.PENDING for state in self.step_states.values()):
                raise ValueError("???????????????????????????????????????????????????????????????????????????")

        if self.running_tasks:
            await self.completion_event.wait()

    async def _schedule_ready_nodes(self):
        """(??????) ?????????????????????????????????????????????????????????"""
        for node_id in self.nodes:
            await self._enqueue_ready_node(node_id)
        await self._drain_ready_queue()

    async def _enqueue_ready_node(self, node_id: str):
        if node_id in self._ready_set:
            return
        if self.step_states.get(node_id) != StepState.PENDING:
            return
        if await self._are_dependencies_met(node_id):
            self.ready_queue.append(node_id)
            self._ready_set.add(node_id)

    async def _drain_ready_queue(self):
        while self.ready_queue:
            node_id = self.ready_queue.popleft()
            self._ready_set.discard(node_id)
            if self.step_states.get(node_id) != StepState.PENDING:
                continue

            node_context = self._prepare_node_context(node_id)
            self.node_contexts[node_id] = node_context

            task = asyncio.create_task(self._execute_dag_node(node_id, node_context))
            self.running_tasks.add(task)
            task.add_done_callback(lambda t, nid=node_id: self._on_task_completed(t, nid))

    def _prepare_node_context(self, node_id: str) -> ExecutionContext:
        """(私有) 为即将执行的节点准备其执行上下文（通过分支和合并父上下文）。"""
        parent_ids = self._get_all_deps_from_struct(self.dependencies.get(node_id, []))

        if not parent_ids:
            return self.root_context.fork()

        parent_contexts = [self.node_contexts[pid] for pid in parent_ids if pid in self.node_contexts]

        if not parent_contexts:
            return self.root_context.fork()

        new_context = parent_contexts[0].fork()
        if len(parent_contexts) > 1:
            new_context.merge(parent_contexts[1:])

        return new_context

    def _on_task_completed(self, task: asyncio.Task, node_id: str):
        """(??????) ?????????????????????????????????????????????"""
        self.running_tasks.discard(task)
        try:
            task.result()
        except Exception as e:
            logger.critical(f"DAG??????????????????????????????????????????: {e}", exc_info=True)

        async def reschedule_and_maybe_finish():
            try:
                for downstream_id in self.reverse_dependencies.get(node_id, set()):
                    await self._enqueue_ready_node(downstream_id)
                await self._drain_ready_queue()
            finally:
                if not self.running_tasks and not self.ready_queue and self.completion_event:
                    self.completion_event.set()

        asyncio.create_task(reschedule_and_maybe_finish())

    async def _are_dependencies_met(self, node_id: str) -> bool:
        """(私有) 检查指定节点的所有依赖是否已满足。"""
        dep_struct = self.dependencies.get(node_id)
        return await self._evaluate_dep_struct(dep_struct)

    async def _evaluate_dep_struct(self, struct: Any) -> bool:
        """(私有) 递归地评估一个依赖结构是否为真。"""
        if struct is None:
            return True

        if isinstance(struct, str):
            if struct.startswith("when:"):
                expression = struct.replace("when:", "").strip()
                renderer = TemplateRenderer(self.root_context, self.state_store)
                return bool(await renderer.render(expression))
            else:
                state = self.step_states.get(struct)
                return state == StepState.SUCCESS

        if isinstance(struct, list):
            if not struct: return True
            results = await asyncio.gather(*[self._evaluate_dep_struct(item) for item in struct])
            return all(results)

        if isinstance(struct, dict):
            if not struct: return True

            if 'and' in struct:
                return await self._evaluate_dep_struct(struct['and'])
            if 'or' in struct:
                results = await asyncio.gather(*[self._evaluate_dep_struct(item) for item in struct['or']])
                return any(results)
            if 'not' in struct:
                return not await self._evaluate_dep_struct(struct['not'])

            if len(struct) != 1:
                raise ValueError(f"依赖条件格式错误: {struct}。状态查询必须是单个键值对。")

            node_id, expected_status_str = next(iter(struct.items()))

            raw_statuses = {s.strip().lower() for s in expected_status_str.split('|')}

            invalid_statuses = raw_statuses - self.VALID_DEPENDENCY_STATUSES
            if invalid_statuses:
                raise ValueError(f"发现未知的依赖状态: {invalid_statuses}. "
                                 f"支持的状态: {self.VALID_DEPENDENCY_STATUSES}")

            current_state_enum = self.step_states.get(node_id)
            if not current_state_enum:
                return False

            current_state_str = current_state_enum.name.lower()
            return current_state_str in raw_statuses

        return True

    def _create_run_state(self, status: StepState, start_time: float, error: Optional[Dict] = None) -> Dict:
        """(??) ????????????????"""
        end_time = time.time()
        return {
            "status": status.name,
            "start_time": time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(start_time)),
            "end_time": time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(end_time)),
            "duration": round(end_time - start_time, 3),
            "error": error
        }

    def _parse_retry_config(self, node_data: Dict[str, Any]) -> Dict[str, Any]:
        """解析节点的重试配置，支持旧格式和新格式。

        旧格式（兼容）：
            retry: 3
            retry_delay: 1
            retry_on: ["TimeoutError"]
            retry_condition: "{{ result.status >= 500 }}"

        新格式（推荐）：
            on_exception:
                retry: 3
                retry_on: ["TimeoutError"]
                delay: 1
            on_result:
                retry_when: "{{ result.status >= 500 }}"
                max_retries: 5
                delay: 2
        """
        # 默认值
        config = {
            "count": 0,
            "delay": 1.0,
            "on_exception": [],
            "condition": None
        }

        # 新格式：on_exception
        if 'on_exception' in node_data:
            exc_cfg = node_data['on_exception']
            if isinstance(exc_cfg, dict):
                config["count"] = int(exc_cfg.get('retry', exc_cfg.get('max_retries', 0)))
                config["delay"] = float(exc_cfg.get('delay', 1.0))
                exc_list = exc_cfg.get('retry_on', exc_cfg.get('on', []))
                if isinstance(exc_list, str):
                    exc_list = [exc_list]
                config["on_exception"] = exc_list

        # 新格式：on_result
        if 'on_result' in node_data:
            result_cfg = node_data['on_result']
            if isinstance(result_cfg, dict):
                result_retries = int(result_cfg.get('max_retries', result_cfg.get('retry', 0)))
                # 取两者中的最大值
                config["count"] = max(config["count"], result_retries)
                config["delay"] = float(result_cfg.get('delay', config["delay"]))
                config["condition"] = result_cfg.get('retry_when', result_cfg.get('when'))

        # 旧格式：兼容性支持
        if config["count"] == 0:  # 如果新格式没有设置，尝试旧格式
            default_delay = float(node_data.get("retry_delay", 1) or 1)
            retry_cfg = node_data.get("retry", {})

            if isinstance(retry_cfg, int):
                config["count"] = max(0, retry_cfg)
            elif isinstance(retry_cfg, dict):
                config["count"] = int(retry_cfg.get("count", retry_cfg.get("retry", 0) or 0))
                config["delay"] = float(retry_cfg.get("delay", retry_cfg.get("retry_delay", default_delay) or default_delay))
                on_exception = retry_cfg.get("on_exception") or retry_cfg.get("retry_on") or []
                config["condition"] = retry_cfg.get("condition") or retry_cfg.get("retry_condition") or config["condition"]
            else:
                try:
                    config["count"] = int(retry_cfg)
                except Exception:
                    config["count"] = 0

            config["delay"] = float(node_data.get("retry_delay", config["delay"]) or config["delay"])
            on_exception = node_data.get("retry_on", config["on_exception"]) or []
            if isinstance(on_exception, str):
                on_exception = [on_exception]
            config["on_exception"] = on_exception
            config["condition"] = node_data.get("retry_condition") or config["condition"]

        return config

    def _should_retry_on_exception(self, exc: Exception, retry_on: List[str]) -> bool:
        if not retry_on:
            return False
        exc_name = type(exc).__name__
        exc_full = f"{type(exc).__module__}.{exc_name}"
        return any(item == exc_name or item == exc_full for item in retry_on)

    def _resolve_node_timeout(self, node_data: Dict[str, Any]) -> Optional[float]:
        timeout = node_data.get("timeout_sec")
        if timeout is None:
            timeout = node_data.get("timeout")
        if timeout is None or timeout == 0:
            timeout = self.default_node_timeout
        try:
            timeout_val = float(timeout) if timeout is not None else 0
        except (TypeError, ValueError):
            return None
        return timeout_val if timeout_val > 0 else None

    async def _execute_dag_node(self, node_id: str, node_context: ExecutionContext):
        """(私有) 执行 DAG 中的一个节点。"""
        # ===== 新增：更新节点元数据 =====
        metadata = self.node_metadata[node_id]
        metadata['execution_count'] += 1
        if metadata['first_executed_at'] is None:
            metadata['first_executed_at'] = time.time()
        metadata['last_executed_at'] = time.time()

        # 将元数据注入上下文，供模板使用
        node_context.data['nodes'].setdefault(node_id, {})
        node_context.data['nodes'][node_id]['metadata'] = metadata.copy()
        self.root_context.data['nodes'].setdefault(node_id, {})
        self.root_context.data['nodes'][node_id]['metadata'] = metadata.copy()

        self.step_states[node_id] = StepState.RUNNING
        start_time = time.time()
        node_result: Dict[str, Any] = {}
        error_details = None
        action_result = None
        loop_info: Dict[str, Any] = {}
        try:
            loop_info = getattr(node_context, "data", {}).get("loop", {}) or {}
        except Exception:
            loop_info = {}

        def _base_payload() -> Dict[str, Any]:
            payload = {
                "node_id": node_id,
                "node_name": self.nodes.get(node_id, {}).get("name"),
                "start_time": start_time,
                "loop_index": loop_info.get("index", 0) or 0,
            }
            if "item" in loop_info:
                try:
                    item_val = loop_info.get("item")
                    item_repr = str(item_val)
                except Exception:
                    item_repr = repr(loop_info.get("item"))
                if item_repr and len(item_repr) > 200:
                    item_repr = item_repr[:200] + "..."
                payload["loop_item"] = item_repr
            return payload

        try:
            node_data = self.nodes[node_id]
            if self.event_callback:
                await self.event_callback('node.started', _base_payload())

            retry_cfg = self._parse_retry_config(node_data)
            max_attempts = retry_cfg["count"] + 1
            delay_sec = retry_cfg["delay"]
            retry_on = retry_cfg["on_exception"]
            cond_expr = retry_cfg["condition"]

            # ===== 新增：记录重试次数 =====
            actual_retry_count = 0

            attempt = 1
            while attempt <= max_attempts:
                await self._check_pause()
                try:
                    async def _run_action():
                        loop_config = node_data.get('loop')
                        if loop_config:
                            return await self._execute_loop(node_id, node_data, node_context, loop_config)
                        return await self._execute_single_action(node_data, node_context)

                    timeout_sec = self._resolve_node_timeout(node_data)
                    if timeout_sec:
                        action_result = await asyncio.wait_for(_run_action(), timeout=timeout_sec)
                    else:
                        action_result = await _run_action()

                    if cond_expr:
                        renderer = TemplateRenderer(node_context, self.state_store)
                        scope = {"result": action_result, "attempt": attempt}
                        should_retry = bool(
                            await renderer._render_recursive(
                                cond_expr, {**scope, **(await renderer.get_render_scope())}
                            )
                        )
                        if should_retry:
                            if attempt < max_attempts:
                                actual_retry_count += 1
                                logger.warning(
                                    f"节点 '{node_id}' 第{attempt}/{max_attempts - 1} 次重试：不满足 retry_condition，"
                                    f"{delay_sec}s 后重试..."
                                )
                                if self.event_callback:
                                    await self.event_callback('node.retrying', {
                                        **_base_payload(),
                                        'retry_seq': attempt,
                                        'retry_limit': max_attempts - 1,
                                        'reason': 'condition',
                                        'delay_sec': delay_sec,
                                    })
                                await asyncio.sleep(delay_sec)
                                attempt += 1
                                continue
                            raise RuntimeError("RetryConditionNotSatisfied")

                    break

                except Exception as e:
                    if attempt < max_attempts and self._should_retry_on_exception(e, retry_on):
                        actual_retry_count += 1
                        logger.warning(
                            f"节点 '{node_id}' 第{attempt}/{max_attempts - 1} 次重试：捕获到{type(e).__name__}: {e}，"
                            f"{delay_sec}s 后重试..."
                        )
                        if self.event_callback:
                            await self.event_callback('node.retrying', {
                                **_base_payload(),
                                'retry_seq': attempt,
                                'retry_limit': max_attempts - 1,
                                'exception_type': type(e).__name__,
                                'exception_message': str(e),
                                'delay_sec': delay_sec,
                            })
                        await asyncio.sleep(delay_sec)
                        attempt += 1
                        continue
                    raise

            # ===== 新增：更新 retry_count 元数据 =====
            metadata['retry_count'] = actual_retry_count
            node_context.data['nodes'][node_id]['metadata'] = metadata.copy()
            self.root_context.data['nodes'][node_id]['metadata'] = metadata.copy()

            outputs_block = node_data.get('outputs', {})
            if outputs_block:
                renderer = TemplateRenderer(node_context, self.state_store)
                output_render_scope = {"result": action_result, **(await renderer.get_render_scope())}
                for name, template in outputs_block.items():
                    node_result[name] = await renderer._render_recursive(template, output_render_scope)
            else:
                node_result['output'] = action_result

            self.step_states[node_id] = StepState.SUCCESS
            if self.event_callback:
                end_ts = time.time()
                await self.event_callback('node.succeeded', {
                    **_base_payload(),
                    'end_time': end_ts,
                    'duration_ms': round((end_ts - start_time) * 1000, 3),
                    'retry_count': actual_retry_count,
                    'output': node_result
                })

            # ===== 新增：执行 goto 逻辑 =====
            await self._handle_goto(node_id, node_data, node_context, action_result)

        except (JumpSignal, StopTaskException) as e:
            logger.error(f"??'{node_id}'????????: {e}", exc_info=self.debug_mode)
            self.step_states[node_id] = StepState.FAILED
            error_details = {"type": type(e).__name__, "message": str(e), "severity": e.severity}
            if self.debug_mode:
                error_details["traceback"] = e.get_full_traceback()
        except Exception as e:
            logger.error(f"??'{node_id}'????????? {e}", exc_info=True)
            self.step_states[node_id] = StepState.FAILED
            error_details = {"type": type(e).__name__, "message": str(e)}
            if self.debug_mode:
                error_details["traceback"] = traceback.format_exc()
            if self.event_callback:
                end_ts = time.time()
                await self.event_callback('node.failed', {
                    **_base_payload(),
                    'end_time': end_ts,
                    'duration_ms': round((end_ts - start_time) * 1000, 3),
                    'exception_type': type(e).__name__,
                    'exception_message': str(e)
                })

        finally:
            run_state = self._create_run_state(self.step_states.get(node_id, StepState.FAILED), start_time,
                                               error=error_details)
            final_node_output = {"run_state": run_state, **node_result}
            node_context.add_node_result(node_id, final_node_output)
            self.root_context.add_node_result(node_id, final_node_output)
            if self.event_callback:
                status = 'error' if error_details else 'success'
                end_ts = time.time()
                await self.event_callback('node.finished', {
                    **_base_payload(),
                    'end_time': end_ts,
                    'duration_ms': round((end_ts - start_time) * 1000, 3),
                    'status': status
                })
            

    async def _execute_single_action(self, node_data: Dict, node_context: ExecutionContext) -> Any:
        """(??) ?????????? action?"""
        renderer = TemplateRenderer(node_context, self.state_store)
        injector = ActionInjector(node_context, self, renderer, self.services)

        action_name = node_data.get('action')
        if not action_name:
            raise ValueError("??????? action")

        raw_params = node_data.get('params', {})

        # ??????????????? ActionInjector.execute
        return await injector.execute(action_name, raw_params)

    async def _execute_loop(self, node_id: str, node_data: Dict, node_context: ExecutionContext, loop_config: Dict) -> List[Any]:
        """(??) ?????????????"""
        renderer = TemplateRenderer(node_context, self.state_store)
        rendered_config = await renderer.render(loop_config)

        tasks: List[Coroutine] = []

        if 'for_each' in rendered_config:
            items = rendered_config['for_each']
            if not isinstance(items, (list, dict)):
                raise TypeError(f"loop.for_each ????????????????? {type(items)}")

            item_source = items.items() if isinstance(items, dict) else enumerate(items)
            for index, item in item_source:
                iter_context = node_context.fork()
                iter_context.set_loop_variables({'item': item, 'index': index})
                tasks.append(self._execute_single_action(node_data, iter_context))

        elif 'times' in rendered_config:
            try:
                count = int(rendered_config['times'])
            except (ValueError, TypeError):
                raise TypeError(f"loop.times ?????????????? {rendered_config['times']}")

            for i in range(count):
                iter_context = node_context.fork()
                iter_context.set_loop_variables({'index': i})
                tasks.append(self._execute_single_action(node_data, iter_context))

        elif 'while' in loop_config:
            results = []
            index = 0
            max_iterations = rendered_config.get('max_iterations', 1000)
            while index < max_iterations:
                iter_context = node_context.fork()
                iter_context.set_loop_variables({'index': index})

                while_renderer = TemplateRenderer(iter_context, self.state_store)
                condition = bool(await while_renderer.render(loop_config['while']))

                if not condition:
                    break

                result = await self._execute_single_action(node_data, iter_context)
                results.append(result)
                index += 1
            return results

        else:
            raise ValueError(f"?? '{node_id}' ? loop ????: {loop_config}")

        parallelism = rendered_config.get('parallelism', len(tasks))
        semaphore = asyncio.Semaphore(parallelism)

        async def run_with_semaphore(task: Coroutine) -> Any:
            async with semaphore:
                return await task

        results = await asyncio.gather(*[run_with_semaphore(task) for task in tasks])
        return results

    async def _handle_goto(self, node_id: str, node_data: Dict[str, Any],
                           node_context: ExecutionContext, action_result: Any):
        """(私有) 处理节点的 goto 逻辑。

        支持以下 goto 格式：
        1. 简单跳转: goto: "label_name"
        2. 条件跳转: goto: {target: "label", when: "{{ condition }}", max_jumps: 10}
        3. 多路跳转: goto: [{when: "...", target: "..."}, ...]
        """
        goto_config = node_data.get('goto')
        if not goto_config:
            return

        renderer = TemplateRenderer(node_context, self.state_store)
        scope = {"result": action_result, **(await renderer.get_render_scope())}

        # 情况1：简单跳转 goto: "label_name"
        if isinstance(goto_config, str):
            target_label = goto_config
            await self._execute_goto_jump(node_id, target_label, scope)
            return

        # 情况2：单个条件跳转 goto: {target, when, max_jumps}
        if isinstance(goto_config, dict) and 'target' in goto_config:
            goto_list = [goto_config]
        # 情况3：多路跳转 goto: [{...}, {...}]
        elif isinstance(goto_config, list):
            goto_list = goto_config
        else:
            logger.error(f"节点 '{node_id}' 的 goto 配置格式错误: {goto_config}")
            return

        # 处理条件跳转列表
        for goto_item in goto_list:
            if not isinstance(goto_item, dict):
                logger.error(f"节点 '{node_id}' 的 goto 条目格式错误: {goto_item}")
                continue

            target_label = goto_item.get('target')
            if not target_label:
                logger.error(f"节点 '{node_id}' 的 goto 缺少 target 字段")
                continue

            # 评估条件
            when_expr = goto_item.get('when')
            if when_expr:
                should_jump = bool(await renderer._render_recursive(when_expr, scope))
                if not should_jump:
                    continue  # 条件不满足，尝试下一个

            # 执行跳转
            max_jumps = goto_item.get('max_jumps')
            await self._execute_goto_jump(node_id, target_label, scope, max_jumps)
            return  # 成功跳转后退出

    async def _execute_goto_jump(self, from_node: str, target_label: str,
                                 scope: Dict[str, Any], max_jumps: Optional[int] = None):
        """(私有) 执行实际的 goto 跳转。

        Args:
            from_node: 发起跳转的节点ID
            target_label: 目标标签
            scope: 渲染作用域（用于日志）
            max_jumps: 最大跳转次数（可选）
        """
        # 查找目标节点
        target_node_id = self.label_to_node.get(target_label)
        if not target_node_id:
            raise ValueError(f"节点 '{from_node}' 的 goto 目标标签 '{target_label}' 未定义")

        # 检查跳转次数限制
        goto_key = f"{from_node}→{target_label}"
        current_jumps = self.node_goto_jumps.get(goto_key, 0)

        if max_jumps is not None and current_jumps >= max_jumps:
            logger.warning(
                f"节点 '{from_node}' 到标签 '{target_label}' 的 goto 已达到最大跳转次数 {max_jumps}，"
                f"跳过此次跳转"
            )
            return

        # 全局安全机制：防止无限循环
        max_total_steps = int(get_config_value("execution.max_total_steps", 1000))
        total_executed = sum(meta.get('execution_count', 0) for meta in self.node_metadata.values())
        if total_executed >= max_total_steps:
            raise RuntimeError(
                f"任务总执行步骤数已达到安全上限 {max_total_steps}，可能存在无限循环。"
                f"请检查 goto 逻辑或增加配置 'execution.max_total_steps'。"
            )

        # 更新跳转计数
        self.node_goto_jumps[goto_key] = current_jumps + 1

        logger.info(
            f"🔄 执行 goto：从节点 '{from_node}' 跳转到标签 '{target_label}' (节点 '{target_node_id}')，"
            f"跳转次数: {current_jumps + 1}" + (f"/{max_jumps}" if max_jumps else "")
        )

        # 重置目标节点状态，允许重新执行
        self.step_states[target_node_id] = StepState.PENDING

        # 将目标节点加入就绪队列
        await self._enqueue_ready_node(target_node_id)
        await self._drain_ready_queue()

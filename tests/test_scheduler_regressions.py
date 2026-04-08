# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from packages.aura_core.api.definitions import ActionDefinition, ServiceDefinition
from packages.aura_core.context.execution import ExecutionContext
from packages.aura_core.engine import action_injector as action_injector_module
from packages.aura_core.engine import action_resolver as action_resolver_module
from packages.aura_core.engine.action_injector import ActionInjector
from packages.aura_core.engine.action_resolver import ActionResolver
from packages.aura_core.packaging.core.task_validator import TaskDefinitionValidator, TaskValidationError
from packages.aura_core.packaging.manifest.schema import PackageInfo, PluginManifest
from packages.aura_core.scheduler.execution.dispatcher import DispatchService
from packages.aura_core.scheduler.execution.manager import ExecutionManager
from packages.aura_core.scheduler.queues.task_queue import Tasklet
from packages.aura_core.scheduler.run_query import RunQueryService
from packages.aura_core.scheduler import scheduling_service as scheduling_module
from packages.aura_core.utils.middleware import Middleware, middleware_manager


class _DummyRenderer:
    async def get_render_scope(self):
        return {}

    async def render(self, raw, scope=None):
        return raw


class _DummyEngine:
    orchestrator = SimpleNamespace(plan_name="demo")


class _DummySchedulerForDispatch:
    def __init__(self, *, resolve_ok=True, queue_raises=False):
        self.fallback_lock = threading.RLock()
        self.run_statuses = {}
        self._resolve_ok = resolve_ok
        self._queue_raises = queue_raises
        self.task_queue = self

    def _resolve_task_inputs_for_dispatch(self, **_kwargs):
        if not self._resolve_ok:
            return False, "invalid inputs"

        return (
            True,
            {
                "resolved": SimpleNamespace(task_ref="tasks:ok.yaml"),
                "full_task_id": "demo/tasks:ok.yaml",
                "task_def": {},
                "validated_inputs": {"k": "v"},
            },
        )

    def _ensure_tasklet_identifiers(self, _tasklet, **_kwargs):
        return None

    async def put(self, _tasklet):
        if self._queue_raises:
            raise RuntimeError("queue put failed")


class _DummySchedulerForRunQuery:
    def __init__(self, service_defs):
        self.fallback_lock = threading.RLock()
        self._service_defs = service_defs

    def _get_service_definitions(self):
        return list(self._service_defs)


class _TraceMiddleware(Middleware):
    def __init__(self, sink):
        self.sink = sink

    async def handle(self, action_def, context, params, next_handler):
        self.sink.append("before")
        next_params = dict(params)
        next_params["value"] = next_params["value"] + 1
        result = await next_handler(action_def, context, next_params)
        self.sink.append("after")
        return result * 2


def _build_manifest() -> PluginManifest:
    return PluginManifest(
        package=PackageInfo(
            name="@demo/pkg",
            version="1.0.0",
            description="demo",
            license="MIT",
        )
    )


def test_enqueue_schedule_item_rolls_back_status_when_input_validation_fails():
    scheduler = _DummySchedulerForDispatch(resolve_ok=False)
    scheduler.run_statuses["item-1"] = {
        "status": "idle",
        "last_run": datetime.now() - timedelta(minutes=10),
    }
    service = DispatchService(scheduler)

    ok = asyncio.run(
        service.enqueue_schedule_item(
            {
                "id": "item-1",
                "plan_name": "demo",
                "task": "tasks:broken.yaml",
                "enabled": True,
                "run_options": {},
            },
            source="schedule",
        )
    )

    assert ok is False
    assert scheduler.run_statuses["item-1"]["status"] == "idle"
    assert "queued_at" not in scheduler.run_statuses["item-1"]


def test_enqueue_schedule_item_rolls_back_status_when_queue_put_fails():
    scheduler = _DummySchedulerForDispatch(resolve_ok=True, queue_raises=True)
    service = DispatchService(scheduler)

    ok = asyncio.run(
        service.enqueue_schedule_item(
            {
                "id": "item-2",
                "plan_name": "demo",
                "task": "tasks:ok.yaml",
                "enabled": True,
                "run_options": {},
            },
            source="schedule",
        )
    )

    assert ok is False
    assert "item-2" not in scheduler.run_statuses


def test_cron_trigger_check_skips_gracefully_when_croniter_missing(monkeypatch):
    scheduler = SimpleNamespace(fallback_lock=threading.RLock(), schedule_items=[], run_statuses={})
    service = scheduling_module.SchedulingService(scheduler)

    monkeypatch.setattr(scheduling_module, "CRONITER_AVAILABLE", False)
    monkeypatch.setattr(scheduling_module, "croniter", None)

    matched = service._has_cron_trigger_match(
        {
            "id": "item-cron",
            "triggers": [{"type": "cron", "expression": "*/5 * * * *"}],
        },
        datetime.now(),
        {},
    )

    assert matched is False
    assert service._croniter_missing_logged is True


def test_resource_tag_parser_accepts_colon_rich_tags():
    manager = ExecutionManager(scheduler=SimpleNamespace())
    tasklet = Tasklet(
        task_name="demo/task",
        resource_tags=[
            "__mutex_group__:alpha:1",
            "__max_instances__:demo/task:2",
        ],
    )

    semaphores = asyncio.run(manager._get_semaphores_for(tasklet))

    assert len(semaphores) == 3
    assert "__mutex_group__:alpha" in manager._resource_sems
    assert "__max_instances__:demo/task" in manager._resource_sems


def test_services_api_serialization_handles_manifest_plugins_and_unknown_objects():
    manifest_plugin = _build_manifest()
    weird_plugin = object()

    service_defs = [
        ServiceDefinition(
            alias="svc1",
            fqid="demo/svc1",
            service_class=dict,
            plugin=manifest_plugin,
            public=True,
        ),
        ServiceDefinition(
            alias="svc2",
            fqid="demo/svc2",
            service_class=list,
            plugin=weird_plugin,
            public=True,
        ),
    ]
    query_service = RunQueryService(_DummySchedulerForRunQuery(service_defs))

    rows = query_service.get_all_services_for_api()

    assert rows[0]["plugin"]["name"] == "@demo/pkg"
    assert rows[0]["plugin"]["canonical_id"] == "demo/pkg"
    assert rows[0]["plugin"]["version"] == "1.0.0"
    assert rows[1]["plugin"]["name"] is None
    assert rows[1]["plugin"]["canonical_id"] is None


def test_action_injector_executes_through_middleware(monkeypatch):
    trace = []

    async def sample_action(value: int):
        trace.append("action")
        return value + 1

    action_def = ActionDefinition(
        func=sample_action,
        name="sample_action",
        read_only=False,
        public=True,
        service_deps={},
        plugin=_build_manifest(),
        is_async=True,
    )

    monkeypatch.setattr(action_injector_module.ACTION_REGISTRY, "get", lambda _name: action_def)

    context = ExecutionContext()
    injector = ActionInjector(
        context=context,
        engine=_DummyEngine(),
        renderer=_DummyRenderer(),
        services={},
    )
    injector.action_resolver = SimpleNamespace(resolve=lambda name: name)

    existing_middlewares = list(middleware_manager._middlewares)
    middleware_manager._middlewares.clear()
    middleware_manager.add(_TraceMiddleware(trace))
    try:
        result = asyncio.run(injector.execute("pkg/sample_action", {"value": 1}))
    finally:
        middleware_manager._middlewares.clear()
        middleware_manager._middlewares.extend(existing_middlewares)

    assert result == 6
    assert trace == ["before", "action", "after"]


def test_action_resolver_keeps_local_bare_action_resolution(monkeypatch):
    current_package = SimpleNamespace(
        package=SimpleNamespace(canonical_id="demo/pkg"),
        dependencies={},
        extends=[],
    )
    resolver = ActionResolver(current_package=current_package)

    monkeypatch.setattr(
        action_resolver_module.ACTION_REGISTRY,
        "get",
        lambda fqid: object() if fqid == "demo/pkg/click" else None,
    )

    assert resolver.resolve("click") == "demo/pkg/click"


def test_action_resolver_does_not_fallback_to_external_package_for_bare_name(monkeypatch):
    current_package = SimpleNamespace(
        package=SimpleNamespace(canonical_id="demo/pkg"),
        dependencies={},
        extends=[],
    )
    resolver = ActionResolver(current_package=current_package)

    external_def = SimpleNamespace(
        fqid="other/pkg/click",
        plugin=SimpleNamespace(package=SimpleNamespace(canonical_id="@other/pkg")),
    )

    def _get(fqid):
        if fqid == "click":
            return external_def
        return None

    monkeypatch.setattr(action_resolver_module.ACTION_REGISTRY, "get", _get)

    assert resolver.resolve("click") == "demo/pkg/click"


def test_action_resolver_requires_declared_dependency_for_explicit_external_action():
    current_package = SimpleNamespace(
        package=SimpleNamespace(canonical_id="demo/pkg"),
        dependencies={},
        extends=[],
    )
    resolver = ActionResolver(current_package=current_package)

    try:
        resolver.resolve("other/pkg/click")
        assert False, "expected undeclared external action to fail"
    except ValueError as exc:
        assert "undeclared external package" in str(exc)


def test_action_resolver_accepts_declared_dependency_for_explicit_external_action():
    current_package = SimpleNamespace(
        package=SimpleNamespace(canonical_id="demo/pkg"),
        dependencies={"@other/pkg": SimpleNamespace()},
        extends=[],
    )
    resolver = ActionResolver(current_package=current_package)

    assert resolver.resolve("other/pkg/click") == "other/pkg/click"


def test_task_validator_accepts_list_payload_under_logical_dep_operator():
    validator = TaskDefinitionValidator(
        plan_name="demo",
        enable_schema_validation=False,
        strict_validation=True,
    )

    validator._validate_depends_on_syntax(
        {
            "all": [
                "prepare",
                {"fetch": "success|skipped"},
            ]
        },
        file_path=Path("demo.yaml"),
        task_name="demo_task",
        step_id="finish",
        field_path="depends_on",
    )


def test_task_validator_rejects_top_level_list_dependency_shorthand():
    validator = TaskDefinitionValidator(
        plan_name="demo",
        enable_schema_validation=False,
        strict_validation=True,
    )

    try:
        validator._validate_depends_on_syntax(
            ["a", "b"],
            file_path=Path("demo.yaml"),
            task_name="demo_task",
            step_id="finish",
            field_path="depends_on",
        )
        assert False, "expected deprecated list shorthand to fail"
    except TaskValidationError as exc:
        assert exc.code == "deprecated_syntax"

# -*- coding: utf-8 -*-
"""Action execution adapter for rendering, injection and invocation."""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import time
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any, Dict

try:
    from pydantic import BaseModel, ValidationError

    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    BaseModel = object  # type: ignore
    ValidationError = Exception  # type: ignore

from packages.aura_core.observability.logging.core_logger import logger

from ..api import ACTION_REGISTRY, ActionDefinition, service_registry
from ..config.template import TemplateRenderer
from ..context.execution import ExecutionContext
from ..types import TaskRefResolver
from .action_resolver import ActionResolver
from ..utils.middleware import middleware_manager
from ..policy import PolicyDeniedError, evaluate_action_policy, infer_service_capabilities
from ..sdk import ActionContext, ActionResultBuilder, EvidenceWriter, PolicyContext

if TYPE_CHECKING:
    from .execution_engine import ExecutionEngine


class ActionInjector:
    """Resolve one action call inside an execution engine context."""

    def __init__(
        self,
        context: ExecutionContext,
        engine: "ExecutionEngine",
        renderer: TemplateRenderer,
        services: Dict[str, Any],
        current_package=None,
        service_resolver=None,
    ):
        self.context = context
        self.engine = engine
        self.renderer = renderer
        self.services = services or {}
        self.task_services = (
            (context.data.get("task_services") or {})
            if hasattr(context, "data") and isinstance(context.data, dict)
            else {}
        )
        self.current_package = current_package
        self.service_resolver = service_resolver
        self.action_resolver = ActionResolver(current_package=current_package)

    async def execute(self, action_name: str, raw_params: Dict[str, Any]) -> Any:
        if action_name == "run_task":
            raise ValueError(
                "Action 'run_task' has been removed. Please use 'aura.run_task' with parameter 'task_ref'."
            )
        if action_name == "aura.run_task":
            return await self._execute_run_task(raw_params)

        resolved_fqid = self.action_resolver.resolve(action_name)
        action_def = ACTION_REGISTRY.get(resolved_fqid)
        if not action_def:
            raise ValueError(f"Action '{action_name}' (resolved: '{resolved_fqid}') not found.")

        render_scope = await self.renderer.get_render_scope()
        rendered_params = await self.renderer.render(raw_params, scope=render_scope)
        started = time.perf_counter()
        service_capabilities, service_requires_admin = self._service_policy_metadata(action_def)
        decision = evaluate_action_policy(
            action_def=action_def,
            rendered_params=rendered_params,
            extra_capabilities=service_capabilities,
            extra_requires_admin=service_requires_admin,
        )
        decision_payload = decision.to_dict()
        self._record_policy_decision(decision_payload)
        self._prepare_sdk_runtime_context(action_def, decision_payload)
        if decision.decision != "allow":
            envelope = self._build_action_result(
                action_def=action_def,
                policy=decision_payload,
                ok=False,
                error_code="policy_denied",
                message=decision.reason,
                duration_ms=_elapsed_ms(started),
                value=None,
                rendered_params=rendered_params,
            )
            self._record_action_result(envelope)
            raise PolicyDeniedError(decision)

        try:
            value = await middleware_manager.process(
                action_def=action_def,
                context=self.context,
                params=rendered_params,
                final_handler=self._invoke_action,
            )
        except Exception as exc:
            envelope = self._build_action_result(
                action_def=action_def,
                policy=decision_payload,
                ok=False,
                error_code=type(exc).__name__,
                message=str(exc),
                duration_ms=_elapsed_ms(started),
                value=None,
                rendered_params=rendered_params,
            )
            self._record_action_result(envelope)
            raise

        envelope = self._build_action_result(
            action_def=action_def,
            policy=decision_payload,
            ok=True,
            error_code=None,
            message="",
            duration_ms=_elapsed_ms(started),
            value=value,
            rendered_params=rendered_params,
        )
        self._record_action_result(envelope)
        return value

    async def _invoke_action(
        self,
        action_def: ActionDefinition,
        _context: ExecutionContext,
        rendered_params: Dict[str, Any],
    ) -> Any:
        call_args = self._prepare_action_arguments(action_def, rendered_params)
        if action_def.is_async:
            return await action_def.func(**call_args)

        loop = asyncio.get_running_loop()
        context_snapshot = contextvars.copy_context()
        return await loop.run_in_executor(
            None,
            lambda: context_snapshot.run(action_def.func, **call_args),
        )

    async def _execute_run_task(self, raw_params: Dict[str, Any]) -> Any:
        logger.info("Executing sub-task via aura.run_task")

        render_scope = await self.renderer.get_render_scope()
        rendered_params = await self.renderer.render(raw_params, scope=render_scope)

        if "task_name" in rendered_params:
            raise ValueError("aura.run_task no longer accepts 'task_name'. Please use 'task_ref'.")

        task_ref = rendered_params.get("task_ref")
        if not task_ref:
            raise ValueError("aura.run_task action requires a 'task_ref' parameter.")
        if not isinstance(task_ref, str):
            raise ValueError(f"task_ref must be a string, got {type(task_ref).__name__}")
        if ".." in task_ref:
            raise ValueError(f"Security: task_ref contains path traversal sequence '..' - {task_ref}")
        if task_ref.startswith("/") or task_ref.startswith("\\"):
            raise ValueError(f"Security: task_ref cannot be an absolute path - {task_ref}")

        current_package = self.engine.orchestrator.plan_name
        resolved = TaskRefResolver.resolve(
            task_ref,
            default_package=current_package,
            enforce_package=current_package,
            allow_cross_package=False,
        )
        task_file_path = resolved.task_file_path
        task_key = resolved.task_key

        logger.info(
            "Parsed task_ref: ref='%s', file='%s', key='%s', target_plan='%s'",
            task_ref,
            task_file_path,
            task_key,
            resolved.reference.package,
        )

        sub_task_inputs = rendered_params.get("inputs", {})
        if not isinstance(sub_task_inputs, dict):
            raise TypeError("aura.run_task 'inputs' parameter must be a dictionary.")

        orchestrator = self.engine.orchestrator
        parent_cid = self.context.data.get("cid")
        logger.debug(
            "Executing sub-task file='%s', key='%s' with parent_cid='%s'",
            task_file_path,
            task_key,
            parent_cid,
        )

        tfr = await orchestrator.execute_task(
            task_file_path=task_file_path,
            task_key=task_key,
            inputs=sub_task_inputs,
            parent_cid=parent_cid,
        )

        if tfr.get("status") in ("FAILED", "ERROR"):
            error_info = tfr.get("error", {"message": "Unknown error in sub-task."})
            raise Exception(f"Sub-task '{task_ref}' failed. Reason: {error_info}")

        return tfr.get("framework_data")

    def _prepare_action_arguments(self, action_def: ActionDefinition, rendered_params: Dict[str, Any]) -> Dict[str, Any]:
        sig = action_def.signature
        call_args: Dict[str, Any] = {}
        consumed_param_names = set()
        accepts_var_keyword = False

        pydantic_param_name = None
        pydantic_model_class = None
        for name, param_spec in sig.parameters.items():
            if inspect.isclass(param_spec.annotation) and issubclass(param_spec.annotation, BaseModel):
                pydantic_param_name = name
                pydantic_model_class = param_spec.annotation
                break

        if pydantic_param_name and pydantic_model_class:
            try:
                call_args[pydantic_param_name] = pydantic_model_class(**rendered_params)
                rendered_params = {}
            except ValidationError as exc:
                error_msg = f"Action '{action_def.name}' parameter validation failed: {exc}"
                logger.error(error_msg)
                raise ValueError(error_msg) from exc

        for param_name, param_spec in sig.parameters.items():
            if param_name in call_args:
                continue
            if param_spec.kind == inspect.Parameter.VAR_POSITIONAL:
                continue
            if param_spec.kind == inspect.Parameter.VAR_KEYWORD:
                accepts_var_keyword = True
                continue

            if param_name in action_def.service_deps:
                service_fqid = action_def.service_deps[param_name]
                if service_fqid in self.task_services:
                    call_args[param_name] = self.task_services[service_fqid]
                elif service_fqid in self.services:
                    call_args[param_name] = self.services[service_fqid]
                elif self.service_resolver:
                    service_instance = self.service_resolver(service_fqid)
                    self.services[service_fqid] = service_instance
                    call_args[param_name] = service_instance
                else:
                    raise ValueError(
                        f"Service dependency '{service_fqid}' for action '{action_def.name}' is not available in execution scope."
                    )
                continue

            sdk_value = self._sdk_injected_value(param_name, param_spec.annotation)
            if sdk_value is not None:
                call_args[param_name] = sdk_value
                continue

            if param_name == "context" or param_spec.annotation is ExecutionContext:
                call_args[param_name] = self.context
                continue

            if param_name == "engine":
                call_args[param_name] = self.engine
                continue

            if param_name in rendered_params:
                call_args[param_name] = rendered_params[param_name]
                consumed_param_names.add(param_name)
                continue

            if param_spec.default is not inspect.Parameter.empty:
                continue

            raise ValueError(f"Action '{action_def.name}' missing required parameter '{param_name}'")

        if accepts_var_keyword:
            for key, value in rendered_params.items():
                if key in consumed_param_names or key in call_args:
                    continue
                call_args[key] = value

        return call_args

    def _record_policy_decision(self, decision: Dict[str, Any]) -> None:
        if not isinstance(getattr(self.context, "data", None), dict):
            return
        self.context.data["_last_policy_decision"] = decision
        self.context.data.setdefault("policy_decisions", []).append(decision)

    def _service_policy_metadata(self, action_def: ActionDefinition) -> tuple[list[str], bool]:
        capabilities: set[str] = set()
        requires_admin = False
        definitions = service_registry.get_all_service_definitions()
        by_fqid = {item.fqid: item for item in definitions}
        by_alias = {item.alias: item for item in definitions}
        for service_id in (action_def.service_deps or {}).values():
            service_def = by_fqid.get(service_id) or by_alias.get(service_id)
            if service_def is None:
                capabilities.update(infer_service_capabilities(service_id))
                continue
            declared = list(getattr(service_def, "capabilities", []) or [])
            capabilities.update(declared or infer_service_capabilities(service_def.alias or service_id))
            requires_admin = requires_admin or bool(getattr(service_def, "requires_admin", False))
        return sorted(capabilities), requires_admin

    def _record_action_result(self, envelope: Dict[str, Any]) -> None:
        if not isinstance(getattr(self.context, "data", None), dict):
            return
        self.context.data["_last_action_result"] = envelope
        self.context.data.setdefault("action_results", []).append(envelope)

    def _build_action_result(
        self,
        *,
        action_def: ActionDefinition,
        policy: Dict[str, Any],
        ok: bool,
        error_code: str | None,
        message: str,
        duration_ms: int,
        value: Any,
        rendered_params: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        desktop = _desktop_result_to_dict(value)
        locator_results = _locator_results_from_value(value, rendered_params or {})
        if desktop:
            desktop_data = dict(desktop.get("data") or {})
            desktop_data.pop("_image", None)
            data_value = _json_safe_value(desktop_data)
        else:
            data_value = _json_safe_value(value)
        sdk_evidence = []
        if isinstance(getattr(self.context, "data", None), dict):
            writer = self.context.data.get("_sdk_evidence_writer")
            if isinstance(writer, EvidenceWriter):
                sdk_evidence = writer.refs()
        evidence = list(desktop.get("evidence") or []) if desktop else []
        evidence.extend(sdk_evidence)
        evidence.extend({"kind": "locator", "payload": item} for item in locator_results)
        data = {"value": data_value, "rendered_params": rendered_params or {}}
        if locator_results:
            data["locators"] = locator_results
            if len(locator_results) == 1:
                data["locator"] = locator_results[0]
        return {
            "ok": ok if not desktop else bool(desktop.get("ok", ok)),
            "action": action_def.fqid,
            "backend": desktop.get("backend") if desktop else None,
            "capabilities_used": list(policy.get("capabilities") or []),
            "policy": {
                "profile": policy.get("profile"),
                "decision": policy.get("decision"),
                "reason": policy.get("reason") or "",
            },
            "duration_ms": int(desktop.get("duration_ms") or duration_ms) if desktop else duration_ms,
            "data": data,
            "error_code": desktop.get("error_code") if desktop else error_code,
            "message": desktop.get("message") if desktop else message,
            "evidence": evidence,
            "fallbacks": list(desktop.get("fallbacks") or []) if desktop else [],
        }

    def _prepare_sdk_runtime_context(self, action_def: ActionDefinition, policy: Dict[str, Any]) -> None:
        if not isinstance(getattr(self.context, "data", None), dict):
            return
        node_id = self.context.data.get("_current_node_id")
        cid = self.context.data.get("cid")
        package_id = getattr(getattr(action_def.plugin, "package", None), "canonical_id", None)
        policy_context = PolicyContext.from_decision(policy)
        evidence_writer = EvidenceWriter(cid=cid, node_id=node_id)
        orchestrator = getattr(self.engine, "orchestrator", None)
        action_context = ActionContext(
            cid=cid,
            node_id=node_id,
            inputs=dict(self.context.data.get("inputs") or {}),
            loop=dict(self.context.data.get("loop") or {}),
            package_id=str(package_id).lstrip("@") if package_id else None,
            plan_name=getattr(orchestrator, "plan_name", None),
            plan_path=str(getattr(orchestrator, "current_plan_path", "") or ""),
            initial=dict(self.context.data.get("initial") or {}),
            action_fqid=action_def.fqid,
            policy=policy_context,
            evidence=evidence_writer,
        )
        self.context.data["_sdk_policy_context"] = policy_context
        self.context.data["_sdk_evidence_writer"] = evidence_writer
        self.context.data["_sdk_action_context"] = action_context

    def _sdk_injected_value(self, param_name: str, annotation: Any) -> Any:
        if not isinstance(getattr(self.context, "data", None), dict):
            return None
        if annotation is ActionContext or param_name == "action_context":
            return self.context.data.get("_sdk_action_context")
        if annotation is EvidenceWriter:
            return self.context.data.get("_sdk_evidence_writer")
        if annotation is PolicyContext:
            return self.context.data.get("_sdk_policy_context")
        if annotation is ActionResultBuilder:
            return ActionResultBuilder()
        return None


def _desktop_result_to_dict(value: Any) -> Dict[str, Any] | None:
    if hasattr(value, "to_dict") and all(hasattr(value, attr) for attr in ("ok", "backend", "domain", "operation")):
        try:
            return value.to_dict()
        except Exception:
            return None
    if isinstance(value, dict) and {"ok", "backend", "domain", "operation"}.issubset(value):
        return value
    return None


def _json_safe_value(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return value.to_dict()
        except Exception:
            pass
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if hasattr(value, "tolist") and callable(value.tolist):
        try:
            return value.tolist()
        except Exception:
            pass
    return value


def _locator_results_from_value(value: Any, rendered_params: Dict[str, Any]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        locators: list[dict[str, Any]] = []
        for item in value:
            locators.extend(_locator_results_from_value(item, rendered_params))
        return locators
    if isinstance(value, dict):
        candidates = []
        for key in ("locator", "locators", "match", "matches", "results", "detections"):
            if key in value:
                candidates.extend(_locator_results_from_value(value[key], rendered_params))
        return candidates
    for attr in ("matches", "results", "detections"):
        if hasattr(value, attr):
            return _locator_results_from_value(getattr(value, attr), rendered_params)
    if not any(hasattr(value, attr) for attr in ("found", "rect", "center_point", "confidence")):
        return []
    rect = getattr(value, "rect", None)
    center = getattr(value, "center_point", None)
    confidence = getattr(value, "confidence", None)
    found = bool(getattr(value, "found", False))
    debug_info = _json_safe_value(getattr(value, "debug_info", {}) or {})
    best_rect = debug_info.get("best_match_rect_on_fail") if isinstance(debug_info, dict) else None
    bbox = _rect_to_bbox(rect or best_rect)
    locator = {
        "ok": found and center is not None,
        "bbox": bbox,
        "center": list(center) if center is not None else _center_from_bbox(bbox),
        "score": float(confidence or 0.0),
        "threshold": rendered_params.get("threshold"),
        "source": rendered_params.get("template") or rendered_params.get("text_to_find") or rendered_params.get("model"),
        "method": _locator_method(value, rendered_params),
        "backend": "action_result",
        "timestamp_ms": int(time.time() * 1000),
        "candidates": [debug_info] if isinstance(debug_info, dict) and debug_info else [],
        "error_code": None if found else "locator_not_found",
        "message": "" if found else "Locator target was not found.",
    }
    return [locator]


def _rect_to_bbox(rect: Any) -> list[float] | None:
    if not rect or len(rect) < 4:
        return None
    return [float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])]


def _center_from_bbox(bbox: list[float] | None) -> list[float] | None:
    if not bbox:
        return None
    return [bbox[0] + bbox[2] / 2.0, bbox[1] + bbox[3] / 2.0]


def _locator_method(value: Any, rendered_params: Dict[str, Any]) -> str:
    class_name = type(value).__name__.lower()
    if "ocr" in class_name or "text" in rendered_params or "text_to_find" in rendered_params:
        return "ocr_text"
    if "yolo" in class_name or "model" in rendered_params:
        return "yolo_detection"
    return "template_match"


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)

# -*- coding: utf-8 -*-
"""Static authoring tools for Aura task/package development."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from packages.aura_core.policy import infer_action_capabilities, get_active_policy_profile
from packages.aura_core.types import TaskRefResolver


def task_graph(*, base_path: str | Path, plan: str, task_ref: str, output_format: str) -> str:
    _task_path, _task_key, task = _load_task(base_path, plan, task_ref)
    graph = _build_graph(task.get("steps") or {})
    if output_format == "json":
        return json.dumps(graph, ensure_ascii=False, indent=2)
    lines = ["graph TD"]
    for node in graph["nodes"]:
        lines.append(f'  {node["id"]}["{node["id"]}: {node.get("action") or "-"}"]')
    for edge in graph["edges"]:
        lines.append(f'  {edge["from"]} --> {edge["to"]}')
    return "\n".join(lines)


def task_explain(*, base_path: str | Path, plan: str, task_ref: str, output_format: str) -> str:
    task_path, task_key, task = _load_task(base_path, plan, task_ref)
    steps = task.get("steps") or {}
    graph = _build_graph(steps)
    rows = []
    for node_id, step in steps.items():
        if not isinstance(step, dict):
            continue
        action = str(step.get("action") or "")
        rows.append(
            {
                "step_id": node_id,
                "action": action,
                "depends_on": step.get("depends_on"),
                "capabilities": infer_action_capabilities(action, read_only=False),
                "policy_profile": get_active_policy_profile(),
            }
        )
    payload = {
        "plan": plan,
        "task_ref": task_ref,
        "task_file": task_path,
        "task_key": task_key,
        "inputs": (task.get("meta") or {}).get("inputs", []),
        "steps": rows,
        "graph": graph,
    }
    if output_format == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2)
    lines = [f"Task: {plan}/{task_ref}", f"File: {task_path}", f"Policy: {payload['steps'][0]['policy_profile'] if rows else get_active_policy_profile()}"]
    for row in rows:
        lines.append(f"- {row['step_id']}: {row['action']} caps={','.join(row['capabilities'])}")
    return "\n".join(lines)


def template_render(
    *,
    base_path: str | Path,
    plan: str,
    task_ref: str,
    context_path: str | Path | None,
    output_format: str,
) -> str:
    _task_path, _task_key, task = _load_task(base_path, plan, task_ref)
    context = {}
    if context_path:
        context = json.loads(Path(context_path).read_text(encoding="utf-8"))
    payload = {
        "status": "success",
        "rendered": {},
        "errors": [],
    }
    for field in ("params", "when", "returns"):
        payload["rendered"][field] = []
    for step_id, step in (task.get("steps") or {}).items():
        if not isinstance(step, dict):
            continue
        for field in ("params", "when"):
            if field not in step:
                continue
            rendered, error = _render_value(step[field], context)
            item = {"step_id": step_id, "field": field, "value": rendered}
            if error:
                payload["status"] = "error"
                item["error"] = error
                payload["errors"].append({"step_id": step_id, "field": field, "message": error})
            payload["rendered"][field].append(item)
    if "returns" in task:
        rendered, error = _render_value(task["returns"], context)
        item = {"field": "returns", "value": rendered}
        if error:
            payload["status"] = "error"
            item["error"] = error
            payload["errors"].append({"field": "returns", "message": error})
        payload["rendered"]["returns"].append(item)
    if output_format == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if payload["status"] == "success":
        return "Template render passed."
    return "\n".join([f"Template render failed with {len(payload['errors'])} error(s):", *[f"- {e}" for e in payload["errors"]]])


def scaffold_package(*, base_path: str | Path, package_id: str) -> dict[str, Any]:
    root = Path(base_path).resolve()
    package_id = package_id.strip().lstrip("@")
    if "/" not in package_id:
        package_id = f"plans/{package_id}"
    namespace, name = package_id.split("/", 1)
    package_dir = root / ("plans" if namespace == "plans" else "packages") / name
    _write_new(package_dir / "manifest.yaml", _package_manifest(package_id, name))
    _write_new(package_dir / "tasks" / "hello.yaml", _task_yaml())
    _write_new(package_dir / "src" / "actions" / "__init__.py", "")
    _write_new(package_dir / "src" / "actions" / "hello.py", _hello_action())
    _write_new(package_dir / "README.md", f"# @{package_id}\n\nMinimal Aura package scaffold.\n")
    return {"status": "success", "package_id": package_id, "path": str(package_dir)}


def scaffold_task(*, base_path: str | Path, plan: str, name: str) -> dict[str, Any]:
    path = Path(base_path).resolve() / "plans" / plan / "tasks" / f"{name}.yaml"
    _write_new(path, _task_yaml(title=name))
    return {"status": "success", "path": str(path)}


def _load_task(base_path: str | Path, plan: str, task_ref: str) -> tuple[str, str | None, dict[str, Any]]:
    root = Path(base_path).resolve()
    resolved = TaskRefResolver.resolve(task_ref, default_package=plan, enforce_package=plan)
    task_path = resolved.task_file_path
    file_path = root / "plans" / plan / task_path
    data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    if "steps" in data:
        return task_path, None, data
    task_key = resolved.task_key or next(iter(data.keys()))
    task = data.get(task_key)
    if not isinstance(task, dict):
        raise ValueError(f"Task '{task_ref}' not found.")
    return task_path, task_key, task


def _build_graph(steps: dict[str, Any]) -> dict[str, Any]:
    nodes = []
    edges = []
    for step_id, step in steps.items():
        if not isinstance(step, dict):
            continue
        nodes.append({"id": str(step_id), "action": step.get("action")})
        for dep in _depends_on_ids(step.get("depends_on")):
            edges.append({"from": dep, "to": str(step_id)})
    return {"nodes": nodes, "edges": edges}


def _depends_on_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str)]
    if isinstance(value, dict):
        result = []
        for item in value.values():
            result.extend(_depends_on_ids(item))
        return result
    return []


def _render_value(value: Any, context: dict[str, Any]) -> tuple[Any, str | None]:
    env = SandboxedEnvironment(undefined=StrictUndefined)
    try:
        if isinstance(value, str):
            return env.from_string(value).render(**context), None
        if isinstance(value, list):
            rendered = []
            for item in value:
                child, error = _render_value(item, context)
                if error:
                    return rendered, error
                rendered.append(child)
            return rendered, None
        if isinstance(value, dict):
            rendered = {}
            for key, item in value.items():
                child, error = _render_value(item, context)
                if error:
                    return rendered, error
                rendered[key] = child
            return rendered, None
        return value, None
    except TemplateError as exc:
        return None, str(exc)


def _write_new(path: Path, content: str) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _package_manifest(package_id: str, name: str) -> str:
    return f"""package:
  name: '@{package_id}'
  version: 0.1.0
  description: Minimal Aura package
  license: MIT
requires:
  aura: '>=0.1.0'
exports:
  services: []
  actions:
    - name: hello
      module: plans.{name}.src.actions.hello
      function: hello
      public: true
      read_only: true
  tasks: []
"""


def _task_yaml(title: str = "Hello") -> str:
    return f"""meta:
  title: {title}
steps:
  start:
    action: hello
returns:
  ok: true
"""


def _hello_action() -> str:
    return """from packages.aura_core.api import action_info


@action_info(name="hello", read_only=True, public=True, capabilities=["filesystem.read"])
def hello():
    return {"message": "hello"}
"""

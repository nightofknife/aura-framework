---
name: aura-plan-authoring
description: Create, modify, and debug Aura plan packages that combine YAML tasks, Python actions, Python services, and manifest exports. Use when Codex needs to add or change files under `plans/{plan}/tasks`, implement `src/actions` or `src/services`, wire `aura.run_task` chains, update `manifest.yaml`, or investigate issues such as action not found, task schema/load problems, template rendering warnings, and mismatches between node `status` and business-level `output`.
---

# Aura Plan Authoring

## Overview

Use this skill when working on Aura plan packages that are split across four layers:
- task YAML for orchestration
- Python actions for callable behavior
- Python services for reusable capabilities
- `manifest.yaml` exports for runtime registration

Read the manifest and the target task first. Decide whether the change belongs in task orchestration, an action, or a service before editing anything.

## Workflow

1. Inspect `plans/{plan}/manifest.yaml`.
   Confirm which tasks, actions, and services are exported today.
2. Inspect the target task file in `plans/{plan}/tasks/`.
   Follow `depends_on`, `when`, `loop`, and `aura.run_task` boundaries before deciding where the bug or change lives.
3. Choose the implementation layer.
   Use a task for orchestration, an action for one callable behavior, and a service for reusable stateful or shared capability.
4. Update exports after adding new runtime symbols.
   In this repo, a new action or service is not available until `manifest.yaml` exports it.
5. Validate through the execution chain.
   Check parent task, child task, and `node_terminal_events` together; a root failure often wraps the real child failure.

## Read References

- Read [references/overview.md](references/overview.md) to orient on package structure and runtime relationships.
- Read [references/task-authoring.md](references/task-authoring.md) when changing YAML orchestration, `aura.run_task`, `depends_on`, `when`, or loop behavior.
- Read [references/action-authoring.md](references/action-authoring.md) when adding or changing Python actions.
- Read [references/service-authoring.md](references/service-authoring.md) when adding or changing reusable services.
- Read [references/manifest-and-registration.md](references/manifest-and-registration.md) whenever runtime registration is relevant.
- Read [references/debugging.md](references/debugging.md) when investigating task load errors, `action not found`, template rendering warnings, or confusing node outcomes.

## Repo Facts

- Treat `plans/resonance/manifest.yaml` and `plans/aura_base/manifest.yaml` as the primary examples for package exports.
- Treat `plans/resonance/tasks/auto_battle_dispatch.yaml` and `plans/resonance/tasks/auto_battle_combat.yaml` as representative task orchestration examples.
- Treat `plans/resonance/src/actions/battle_dispatch_actions.py` as a representative custom action module.
- Treat `plans/resonance/src/services/resonance_market_data_service.py` as a representative custom service module.
- Do not assume `@action_info` or `@service_info` is enough for runtime availability; this repo still requires manifest exports.

## Guardrails

- Distinguish node execution success from business success.
  A node can have `run_state.status = SUCCESS` while its `output` is `false`.
- Treat `find_text_and_click` style actions as "attempted successfully" rather than "business step definitely succeeded" unless `output` confirms it.
- Prefer fixing orchestration in the task layer when the issue is ordering, branching, or task boundaries.
- Prefer fixing an action when the issue is OCR logic, state polling, click behavior, parsing, or reusable runtime behavior.
- Prefer a service only when the capability is shared, stateful, or cache-backed across multiple actions/tasks.

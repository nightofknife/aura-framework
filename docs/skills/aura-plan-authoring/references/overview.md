# Aura Plan Overview

Aura plan packages in this repo follow one core shape:

```text
plans/<plan>/
  manifest.yaml
  tasks/
  src/actions/
  src/services/
  data/           # optional
```

The runtime relationship is:

```text
task YAML -> action/service names -> manifest exports -> Python implementation
```

Use these files as the main examples:
- `plans/resonance/manifest.yaml`
- `plans/aura_base/manifest.yaml`
- `plans/resonance/tasks/auto_battle_dispatch.yaml`
- `plans/resonance/src/actions/battle_dispatch_actions.py`
- `plans/resonance/src/services/resonance_market_data_service.py`

## Minimum package responsibilities

- `tasks/*.yaml`
  Define orchestration, branching, task inputs, and task-to-task calls.
- `src/actions/*.py`
  Define callable behaviors used directly by tasks.
- `src/services/*.py`
  Define reusable shared capability, especially when state, caching, or long-lived integration is involved.
- `manifest.yaml`
  Export runtime-visible tasks, actions, and services.

## Decision rule: task vs action vs service

- Use a task when the change is mostly orchestration.
  Examples: ordering, branching, loops, `aura.run_task`, retries by composition, per-route wiring.
- Use an action when the change is one reusable behavior.
  Examples: OCR-driven selection, parsing, polling, click-and-decide logic.
- Use a service when the change needs shared capability or state.
  Examples: cached market data, process management, OCR provider abstraction.

## Non-obvious repo rule

In this repo, runtime registration is manifest-driven.

That means:
- adding a Python action function is not enough
- adding a Python service class is not enough
- adding a new task YAML file is not enough

Each runtime-visible symbol must be exported from `manifest.yaml`.

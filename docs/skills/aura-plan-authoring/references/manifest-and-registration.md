# Manifest and Registration

`manifest.yaml` is the runtime source of truth for plan exports in this repo.

Representative examples:
- `plans/resonance/manifest.yaml`
- `plans/aura_base/manifest.yaml`

## What the manifest exports

- `exports.services`
- `exports.actions`
- `exports.tasks`

These exports determine what the runtime can see.

## Action export shape

Typical action export:

```yaml
- name: resonance.run_battle_resolution
  module: plans.resonance.src.actions.battle_dispatch_actions
  function: resonance_run_battle_resolution
  public: true
  read_only: false
  timeout: null
  description: ...
  parameters:
    - name: capture_count
      type: Any
      required: false
      default: null
```

## Service export shape

Typical service export:

```yaml
- name: resonance_market_data
  module: plans.resonance.src.services.resonance_market_data_service
  class: ResonanceMarketDataService
  public: true
  singleton: true
  replace: null
  description: ...
```

## Task export shape

Tasks are also exported so the runtime can reference them by `task_ref`.

This matters when:
- a new task file is added
- task keys are renamed
- `aura.run_task` starts failing to resolve

## Non-obvious rule

`@action_info` and `@service_info` do not replace manifest exports in this repo.

The decorators describe the symbol.
The manifest exposes the symbol.

If you add a new action/service and forget the manifest:
- code compiles
- task YAML can reference the name
- runtime still fails with `Action ... not found` or missing service resolution

## Registration checklist

Whenever you add or rename an action or service:
- add the Python symbol
- add the manifest export
- restart or reload the runtime
- confirm logs show the symbol being registered

Useful log symptom:
- old action appears in registration logs
- new action does not
- root cause is usually missing manifest export

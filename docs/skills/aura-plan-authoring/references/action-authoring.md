# Action Authoring

Use actions for one callable behavior that tasks can orchestrate.

Representative module:
- `plans/resonance/src/actions/battle_dispatch_actions.py`

Representative base action module:
- `plans/aura_base/src/actions/atomic_actions.py`

## Action shape

Typical custom action structure:

```python
from packages.aura_core.api import action_info, requires_services

@action_info(
    name="resonance.some_action",
    public=True,
    read_only=False,
    description="..."
)
@requires_services(
    app="plans/aura_base/app",
    ocr="plans/aura_base/ocr",
)
def resonance_some_action(..., app=None, ocr=None) -> dict:
    ...
```

## Rules

- Give the action a stable public name under the plan namespace.
- Keep the function name explicit and unique.
- Use `@requires_services` for runtime dependencies instead of constructing them manually.
- Return structured dictionaries when downstream task logic needs fields.
- Raise structured errors when failure details matter to debugging.

## Read-only guidance

- `read_only=True`
  Use when the action only observes or computes.
- `read_only=False`
  Use when the action clicks, drags, types, mutates service state, or performs side effects.

## Return style

Prefer machine-usable results:

```python
return {
    "found": True,
    "click_x": x,
    "click_y": y,
}
```

This is better than returning bare booleans when downstream logic needs branching or diagnostics.

## Error style

When an action has meaningful failure modes, raise a structured error rather than silently returning vague false values.

Examples of useful error conditions:
- missing required service
- invalid input shape
- OCR region capture failure
- state machine timeout
- consistency check failure

## Important registration rule

Defining the Python function is not enough.

After adding or renaming an action:
- export it in `plans/{plan}/manifest.yaml`
- verify the runtime logs show it being registered

If logs do not show a registration line for the action, the action is still unavailable even if the code exists.

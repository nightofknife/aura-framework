# Debugging Aura Plans

Use this order when debugging plan behavior.

## 1. Find the failing layer

Check whether the problem is in:
- task loading
- task orchestration
- action registration
- action logic
- service registration or state

Do not assume the top-level task failure message is the real root cause.

## 2. Read nested task failures from child to parent

`aura.run_task` wraps child failures.

For nested flows:
- identify the deepest child task
- inspect that task's failing node
- only then move back up the wrapped exceptions

## 3. Use three sources together

- main session log in `logs/`
- runtime registration lines that show actions or services being registered
- `logs/runs/run_store.sqlite3`, especially `node_terminal_events`

The SQLite event table is often the fastest way to see:
- which nodes actually ran
- which nodes were skipped
- terminal status
- exception type and message

## 4. Distinguish `status` from `output`

This repo frequently uses actions where:
- `run_state.status = SUCCESS`
- but `output = false`

Example:
- `find_text_and_click` may execute successfully as an action call
- but still report that the target text was not found

So a downstream dependency that only cares about execution order can behave very differently from one that cares about business truth.

## 5. Common failure patterns

### Action not found

Typical cause:
- the Python function exists
- `manifest.yaml` does not export it

Check:
- manifest export exists
- registration log contains the action name

### Task loads but behaves strangely

Typical causes:
- `when` branch conditions do not match actual inputs
- `depends_on` is correct for scheduling but wrong for business gating
- upstream task is passing stale or incompatible fields

### Template rendering warnings

Typical symptom:
- warnings about `loop.item.*` being undefined

Interpretation:
- often a looped node is being pre-rendered outside loop context
- warning may be noisy but not the primary runtime failure
- still inspect whether the looped node eventually receives the correct values

### OCR flow regressions

Typical causes:
- wrong ROI
- insufficient wait duration
- state transition assumption is wrong
- an action was modified but the isolated entry-point test was skipped

## 6. Practical debugging rules

- When changing OCR or battle-state logic, first validate through a standalone entry task.
- After reconnecting a validated child task into the main chain, re-check parent task dependencies and input contracts.
- If a new action or service does not appear in registration logs, stop and fix manifest export before debugging the business logic.

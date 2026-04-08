# Task Authoring

## Task file structure

A task YAML file usually contains:

```yaml
task_key:
  meta:
    title: ...
    description: ...
    inputs:
      - name: ...
  steps:
    step_name:
      action: some.action
      params: {}
      depends_on: ...
      when: ...
  returns:
    success: true
```

Representative examples:
- `plans/resonance/tasks/auto_battle_dispatch.yaml`
- `plans/resonance/tasks/auto_battle_combat.yaml`

## Use the task layer for orchestration

Keep these decisions in YAML when possible:
- ordering
- branching with `when`
- task decomposition with `aura.run_task`
- loop execution
- grouping multiple reusable actions into one business chain

Do not push orchestration into Python unless the behavior becomes inherently state-machine heavy or impossible to express safely in task nodes.

## Key fields

- `meta.inputs`
  Define the external contract for the task.
- `steps.<name>.action`
  Resolve to an exported action FQID or external action path.
- `params`
  Template-rendered inputs to the action.
- `depends_on`
  Control scheduling dependency, not business truth by itself.
- `when`
  Gate branch execution based on inputs or previous node outputs.
- `returns`
  Define the user-facing task result shape.

## `depends_on` vs `output`

This is a common source of bugs.

- `depends_on`
  Means "run after this node reaches an allowed terminal state."
- `output`
  Means the business value returned by that node.

A node can be:
- `run_state.status = SUCCESS`
- but `output = false`

This happens often with actions like `find_text_and_click`.

So when deciding whether a downstream node should run:
- use `depends_on` for graph order
- use `when` or an explicit assert when the branch depends on the previous node's business result

## `aura.run_task`

Use `aura.run_task` to compose larger flows from smaller tasks.

When using it:
- pass only the inputs the child task actually needs
- keep task boundaries meaningful
- inspect nested failures from child back to parent

Representative nested orchestration:
- `auto_battle_dispatch -> auto_battle_ct_batch -> auto_battle_ct_tie_an_batch -> auto_battle_ct_tie_an_run_one -> auto_battle_combat`

## Loop authoring

When a task uses:

```yaml
loop:
  for_each: "{{ inputs.jobs }}"
  parallelism: 1
```

Be careful with:
- `loop.item.*` only being meaningful inside the looped node context
- template pre-render warnings not always being the real failure
- child task errors being wrapped by the parent loop node

## Practical rules

- Keep click/assert/wait sequencing explicit when UI transitions are fragile.
- Prefer one small task per meaningful business subflow.
- When a change is risky, create a dedicated entry-point task for isolated validation before reconnecting the main chain.
- Keep `returns` small and meaningful; do not dump every internal node output into the public task contract.

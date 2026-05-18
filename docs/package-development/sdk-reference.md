# Extension SDK Reference

Aura V6 exposes stable SDK context objects for action authors:

```python
from packages.aura_core.sdk import ActionContext, EvidenceWriter, PolicyContext
```

## Injection

Use type annotations for `EvidenceWriter` and `PolicyContext`. Use either the `ActionContext` annotation or the parameter name `action_context` for full context injection.

```python
@action_info(name="inspect_state", read_only=True)
def inspect_state(action_context: ActionContext, evidence: EvidenceWriter) -> dict:
    evidence.add_ref(kind="note", payload={"stage": "inspect"})
    return {"cid": action_context.cid}
```

Legacy `context` and `engine` injection still works for compatibility, but new stable actions should prefer the SDK types.

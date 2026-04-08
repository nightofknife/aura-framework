# Service Authoring

Use services for shared capabilities that should live longer than one action call.

Representative example:
- `plans/resonance/src/services/resonance_market_data_service.py`

## Use a service when

- multiple actions need the same capability
- state or cache should be shared
- a remote integration should be wrapped once
- setup cost is high enough that singleton reuse matters

Typical examples:
- OCR provider access
- cached market data
- process management
- navigation/session abstractions

## Prefer an action instead when

- the behavior is one immediate operation
- state does not need to persist across calls
- orchestration would still live in YAML

## Service shape

Typical custom service structure:

```python
from packages.aura_core.api import service_info

@service_info(
    alias="resonance_market_data",
    public=True,
    singleton=True,
    description="..."
)
class ResonanceMarketDataService:
    ...
```

## Singleton and public

- `singleton=True`
  Use when shared state, cache, or expensive setup should be reused.
- `public=True`
  Use when tasks/actions may request the service through runtime injection.

## Registration rule

Like actions, services must also be exported through `manifest.yaml`.

If the class exists but the manifest export is missing:
- the service will not be registered
- `@requires_services` users will fail at runtime

## Design guidance

- Keep service methods domain-oriented, not UI-flow-oriented.
- Keep task sequencing out of services.
- Let actions adapt task inputs to service calls.
- Keep constructor setup deterministic and safe for repeated runtime startup.

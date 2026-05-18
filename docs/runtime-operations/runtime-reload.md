# Runtime Reload

Aura V6 exposes runtime reload as a controlled operation instead of a direct file watcher side effect.

## API

- `GET /api/v1/runtime/reload/status`
- `POST /api/v1/runtime/reload/plan`
- `POST /api/v1/runtime/reload/apply`
- `POST /api/v1/workspace/packages/{package_id}/reload`

`apply` fails when affected runs are active unless `drain` is set. Runtime reload and package reload are local administration operations and are protected by the hot reload admin feature flag.

## Behavior

- Default mode is fail-fast.
- Drain mode pauses new dequeue work during reload and waits for active runs to finish.
- V6 package reload uses a safe full registry refresh with package-scoped planning metadata.
- Reload results are recorded in SQLite `reload_operations`; successful reloads also write `runtime_generations`.

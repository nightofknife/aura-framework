# Queue Recovery

Aura V6 persists the main task queue to `logs/aura.sqlite3`.

## Queue States

- `ready`: waiting for a worker lease.
- `delayed`: waiting for its delay time.
- `leased`: claimed by a worker and not yet acknowledged.
- `completed`: acknowledged after execution handoff completes.
- `dropped`: removed or cleared before execution.
- `abandoned`: stale and no longer recoverable.

## API

- `GET /api/v1/queue/recovery/status`
- `POST /api/v1/queue/recovery/recover`
- `POST /api/v1/queue/recovery/abandon-stale`

V6 restores ready and delayed main queue rows on startup. Expired leases are either recovered to ready or marked abandoned depending on attempts.

# Aura GUI Redesign Design

Status: draft  
Last updated: 2026-05-13

This document records the agreed GUI redesign direction. Future GUI layout, API, field, and visual-style changes should be summarized here before implementation.

## Goals

- Reduce noisy data on primary pages.
- Align the GUI with the new API contract through a stable frontend API layer.
- Rework page layout around the main user workflow.
- Replace the current heavy industrial visual style with a calmer desktop tool style.
- Keep advanced diagnostics available without making them the default experience.

## Proposed Navigation

Use five primary entries:

1. Execute
2. Task Library
3. Runs
4. Capabilities
5. Settings

`Observability` should no longer be a first-level page by default. Its data should move into run details and advanced diagnostics under Settings.

Current experimental or legacy pages such as `DashboardView`, `ActionsView`, `ServicesView`, and `AutomationView` should remain outside default navigation unless explicitly promoted later.

## Page Layout Design

### Execute

Purpose: choose a task, configure inputs, submit execution, and see immediate state.

Layout:

```text
+------------------------------------------------+
| Top status: backend / scheduler / workspace     |
+---------------+----------------+---------------+
| Task picker   | Input config   | Execution state|
| Plan filter   | Form fields    | Active runs    |
| Task search   | Validation     | Recent results |
| Task list     | Execute button | Error summary  |
+---------------+----------------+---------------+
```

Keep this page focused on the primary execution flow. Do not expose full queue management here by default.

Primary APIs:

- `GET /plans`
- `GET /plans/{plan}/tasks`
- `POST /tasks/dispatch`
- `GET /runs/active`
- `GET /runs/history`

### Task Library

Purpose: browse task definitions, understand inputs and steps, and run lightweight validation.

Layout:

```text
+--------------------------------------+
| Top: plan search / refresh / validate |
+--------------+-----------------------+
| Plan/Task tree| Task detail            |
|              | Overview tab           |
|              | Inputs tab             |
|              | Steps tab              |
|              | Validate/Dry-run tab   |
+--------------+-----------------------+
```

Primary APIs:

- `GET /plans`
- `GET /plans/{plan}/tasks`
- `GET /plans/{plan}/task-load-errors`
- `GET /actions`
- `POST /tasks/validate`
- `POST /tasks/dry-run`

### Runs

Purpose: inspect active and historical runs, identify failures, and open details.

Layout:

```text
+--------------------------------------+
| Filters: status / plan / time / text  |
+-------------------+------------------+
| Run list/table    | Run detail drawer |
| Task              | Overview          |
| Plan              | Timeline          |
| Status            | Action results    |
| Time/duration     | Evidence/debug    |
+-------------------+------------------+
```

Primary APIs:

- `GET /runs/active`
- `GET /runs/history`
- `GET /runs/{cid}`
- `GET /runs/{cid}/evidence/manifest`
- `GET /runs/{cid}/locators`
- `GET /runs/{cid}/debug-report`

### Capabilities

Purpose: show whether desktop capability backends are available and why not.

Layout:

```text
+--------------------------------------+
| Top: self-check / refresh             |
+--------------------------------------+
| Domain summary cards                  |
| capture / mouse / keyboard / ocr / window |
+--------------------------------------+
| Backend detail table                  |
+--------------------------------------+
```

Primary APIs:

- `GET /capabilities`
- `GET /capabilities/{domain}`
- `POST /capabilities/self-check`

### Settings

Purpose: show base configuration clearly and keep risky operations in advanced sections.

Layout:

```text
+--------------------------------------+
| Basic settings                        |
| API / Workspace / Profile             |
+--------------------------------------+
| Runtime                               |
| Scheduler / Reload / Migration        |
+--------------------------------------+
| Package management                    |
| packages / enable / disable / lock    |
+--------------------------------------+
| Advanced diagnostics                  |
| Policy / Diagnostics / Queue recovery |
+--------------------------------------+
```

Primary APIs:

- `GET /system/health`
- `GET /workspace`
- `GET /workspace/packages`
- `POST /workspace/packages/lock`
- `POST /workspace/packages/{id}/enable`
- `POST /workspace/packages/{id}/disable`
- `GET /policy`
- `GET /diagnostics/recent`
- `GET /runtime/reload/status`
- `POST /runtime/reload/apply`
- `GET /migrations/status`
- `POST /migrations/apply`

## Field Retention Plan

Fields marked as hidden are still available in details, drawers, tabs, advanced sections, or debug raw JSON. Fields marked as removed are removed from the main UI, not necessarily from API contracts.

### Execute

Retain:

| Area | Fields |
| --- | --- |
| Top status | `backend status`, `scheduler is_running`, `workspace/profile` |
| Task picker | `plan_name`, `task_ref`, `meta.title`, `meta.description`, `meta.inputs`, `meta.entry_point`, `meta.concurrency` |
| Input form | `input.name`, `input.label`, `input.type`, `input.required`, `input.default`, `input.allowed`, `input.min`, `input.max` |
| Dispatch feedback | `cid`, `status`, `message`, `trace_label` |
| Active runs | `plan_name`, `task_ref`, `status`, `started_at`, `duration_ms`, `error` |
| Recent results | `plan_name`, `task_ref`, `status`, `finished_at`, `duration_ms`, `error` |

Hide by default:

| Field | Handling |
| --- | --- |
| `full_task_id` | Detail drawer |
| `task_name_in_plan` | Prefer `task_ref` in normal UI |
| `trace_id` | Run detail |
| `definition.steps` | Task Library |
| `queue.ready_length`, `queue.delayed_length`, `avg_wait_sec` | Advanced queue status |
| `enqueued_at`, `source` | Queue detail |

Remove or downgrade:

| Field or module | Reason |
| --- | --- |
| Complex local staging queue status | Avoid a second queue concept in the primary workflow |
| `guiStatusLabel`, `lastCid`, `pushedAt` | Can be represented by dispatch/run state |
| Large queue management controls | Move to advanced diagnostics |

### Task Library

Retain:

| Area | Fields |
| --- | --- |
| Plan list | `name`, `task_count`, `task_error_count` |
| Task list | `task_ref`, `meta.title`, `meta.description`, `meta.entry_point`, `meta.concurrency` |
| Overview | `plan_name`, `task_ref`, `full_task_id`, `meta.title`, `meta.description` |
| Inputs | `meta.inputs[].name`, `label`, `type`, `required`, `default`, `allowed`, `min`, `max` |
| Steps | `definition.steps.{id}.action`, `params`, `depends_on`, `retry`, `loop` |
| Validation | `status`, `errors`, `warnings`, `dry_run` |

Hide by default:

| Field | Handling |
| --- | --- |
| Full `definition` JSON | Raw definition collapsible section |
| Full `action.parameters` schema | Step detail expansion |
| Raw `task-load-errors` object | Summary first, raw details on expand |
| `full_task_id` | Small overview detail, not list column |

Remove or downgrade:

| Field or module | Reason |
| --- | --- |
| Same-screen graph, action schema, inputs, and errors | Move into tabs to reduce overload |
| `task_name_in_plan` in list | Less useful than `task_ref` or title |
| All steps expanded by default | Long tasks become unreadable |

### Runs

Retain:

| Area | Fields |
| --- | --- |
| List | `status`, `plan_name`, `task_ref`, `trace_label`, `started_at`, `finished_at`, `duration_ms`, `error` |
| Detail overview | `cid`, `trace_id`, `trace_label`, `plan_name`, `task_ref`, `status`, `started_at`, `finished_at`, `duration_ms`, `error` |
| Timeline | `nodes[].id`, `action`, `status`, `started_at`, `finished_at`, `duration_ms`, `error` |
| Action results | `action_results[].node_id`, `action`, `backend`, `status`, `duration_ms`, `error` |
| Evidence | `evidence`, `evidence manifest` |
| Debug | `debug-report`, `locators` |

Hide by default:

| Field | Handling |
| --- | --- |
| `cid` | Short code in list, full value in detail |
| `trace_id` | Detail only |
| `user_data` | Detail tab |
| `framework_data` | Detail tab |
| `policy_decisions` | Debug or policy tab |
| `locators` | Debug tab |
| Raw `evidence manifest` JSON | Evidence tab collapsible section |

Remove or downgrade:

| Field or module | Reason |
| --- | --- |
| Many IDs directly in list | Reduces scan efficiency |
| Full error object in list | Use error summary plus detail |
| `queued` as core history statistic | Avoid mixing queue state with run lifecycle if new API changes this model |

### Capabilities

Retain:

| Area | Fields |
| --- | --- |
| Domain summary | `domain`, available count, total count |
| Backend detail | `backend_id`, `domain`, `available`, `health_status`, `limitations`, `last_error` |
| Constraints | `requires_foreground`, `supports_background`, `supports_minimized`, `requires_admin` |
| Risk | `side_effect_level`, `stability`, `capabilities` |

Hide by default:

| Field | Handling |
| --- | --- |
| Full `capabilities[]` | Backend detail expansion |
| Long `limitations[]` | Show first item or summary by default |
| `last_error` | Show only when unavailable or expanded |
| `side_effect_level` | Detail or advanced column |

Remove or downgrade:

| Field or module | Reason |
| --- | --- |
| Flat display of every raw backend field | Capability page should answer availability first |
| Raw self-check JSON | Show in self-check result detail only |

### Settings

Retain:

| Area | Fields |
| --- | --- |
| Basic | `api.base_url`, `api.timeout_ms`, `ws.base_url`, `workspace.name`, `workspace.profile` |
| System state | `system.status`, `is_running`, `scheduler_initialized`, `ready` |
| Workspace | `workspace`, `lock`, `doctor.status`, `doctor.errors`, `doctor.warnings` |
| Packages | `id`, `version`, `enabled`, `source`, `validation_status`, `lock_drift` |
| Policy | `profile`, effective allow/deny summary |
| Runtime reload | `status`, `reload_id`, `blocked_by`, `message` |
| Migrations | `status`, `run_store_schema_version`, `legacy_db_exists`, `pending` |
| Diagnostics | recent `id`, `created_at`, `status` |

Hide by default:

| Field | Handling |
| --- | --- |
| Full `workspace.lock` | Advanced detail |
| Full `doctor` output | Problem summary plus expansion |
| Package permissions | Package detail expansion |
| Migration plan/apply raw result | Advanced section |
| Runtime reload raw result | Advanced section |
| Diagnostics bundle detail | Detail modal or page |

Remove or downgrade:

| Field or module | Reason |
| --- | --- |
| Theme explanation copy | Settings should not explain visual style |
| Local storage key display | Debug-only information |
| `status_poll_ms`, `queue_list_limit`, `dispatch_timeout_ms` | Move to developer/debug mode |
| Always-visible migration/reload apply buttons | Risky operations require advanced section and confirmation |

## Field Layering Rule

All GUI data should be classified into one of three layers:

| Layer | Meaning |
| --- | --- |
| Summary | Names, state, time, result, and concise error summary. Shown in lists and primary panels. |
| Detail | IDs, inputs, outputs, steps, evidence, and backend details. Shown in drawers, tabs, or detail panels. |
| Debug | Raw JSON, trace internals, policy decisions, framework data, diagnostics. Shown only in advanced/debug areas. |

## Page Data Cleanup Plan

Code audit date: 2026-05-13. This plan maps current page data noise to concrete cleanup actions. It describes what to remove from the default UI, what to move into detail/advanced surfaces, and what state/API calls should disappear from the redesigned primary pages.

### Cleanup Principles

- Primary pages should not show implementation internals unless they answer the user's immediate question.
- One page should have one main job.
- Queue, run, trace, evidence, and diagnostics are separate layers; do not mix them in the same primary panel.
- Keep raw IDs and raw JSON available, but only in details or debug sections.
- Remove local-only state that duplicates backend state unless it is required for unsent draft work.
- Prefer normalized view models over page-local field reshaping.

### Execute Cleanup

Current page: `aura_gui/src/pages/ExecuteView.vue`

Current noisy areas:

- Header stat strip: `catalog`, `staged`, `queue`, `live`.
- Three heavy panels: catalog, local staging desk, backend queue/live rail.
- Local GUI queue via `useGuiQueue()`.
- Ready queue management: delete, clear, move-to-front.
- Runtime queue summary: ready/running/delayed.
- Local favorites in `localStorage`.
- Repeated mission/route/desk wording.

Target default screen:

- Task picker.
- Input form for selected task.
- Execute button and last dispatch feedback.
- Compact active/recent runs panel.

Remove from default UI:

| Current element | Cleanup action |
| --- | --- |
| `desk-header__stats` with catalog/staged/queue/live | Replace with compact global status in header. |
| Local staging desk route | Remove from first redesign. Execute one configured task at a time. |
| `guiItems`, `addGui`, `updateGui`, `removeGuiItem`, `clearGuiItems`, `moveGuiItem` | Remove from Execute page state unless batch staging is reintroduced later. |
| `stage-note`, route board numbering, raise/lower buttons | Remove. |
| Backend ready queue tickets | Move to Settings > Advanced diagnostics or a future Queue panel. |
| `DELETE /queue/{cid}`, `POST /queue/{cid}/move-to-front`, `DELETE /queue/clear` calls | Remove from Execute page. Keep in `advanced.js`. |
| `queueOverview.ready_count/running_count/delayed_count` display | Remove from Execute; only active runs and recent runs remain. |
| Favorite task stars | Defer. Reintroduce only if user workflow proves it is needed. |

Keep in Execute:

| Data | Source |
| --- | --- |
| Plans | `GET /plans` |
| Tasks for selected plan | `GET /plans/{plan_name}/tasks` |
| Selected task inputs | task `meta.inputs` |
| Dispatch result | `POST /tasks/dispatch` |
| Backend/scheduler state | `GET /system/health` or `GET /system/status` |
| Active runs | `GET /runs/active` |
| Recent runs | `GET /runs/history?limit=5` |

Move to detail:

| Data | Destination |
| --- | --- |
| `cid`, `trace_id`, raw dispatch payload | Run detail drawer or debug copy action. |
| Full task definition | Task Library. |
| Queue source/enqueue metadata | Advanced diagnostics. |

### Task Library Cleanup

Current page: `aura_gui/src/pages/PlansView.vue`

Current noisy areas:

- Plan index, task strip, and dossier all shown at once.
- Inputs, step preview, task graph, action parameter schema, validate result, dry-run result, and load errors can all appear in one long surface.
- `actionSchemaRows` joins action catalog into every step view.
- Full validation/dry-run JSON is shown inline.

Target default screen:

- Left plan/task tree.
- Right task detail with tabs: Overview, Inputs, Steps, Validation.

Remove from default UI:

| Current element | Cleanup action |
| --- | --- |
| `Step Preview` and `Task Graph` as separate simultaneous blocks | Merge into one `Steps` tab. |
| `Action Parameter Schema` always visible | Move into per-step expansion. |
| Full validation/dry-run JSON inline | Show summary first; raw JSON behind "Raw result". |
| Load error raw rows inline | Show count and concise message; raw object in expansion. |
| `taskGraphRows` visible together with step preview | Keep only one normalized step representation. |

Keep:

| Data | Source |
| --- | --- |
| Plan list and task counts | `GET /plans` |
| Task list for selected plan | `GET /plans/{plan_name}/tasks` |
| Load error summary | `GET /plans/{plan_name}/task-load-errors` |
| Task inputs | task `meta.inputs` |
| Task steps | task `definition.steps` |
| Validate/dry-run summaries | `POST /tasks/validate`, `POST /tasks/dry-run` |

Move to detail:

| Data | Destination |
| --- | --- |
| Full task definition | Raw definition collapsible block. |
| Full action parameter schemas | Step detail drawer/expansion. |
| Full validation/dry-run response | Raw result expansion. |
| `full_task_id` | Overview metadata, not list. |

### Runs Cleanup

Current page: `aura_gui/src/pages/RunsView.vue`

Current noisy areas:

- Header repeats active/queued/success/failed stats.
- Side rail repeats status split.
- `queuedCount` is computed from merged runs and can blur queue vs run lifecycle.
- Run list and side copy compete with detail drawer.

Target default screen:

- Filter toolbar.
- Runs table/list.
- Detail drawer.

Remove from default UI:

| Current element | Cleanup action |
| --- | --- |
| Large `runs-header__stats` | Replace with small inline summary or remove entirely. |
| `runs-wall__rail` status split | Remove; filters already provide status visibility. |
| `runs-wall__copy` explanatory text | Remove. |
| `queuedCount` as a top-level run statistic | Remove unless the new API models queued as run lifecycle. |
| Repeated status counts in multiple places | Keep at most one compact summary. |

Keep:

| Data | Source |
| --- | --- |
| Active runs | `GET /runs/active` |
| Historical runs | `GET /runs/history` |
| Status/plan/query filters | Client-side initially |
| Run detail | `GET /runs/{cid}` |
| Debug detail | `GET /runs/{cid}/debug-report`, `GET /runs/{cid}/locators`, `GET /runs/{cid}/evidence/manifest` |

Move to detail:

| Data | Destination |
| --- | --- |
| `cid`, `trace_id`, raw run payload | Detail drawer. |
| `user_data`, `framework_data`, `policy_decisions` | Detail tabs. |
| Evidence manifest and locators | Evidence/debug tabs. |

### Capabilities Cleanup

Current page: `aura_gui/src/pages/CapabilitiesView.vue`

Current noisy areas:

- Mostly acceptable, but backend rows are grouped only by domain and do not provide a compact summary-first matrix.
- Limitations can become long text in rows.

Target default screen:

- Domain summary cards.
- Backend table filtered by domain.
- Self-check action and result summary.

Remove from default UI:

| Current element | Cleanup action |
| --- | --- |
| Long limitations text in each row | Show first limitation or count; full list in expansion. |
| All backend details shown equally | Prioritize `available`, `health_status`, `last_error` when unavailable. |

Keep:

| Data | Source |
| --- | --- |
| Domain list and availability counts | `GET /capabilities` |
| Backend health | `GET /capabilities` |
| Self-check | `POST /capabilities/self-check` |

Move to detail:

| Data | Destination |
| --- | --- |
| Full limitations array | Backend detail expansion. |
| `capabilities[]`, `side_effect_level`, `stability` | Advanced columns/detail. |
| Raw self-check response | Self-check detail drawer. |

### Settings Cleanup

Current page: `aura_gui/src/pages/SettingsView.vue`

Current noisy areas:

- Transport internals: status poll, queue limit, dispatch timeout.
- Workspace, policy, diagnostics, runtime reload, migrations, capabilities, theme explanation, and local storage keys all appear at the same level.
- Runtime reload and migration apply buttons are always visible.
- Theme lock copy describes visual style in the app.
- Local storage keys are user-visible.

Target default screen:

- Basic system/workspace state.
- Packages summary and management.
- Collapsed advanced sections for reload, migrations, policy, diagnostics, queue recovery.

Remove from default UI:

| Current element | Cleanup action |
| --- | --- |
| `Status Poll`, `Queue Limit`, `Dispatch Timeout` | Move to developer/debug section. |
| `Theme Lock` card | Remove. Visual style should not be described in UI. |
| `Local Keys` card | Move to debug-only section or remove. |
| Always-visible runtime reload apply button | Move to Advanced Runtime with confirmation. |
| Always-visible migration apply button | Move to Advanced Persistence with confirmation. |
| Capabilities summary duplicated from Capabilities page | Keep only compact health summary or remove. |

Keep:

| Data | Source |
| --- | --- |
| Backend/scheduler status | `GET /system/health` |
| API base URL | config |
| Workspace profile/name | `GET /workspace` |
| Package list | `GET /workspace/packages` |
| Package enable/disable/lock | workspace package APIs |
| Policy profile | `GET /policy` |
| Diagnostics recent summary | `GET /diagnostics/recent` |
| Runtime reload status | `GET /runtime/reload/status` |
| Migration status | `GET /migrations/status` |

Move to advanced:

| Data/action | Destination |
| --- | --- |
| Runtime reload plan/apply | Advanced Runtime. |
| Migration plan/apply | Advanced Persistence. |
| Queue recovery | Advanced Diagnostics. |
| Policy effective | Advanced Policy. |
| Diagnostics collect/detail | Advanced Diagnostics. |
| Package upgrade/rollback/reload | Package detail advanced actions. |

### Observability Cleanup

Current page: `aura_gui/src/pages/ObservabilityView.vue`

Decision: remove as default first-level navigation.

Current data to redistribute:

| Current observability data | New destination |
| --- | --- |
| Error summary | Settings > Advanced Diagnostics summary. |
| Error drilldown | Settings > Advanced Diagnostics drawer. |
| Backend/action/service/desktop metrics | Settings > Advanced Diagnostics or future Operations page. |
| Resource samples | Run detail debug tab or Advanced Diagnostics. |
| Recent traces | Runs page and run detail. |
| Queue recovery | Settings > Advanced Diagnostics. |

Remove from default UI:

| Current element | Cleanup action |
| --- | --- |
| First-level Observability nav item | Remove from default navigation. |
| Multi-panel metrics grid | Replace with targeted advanced sections. |
| Always-loaded observability API fanout | Do not fetch unless advanced diagnostics is opened. |

### Package Pages Cleanup

Current default page: `WorkspacePackagesView.vue`  
Legacy/unsafe page: `PackagesView.vue`

Decision:

- Keep workspace package lifecycle as part of Settings.
- Do not promote `PackagesView.vue`; it calls backend routes that do not exist in current code.

Remove from default UI:

| Current element | Cleanup action |
| --- | --- |
| Top-level Packages nav item | Fold into Settings unless package work becomes a main workflow. |
| Upgrade panel on first screen | Move into package detail advanced action. |
| Apply upgrade button always visible when `local_admin` | Require advanced section and confirmation. |
| Legacy package manifest/dependency editor | Remove from redesigned default app. |

Keep:

| Data | Source |
| --- | --- |
| Package id/version/enabled/source/validation/lock drift | `GET /workspace/packages` |
| Enable/disable | `POST /workspace/packages/{package_id}/enable`, `POST /workspace/packages/{package_id}/disable` |
| Write lock | `POST /workspace/packages/lock` |

Move to advanced:

| Data/action | Destination |
| --- | --- |
| Upgrade plan/apply | Package detail advanced. |
| Rollback | Package detail advanced. |
| Reload package | Package detail advanced. |
| Permissions/migrations | Package detail tabs. |

### State And Composable Cleanup

Current duplicated or stale state modules:

| Module | Current issue | Cleanup plan |
| --- | --- | --- |
| `useGuiQueue.js` | Creates local staging queue separate from backend run state. | Remove from first redesigned Execute page. |
| `useStagingQueue.js` | Larger staging system not used by default navigation. | Keep only if future batch execution is designed. |
| `useStagingRunner.js` | Couples local staging with dispatch and queue polling. | Do not use in redesigned primary pages. |
| `useBackendQueue.js` | Queue-specific operations should be advanced-only. | Move behind `advanced.js`. |
| `useQueueStore.js` | Duplicates queue state. | Replace with API layer and page-local advanced query state. |
| `stores/queue.*` | Uses older store shape. | Remove or replace after API layer migration. |
| `stores/runs.js` | Calls missing `GET /runs`. | Remove or replace with `runsApi`. |
| `useAuraSockets.js` | References websocket routes not present in backend. | Do not use until backend transport exists. |

### Cleanup Implementation Order

1. Add shared API layer and normalizers.
2. Add new shell/theme components.
3. Rewrite Execute without local staging queue and without backend queue controls.
4. Rewrite Task Library into tabbed detail layout.
5. Rewrite Runs as table plus detail drawer, remove repeated stats rail.
6. Rewrite Capabilities as matrix/table with expandable backend details.
7. Merge Workspace Packages and Settings into one Settings page with advanced sections.
8. Remove Observability from default navigation and lazy-load its data only from advanced diagnostics.
9. Remove or quarantine stale pages and composables after no default route imports them.

### Cleanup Acceptance Criteria

- No default page makes API calls to routes that do not exist in backend code.
- Execute page no longer imports `useGuiQueue`.
- Default navigation contains only Execute, Task Library, Runs, Capabilities, Settings.
- Queue mutation APIs are not called by Execute.
- Observability APIs are not fetched on app startup or default page load.
- Settings does not show local storage keys or visual-theme explanation.
- Raw JSON appears only in explicit detail/debug sections.
- High-risk actions require an advanced section and confirmation.

## Frontend API Layer Direction

Code audit date: 2026-05-13. Source of truth for this section is the current code under `backend/api/routes`, `backend/api/schemas.py`, and existing GUI call sites under `aura_gui/src`. The public docs are behind the code in several places.

Before adapting pages to the new API, create a unified frontend API layer instead of keeping page-local `axios.create(...)` calls.

### Current API Inventory From Code

Core routes included by `backend/api/app.py`:

| Group | Code file | Role |
| --- | --- | --- |
| System | `backend/api/routes/system.py` | Health, scheduler lifecycle, metrics, logs, legacy hot reload |
| Execution | `backend/api/routes/execution.py` | Dispatch, batch dispatch, batch status, validate, dry-run |
| Plans | `backend/api/routes/plans.py` | Plan/task listing, task load errors, feature-flagged file editing |
| Queue | `backend/api/routes/queue.py` | Queue overview/list/mutation and recovery |
| Runs | `backend/api/routes/runs.py` | Active/history/detail/evidence/debug |
| Catalog | `backend/api/routes/catalog.py` | Action, service, loaded package catalog |
| Capabilities | `backend/api/routes/capabilities.py` | Desktop backend matrix and self-check |
| Workspace | `backend/api/routes/workspace.py` | Workspace profile and package lifecycle |
| Diagnostics | `backend/api/routes/diagnostics.py` | Diagnostic bundles |
| Policy | `backend/api/routes/policy.py` | Policy profile and effective capability view |
| Observability | `backend/api/routes/observability.py` | Trace, metrics, error, resource, queue analysis queries |
| Migrations | `backend/api/routes/migrations.py` | SQLite migration status/plan/apply |
| Runtime | `backend/api/routes/runtime.py` | Runtime reload status/plan/apply |

Primary redesign routes:

| Page | API calls |
| --- | --- |
| Execute | `GET /system/health`, `GET /system/status`, `GET /plans`, `GET /plans/{plan_name}/tasks`, `POST /tasks/dispatch`, `GET /runs/active`, `GET /runs/history` |
| Task Library | `GET /plans`, `GET /plans/{plan_name}/tasks`, `GET /plans/{plan_name}/task-load-errors`, `GET /actions`, `POST /tasks/validate`, `POST /tasks/dry-run` |
| Runs | `GET /runs/active`, `GET /runs/history`, `GET /runs/{cid}`, `GET /runs/{cid}/evidence/manifest`, `GET /runs/{cid}/locators`, `GET /runs/{cid}/debug-report` |
| Capabilities | `GET /capabilities`, `GET /capabilities/{domain}`, `POST /capabilities/self-check` |
| Settings | `GET /system/health`, `GET /workspace`, `GET /workspace/packages`, `POST /workspace/packages/lock`, `POST /workspace/packages/{package_id}/enable`, `POST /workspace/packages/{package_id}/disable`, `GET /policy`, `GET /diagnostics/recent`, `GET /runtime/reload/status`, `GET /migrations/status` |

Advanced-only routes:

| Area | API calls | Notes |
| --- | --- | --- |
| Queue operations | `GET /queue/overview`, `GET /queue/list`, `POST /queue/reorder`, `DELETE /queue/clear`, `DELETE /queue/{cid}`, `POST /queue/{cid}/move-to-front` | Keep out of the primary Execute screen. |
| Queue recovery | `GET /queue/recovery/status`, `POST /queue/recovery/recover`, `POST /queue/recovery/abandon-stale` | Settings > Advanced diagnostics. |
| Runtime reload | `POST /runtime/reload/plan`, `POST /runtime/reload/apply` | Protected by hot reload admin flag. Needs confirmation UI. |
| Migrations | `POST /migrations/plan`, `POST /migrations/apply` | Protected by hot reload admin flag for POST. Needs confirmation UI. |
| Diagnostics | `GET /diagnostics/{bundle_id}`, `POST /diagnostics/collect` | Advanced diagnostics. |
| Policy | `GET /policy/effective` | Advanced policy detail. |
| Observability | `GET /observability/*` | Move to Runs detail or Settings > Diagnostics, not first-level navigation. |
| Workspace package detail | `GET /workspace/packages/{package_id}/permissions`, `GET /workspace/packages/{package_id}/migrations`, `POST /workspace/packages/{package_id}/upgrade-plan`, `POST /workspace/packages/{package_id}/upgrade`, `POST /workspace/packages/{package_id}/rollback`, `POST /workspace/packages/{package_id}/reload` | Package detail drawer or advanced package operations. |

Compatibility or feature-flagged routes:

| API calls | Treatment |
| --- | --- |
| `GET /system/ready` | Compatibility alias for health/ready; do not use in new GUI. |
| `GET /system/logs` | Feature-flagged by `AURA_API_ENABLE_LOGS`; advanced diagnostics only. |
| `GET /system/hot_reload/status`, `POST /system/hot_reload/enable`, `POST /system/hot_reload/disable` | Legacy hot reload surface; prefer `/runtime/reload/*` in new GUI. |
| `GET /plans/{plan_name}/files/tree`, `GET /plans/{plan_name}/files/content`, `PUT /plans/{plan_name}/files/content`, `POST /plans/{plan_name}/files/reload`, `DELETE /plans/{plan_name}` | Feature-flagged by `AURA_API_ENABLE_PLAN_EDITING`; exclude from the first redesign unless task editing is explicitly in scope. |
| `GET /run/{cid}/detail` | Legacy run detail shape; prefer `GET /runs/{cid}`. |

Stale or currently unsafe frontend call sites:

| Call site | Problem | Redesign handling |
| --- | --- | --- |
| `ActionsView.vue` uses `GET /actions/{fqid}` | No matching backend route in current code. | Do not promote `ActionsView`. Use `GET /actions` only in Task Library. |
| `PackagesView.vue` uses `/packages/{name}/manifest` and `/packages/{name}/dependencies` | No matching backend routes in current code. | Replace with `/workspace/packages` lifecycle APIs. |
| `ServicesView.vue` uses `/services/{id}` and `/services/{id}/status` | No matching backend routes in current code. | Do not promote `ServicesView`; keep service catalog read-only through `GET /services` if needed. |
| `stores/runs.js` uses `GET /runs` | No matching backend route in current code. | Replace with `GET /runs/active` and `GET /runs/history`. |
| `useAuraSockets.js` expects `/ws/v1/events` and `/ws/logs` | No backend websocket routes found under `backend`. | Treat realtime as unavailable until the new API explicitly provides WebSocket/SSE. Use polling in v1 of the redesign. |
| Plan file editing APIs | Feature-flagged and security-sensitive. | Keep behind explicit advanced/task-authoring mode, not default Task Library. |

### Proposed API Module Structure

```text
src/api/client.js
src/api/errors.js
src/api/normalizers.js
src/api/system.js
src/api/plans.js
src/api/tasks.js
src/api/runs.js
src/api/capabilities.js
src/api/workspace.js
src/api/settings.js
src/api/diagnostics.js
src/api/advanced.js
```

Module responsibilities:

| Module | Responsibility |
| --- | --- |
| `client.js` | Single axios instance, config loading, timeout handling, base URL handling, request helpers. |
| `errors.js` | Normalize HTTP errors, feature-flag 404s, validation errors, and conflict responses. |
| `normalizers.js` | Convert backend payloads into view models. All page components consume normalized shapes. |
| `system.js` | Health/status/start/stop/metrics. Primary GUI should only need health/status. |
| `plans.js` | Plan list, task list, task load errors, action catalog for task inspection. |
| `tasks.js` | Dispatch, batch dispatch, batch status, validate, dry-run. |
| `runs.js` | Active/history/detail/evidence/locators/debug report. |
| `capabilities.js` | Capability matrix and self-check. |
| `workspace.js` | Workspace profile and package lifecycle. |
| `settings.js` | Aggregated settings page loader composed from system/workspace/policy/runtime/migrations. |
| `diagnostics.js` | Diagnostic list/detail/collect and observability drilldown. |
| `advanced.js` | Queue operations, runtime reload, migrations, policy effective, observability metrics. |

Do not expose route details directly to Vue pages. Pages should call use-case shaped functions such as:

```text
executeApi.loadTaskPicker()
executeApi.dispatchTask(planName, taskRef, inputs)
runsApi.loadRunList(filters)
runsApi.loadRunDetail(cid)
capabilitiesApi.loadMatrix()
settingsApi.loadOverview()
```

### View Models

Normalize backend payloads into these page-safe shapes:

```text
SystemViewModel
  status: "ok" | "offline" | "error"
  isRunning: boolean
  schedulerInitialized: boolean
  ready: boolean

PlanViewModel
  name: string
  taskCount: number
  taskErrorCount: number

TaskViewModel
  key: string
  planName: string
  taskRef: string
  title: string
  description: string
  entryPoint: boolean | string | null
  concurrency: string | object | null
  inputs: InputViewModel[]
  steps: StepViewModel[]
  raw: object

DispatchViewModel
  cid: string | null
  traceId: string | null
  traceLabel: string | null
  status: "queued" | "error"
  message: string

RunViewModel
  cid: string
  shortCid: string
  planName: string
  taskRef: string
  title: string
  status: "queued" | "running" | "success" | "failed" | "cancelled" | "unknown"
  startedAtMs: number | null
  finishedAtMs: number | null
  durationMs: number | null
  errorSummary: string | null
  raw: object

CapabilityViewModel
  domain: string
  backendId: string
  available: boolean
  healthStatus: string
  limitations: string[]
  lastError: string | null
  requiresAdmin: boolean
  requiresForeground: boolean
  supportsBackground: boolean
  supportsMinimized: boolean
  stability: string
  sideEffectLevel: string

WorkspacePackageViewModel
  id: string
  version: string
  enabled: boolean
  source: string
  validationStatus: string
  lockDrift: boolean
  raw: object
```

Normalization rules:

- Convert all backend timestamps to millisecond numbers or `null`.
- Normalize status strings to lowercase.
- Keep raw payloads attached only for detail/debug surfaces.
- Use `task_ref` as the task identity shown to users; keep `task_name_in_plan` only as raw/detail data.
- Use `trace_label` for readable labels when available; keep `trace_id` in details.
- Convert unknown/missing arrays to empty arrays.
- Convert backend error objects into concise `errorSummary` strings.

### API Security and Feature Flags

The API security layer matters for GUI design:

- Public routes: `GET /api/v1/system/health`, `GET /api/v1/system/status`.
- Local-only mode allows loopback GUI access without API key.
- Remote mode requires `X-Aura-Api-Key`.
- These are closed by default unless feature flags are enabled:
  - `/api/v1/system/logs`
  - `/api/v1/system/hot_reload/*`
  - `/api/v1/runtime/reload/*`
  - `POST /api/v1/migrations/*`
  - `/api/v1/plans/*/files/*`
  - `DELETE /api/v1/plans/{plan_name}`

The frontend must treat a 404 from feature-flagged routes as "feature unavailable", not as a broken backend.

### Realtime Position

Current frontend has a WebSocket client (`useAuraSockets.js`) for `/ws/v1/events` and `/ws/logs`, but no backend websocket routes were found in `backend`. The first redesigned GUI should use polling:

- Execute: poll health, active runs, recent history.
- Runs: poll active/history while the page is open.
- Capabilities and Settings: refresh on demand.

If the new API adds WebSocket or SSE, introduce it behind a separate transport module and keep page APIs unchanged.

### Open API Contract Questions

- Does the new API still use `/api/v1`?
- Is task execution still `POST /tasks/dispatch`?
- Is task identity still `plan_name + task_ref`?
- Are run statuses still `queued`, `running`, `success`, `failed`, `cancelled`?
- Does queue state remain visible to GUI users, or does the new API expose a run lifecycle only?
- Should real-time updates use WebSocket, SSE, or polling?
- Which observability APIs should remain visible in the redesigned GUI?

## Visual Style Direction

Style audit date: 2026-05-13. Current visual system is concentrated in `aura_gui/src/styles/aetherium-theme.css`, `aura_gui/src/style.css`, and page/component scoped styles. The existing look uses remote Google fonts, Oswald display headings, deep green-gray backgrounds, paper/ember colors, repeated gradients, texture overlays, heavy shadows, uppercase text, and wide letter spacing.

Replace it with a quieter desktop automation workbench style. The UI should feel like a professional local control surface for task execution, not a themed expedition table or marketing dashboard.

### Long-Term Use Review

Human-computer interaction assessment: the proposed five-page layout and workbench visual style are suitable for long-term use only if they stay restrained. The redesign should optimize for repeated task execution, fast scanning, low fatigue, and safe recovery from failures.

What works:

| Decision | Why it helps long-term use |
| --- | --- |
| Five primary pages | Reduces navigation memory load. Users always know whether they are executing, browsing tasks, reviewing runs, checking capabilities, or configuring the system. |
| Execute as default page | Matches the main daily workflow and avoids making users start from dashboards or diagnostics. |
| Runs as table plus detail drawer | Supports fast scanning while keeping investigation one click away. |
| Task Library as tree plus tabs | Keeps task comprehension structured without dumping DSL internals into the main flow. |
| Capabilities as matrix/table | Answers the operational question: "Can this backend work now?" |
| Settings with advanced sections | Keeps dangerous and rare operations out of the normal path. |
| Neutral workbench style | Lowers visual fatigue compared with the current high-contrast themed UI. |

Risks to control:

| Risk | Mitigation |
| --- | --- |
| Too much dark UI over long sessions | Keep contrast moderate, avoid pure black large areas, and add light theme later. |
| Dense tables becoming visually tiring | Use row height around 40-48px, sticky headers, filters, and clear empty/error states. |
| Hiding advanced data too aggressively | Make detail drawers predictable and keep raw/debug data one explicit click away. |
| Execute page becoming too minimal | Always show active/recent run feedback so users know whether work was accepted and what happened. |
| Settings becoming a dumping ground | Group by Basic, Packages, Runtime, Diagnostics. Collapse advanced sections by default. |
| Over-reliance on color status | Pair color with text labels and icons/dots. Do not encode state by color alone. |
| Polling causing visible churn | Refresh quietly; avoid layout shifts when active runs update. |

Required ergonomic refinements:

- Add a persistent global status area showing backend and scheduler state.
- Preserve current selection when refreshing lists.
- Keep filters and search inputs stable; do not reset them after refresh.
- Use deterministic table columns and widths to prevent layout shifts.
- Provide immediate feedback after dispatch: queued/failed message, `cid` in detail, and link/open action for run detail.
- Add confirmation for destructive or high-risk actions: queue clear, package disable, reload apply, migration apply, rollback.
- Ensure keyboard navigation works for primary flows: task search, task select, input form, execute, run detail close.
- Use readable labels and domain terms; avoid decorative copy inside operational pages.
- Provide clear offline states and feature-unavailable states, especially for feature-flagged routes returning 404.

Conclusion:

The layout is directionally right for long-term use, but the first implementation should be deliberately plain. The danger is not that the new UI will be too boring; the danger is reintroducing visual weight and diagnostic data into high-frequency pages. Keep Execute and Runs fast, predictable, and quiet. Put complexity behind drawers, tabs, and advanced sections.

### Visual Principles

- Functional density over decoration.
- Neutral surfaces, clear hierarchy, restrained color.
- Tables, split panes, drawers, tabs, and forms should be first-class UI.
- Status should be readable at a glance without saturated page-wide color.
- The interface should work for repeated daily use.
- Advanced/debug surfaces can be dense; primary surfaces should stay calm.

### Current Style To Remove

Remove or stop extending these patterns:

| Current pattern | Replacement |
| --- | --- |
| `Oswald` display font and large uppercase headings | System font stack, compact headings |
| Remote font import | Local/system fonts only |
| Paper/ember expedition palette | Neutral slate/gray palette with blue accent |
| Page-wide radial gradients and decorative backgrounds | Flat app shell with subtle surface separation |
| Repeating texture gradients | Solid surfaces |
| Heavy inset/plate shadows | 1px borders and light elevation only |
| Large ornamental cards | Panels, tables, split panes, drawers |
| Rotated cards/plates | Stable aligned grid |
| Letter-spaced uppercase everywhere | Normal case, letter spacing `0` |
| Dynamic/contour decorative backgrounds | Disabled by default |
| Concept labels like "Expedition", "Mission", "Route Board" | Product language: task, run, queue, capability, workspace |

### New Visual Identity

Name: Desktop Automation Workbench

Tone:

- Calm
- Technical
- Local-first
- Operational
- Precise

Visual references by behavior, not direct copying:

- Linear-like density and quiet controls
- GitHub-like tables and status badges
- VS Code-like local tool framing
- Vercel-like restraint in spacing and contrast

Do not use:

- Large hero areas
- Decorative orb/blob backgrounds
- Full-page gradients
- Marketing copy blocks
- Oversized display typography

### Color Tokens

Use a neutral palette with one primary accent. Keep both light and dark mode possible, but implement one mode first if needed. The first implementation should default to dark because the current app already assumes dark surfaces.

Dark theme target:

```css
:root {
  --bg-app: #0f1115;
  --bg-sidebar: #11141a;
  --bg-surface: #171a21;
  --bg-surface-2: #1d2129;
  --bg-elevated: #222733;
  --bg-field: #0f131a;

  --border-subtle: #252a34;
  --border-strong: #343b49;

  --text-primary: #eef1f5;
  --text-secondary: #a8b0bd;
  --text-muted: #737d8c;
  --text-disabled: #525b68;

  --accent: #4f8cff;
  --accent-hover: #6da1ff;
  --accent-soft: rgba(79, 140, 255, 0.14);

  --success: #36b37e;
  --success-soft: rgba(54, 179, 126, 0.14);
  --warning: #e2a336;
  --warning-soft: rgba(226, 163, 54, 0.14);
  --danger: #ef5b5b;
  --danger-soft: rgba(239, 91, 91, 0.14);
  --info: #4f8cff;
  --info-soft: rgba(79, 140, 255, 0.14);

  --shadow-elevated: 0 12px 28px rgba(0, 0, 0, 0.28);
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
}
```

Light theme target for later:

```css
[data-theme="light"] {
  --bg-app: #f6f8fb;
  --bg-sidebar: #ffffff;
  --bg-surface: #ffffff;
  --bg-surface-2: #f1f4f8;
  --bg-elevated: #ffffff;
  --bg-field: #ffffff;

  --border-subtle: #d8dee8;
  --border-strong: #c5cedb;

  --text-primary: #17202c;
  --text-secondary: #566173;
  --text-muted: #7a8494;
  --text-disabled: #a3abb8;
}
```

Status mapping:

| Meaning | Token | Usage |
| --- | --- | --- |
| Success / available | `--success` | successful runs, available backends |
| Running / active | `--info` | active runs, scheduler running |
| Queued / waiting / warning | `--warning` | queued work, stale recovery candidates |
| Failed / unavailable | `--danger` | failed runs, unavailable backends |
| Neutral / disabled | `--text-muted` | stopped scheduler, inactive state |

### Typography

Use system fonts:

```css
--font-body: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
--font-mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
```

If Inter is not bundled locally, rely on the rest of the stack. Do not import Google Fonts.

Type scale:

| Role | Size | Weight | Notes |
| --- | --- | --- | --- |
| Page title | 22px | 650 | Normal case |
| Section title | 16px | 650 | Normal case |
| Panel title | 14px | 650 | Normal case |
| Body | 13px | 400 | Default UI text |
| Secondary | 12px | 400 | Metadata and hints |
| Table header | 11px | 600 | May use uppercase, letter spacing `0` |
| Code | 12px | 400 | Mono |

Rules:

- Letter spacing must be `0` except rare short table labels where it remains visually neutral.
- Avoid all-caps labels except compact status badges or table headers.
- Do not use hero-scale headings inside control surfaces.

### Layout Shell

Target shell:

```text
+----------------------------------------------------------+
| App header: page title, global status, refresh/actions    |
+--------------+-------------------------------------------+
| Sidebar nav  | Page content                              |
| compact      | split panes / tables / drawers            |
+--------------+-------------------------------------------+
```

Dimensions:

| Element | Target |
| --- | --- |
| Sidebar width | 220px |
| Header height | 56px |
| Page padding | 20px |
| Panel gap | 12px or 16px |
| Form row height | 36px to 40px |
| Button height | 32px or 36px |
| Table row height | 40px to 48px |

Responsive behavior:

- Desktop-first remains acceptable.
- Minimum width should not require `1280px`; target practical behavior down to `1024px`.
- Split panes may stack below `1100px`.
- Text must truncate or wrap predictably; no overlapping labels.

### Component Style

#### Sidebar

Current `ProSidebar` should be redesigned from brand-heavy to utility navigation:

- Small `Aura` wordmark or product name only.
- No serial numbers, oversized logo text, or explanatory copy.
- Navigation items use icon + label.
- Active item uses accent left rail or soft accent background.
- Footer only shows concise workspace/profile status if useful.

#### Header

Current `ProTopbar` should become a compact command header:

- Left: page title and optional short subtitle.
- Right: backend status, scheduler status, primary action.
- No large plate styling.
- Status badges should be compact.

#### Buttons

Button types:

| Type | Use |
| --- | --- |
| Primary | Main action on page, e.g. Execute, Self Check |
| Secondary | Normal page action, e.g. Refresh |
| Ghost | Toolbar/icon-only actions |
| Danger | Destructive actions, with confirmation for high risk |

Rules:

- Use 6px radius.
- No gradients.
- No uppercase transformation.
- Include icons for common operations once icon library choice is made.
- Disabled state must be clear but still readable.

#### Inputs

Inputs/selects/textareas:

- 36px to 40px high.
- Solid field background.
- 1px border.
- Focus ring uses accent.
- Placeholder uses muted text.
- Validation errors appear below the field and on the border.

#### Cards And Panels

Use panels for page structure and cards only for repeated items.

Panel style:

- 1px border
- `--bg-surface`
- 6px or 8px radius
- No nested card-in-card structures
- No texture overlays

Repeated cards:

- Task list item
- Run list item on narrow layouts
- Capability domain summary

Avoid page sections as decorative cards. Prefer split panes and tables.

#### Tables

Tables are a primary component:

- Sticky header where useful.
- Row hover state.
- Compact row density.
- Empty state inside table body.
- Right-aligned numeric/time columns.
- Status badge column near the left or right edge.

#### Badges

Status badge shape:

- 20px to 24px height
- 4px radius or pill if short
- Soft background using status token
- Optional dot, but no square industrial marker

Labels:

- `Success`, `Running`, `Queued`, `Failed`, `Available`, `Unavailable`
- Chinese labels can be used if the whole UI is localized; avoid mixed decorative English labels.

#### Drawers And Modals

Drawers:

- Right side.
- Width 520px to 720px depending on content.
- Solid elevated surface.
- Header with title and close icon.
- Tabs allowed inside.

Modals:

- Use only for confirmation or focused editing.
- Destructive operations require explicit confirmation copy.

#### Toasts

Toasts should be simple:

- Top-right stack.
- Small status icon.
- Title + one-line message.
- No display font.
- No decorative border colors beyond status accent.

### Page-Specific Art Direction

Execute:

- Three-column workbench.
- Task list and input form should look like a tool, not a mission board.
- Primary action is visually clear but not oversized.

Task Library:

- Explorer-like tree on the left.
- Details area uses tabs and tables.
- Steps are compact rows, expandable for params/retry/loop.

Runs:

- Table-first.
- Detail drawer with timeline.
- Failure information uses calm red accents, not full red panels.

Capabilities:

- Matrix and backend table.
- Domain summaries can be small cards.
- Self-check result appears inline or in drawer.

Settings:

- Sectioned form layout.
- Advanced areas collapsed by default.
- Risky actions grouped and visually separated.

### Motion

Keep motion minimal:

- Hover color transition: 120ms.
- Drawer open/close: 160ms to 200ms.
- Toast enter/leave: 160ms.
- No parallax, tilt, animated background, or decorative canvas animation in default UI.
- Respect `prefers-reduced-motion`.

### Migration Rules

During implementation:

1. Create a new global theme file rather than incrementally mutating `aetherium-theme.css`.
2. Remove the Google font import.
3. Replace token names gradually through compatibility aliases if needed.
4. Disable `DynamicBackground` by default in `config.js`.
5. Rewrite shell components first: sidebar, header, page shell, buttons, inputs, badges, panels, tables, drawers.
6. Then rewrite pages in the agreed order: Execute, Task Library, Runs, Capabilities, Settings.
7. Delete old expedition copy as pages are migrated.

Compatibility aliases can temporarily map old tokens to new tokens:

```css
--text-main: var(--text-primary);
--text-soft: var(--text-secondary);
--text-dim: var(--text-muted);
--bg-panel: var(--bg-surface);
--bg-panel-2: var(--bg-surface-2);
--line: var(--border-subtle);
--paper: var(--text-secondary);
--paper-2: var(--text-primary);
--ember: var(--accent);
--ember-2: var(--accent-hover);
```

## Implementation Notes

- Do not start implementation until the new API contract and visual direction are confirmed.
- First implementation step should be the shared API layer and view models.
- Page rewrites should follow the new navigation order:
  1. Execute
  2. Task Library
  3. Runs
  4. Capabilities
  5. Settings
- Keep advanced diagnostics available, but avoid making them first-screen content.

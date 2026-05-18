export function toMs(value) {
  if (value === undefined || value === null || value === '') return null
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) return null
  return number > 1e12 ? Math.round(number) : Math.round(number * 1000)
}

export function normalizeStatus(value, fallback = 'unknown') {
  const status = String(value || '').trim().toLowerCase()
  if (!status) return fallback
  if (status === 'error') return 'failed'
  if (status === 'starting') return 'running'
  if (['queued', 'running', 'success', 'failed', 'cancelled', 'ok', 'idle'].includes(status)) {
    return status
  }
  return fallback
}

export function summarizeError(value) {
  if (!value) return null
  if (typeof value === 'string') return value
  if (typeof value === 'object') {
    return value.message || value.detail || value.error || value.exception_message || JSON.stringify(value)
  }
  return String(value)
}

export function shortId(value, length = 8) {
  if (!value) return ''
  return String(value).slice(0, length)
}

export function normalizeSystem(payload = {}) {
  const ok = payload?.status === 'ok'
  return {
    status: ok ? 'ok' : 'offline',
    isRunning: !!payload?.is_running,
    schedulerInitialized: !!payload?.scheduler_initialized,
    schedulerRunning: !!payload?.scheduler_running,
    ready: !!payload?.ready,
    raw: payload || {},
  }
}

export function normalizePlan(payload = {}) {
  return {
    name: payload?.name || '',
    taskCount: Number(payload?.task_count || 0),
    taskErrorCount: Number(payload?.task_error_count || 0),
    raw: payload || {},
  }
}

function normalizeDependsOn(value) {
  if (Array.isArray(value)) return value.filter(Boolean)
  if (value && typeof value === 'object') {
    return Object.values(value)
      .flatMap((item) => (Array.isArray(item) ? item : [item]))
      .filter(Boolean)
  }
  return value ? [value] : []
}

export function normalizeStepEntries(definition = {}) {
  const steps = definition?.steps
  if (!steps) return []
  const entries = Array.isArray(steps)
    ? steps.map((step, index) => [step.id || `step_${index + 1}`, step])
    : Object.entries(steps)

  return entries.map(([id, step = {}]) => {
    const rawDepends = step.depends_on ?? step.dependsOn ?? step.needs ?? []
    const dependsOn = normalizeDependsOn(rawDepends)
    return {
      id,
      action: step.action || '',
      params: step.params || {},
      dependsOn,
      retry: step.retry || null,
      loop: step.loop || null,
      raw: step,
    }
  })
}

export function normalizeTask(payload = {}) {
  const meta = payload?.meta || {}
  const taskRef = payload?.task_ref || payload?.task_name_in_plan || ''
  return {
    key: `${payload?.plan_name || ''}::${taskRef}`,
    fullTaskId: payload?.full_task_id || '',
    planName: payload?.plan_name || '',
    taskNameInPlan: payload?.task_name_in_plan || '',
    taskRef,
    title: meta.title || taskRef || '未命名任务',
    description: meta.description || '',
    entryPoint: meta.entry_point ?? null,
    concurrency: meta.concurrency ?? null,
    inputs: Array.isArray(meta.inputs) ? meta.inputs : [],
    defaults: meta.defaults || {},
    steps: normalizeStepEntries(payload?.definition || {}),
    meta,
    definition: payload?.definition || null,
    raw: payload || {},
  }
}

export function normalizeTaskLoadError(payload = {}) {
  return {
    planName: payload?.plan_name || '',
    sourceFile: payload?.source_file || '',
    taskRefs: Array.isArray(payload?.task_refs) ? payload.task_refs : [],
    errorCode: payload?.error_code || '',
    message: payload?.message || '任务加载失败',
    raw: payload || {},
  }
}

export function normalizeAction(payload = {}) {
  return {
    fqid: payload?.fqid || '',
    name: payload?.name || '',
    description: payload?.description || '',
    parameters: Array.isArray(payload?.parameters) ? payload.parameters : [],
    capabilities: Array.isArray(payload?.capabilities) ? payload.capabilities : [],
    stability: payload?.stability || 'stable',
    sideEffectLevel: payload?.side_effect_level || 'read',
    raw: payload || {},
  }
}

export function normalizeDispatch(payload = {}) {
  return {
    cid: payload?.cid || null,
    traceId: payload?.trace_id || null,
    traceLabel: payload?.trace_label || null,
    status: normalizeStatus(payload?.status, 'queued'),
    message: payload?.message || '',
    raw: payload || {},
  }
}

export function normalizeRun(payload = {}) {
  const startedAtMs = toMs(payload?.started_at ?? payload?.startedAt)
  const finishedAtMs = toMs(payload?.finished_at ?? payload?.finishedAt)
  const durationMs = payload?.duration_ms ?? payload?.elapsed ?? (
    startedAtMs && finishedAtMs ? Math.max(finishedAtMs - startedAtMs, 0) : null
  )
  const taskRef = payload?.task_ref || payload?.task_name || payload?.task || ''
  const cid = payload?.cid || payload?.id || ''
  return {
    key: cid || `${payload?.plan_name || 'plan'}::${taskRef}::${startedAtMs || 0}`,
    cid,
    shortCid: shortId(cid) || '--------',
    traceId: payload?.trace_id || null,
    traceLabel: payload?.trace_label || '',
    planName: payload?.plan_name || '',
    taskRef,
    title: payload?.trace_label || taskRef || payload?.plan_name || '运行记录',
    status: normalizeStatus(payload?.status),
    startedAtMs,
    finishedAtMs,
    durationMs: durationMs == null ? null : Number(durationMs),
    errorSummary: summarizeError(payload?.error),
    nodes: Array.isArray(payload?.nodes) ? payload.nodes : [],
    actionResults: Array.isArray(payload?.action_results) ? payload.action_results : [],
    policyDecisions: Array.isArray(payload?.policy_decisions) ? payload.policy_decisions : [],
    evidence: Array.isArray(payload?.evidence) ? payload.evidence : [],
    userData: payload?.user_data,
    frameworkData: payload?.framework_data,
    raw: payload || {},
  }
}

export function normalizeCapability(payload = {}) {
  return {
    domain: payload?.domain || '',
    backendId: payload?.backend_id || '',
    available: !!payload?.available,
    healthStatus: payload?.health_status || 'unknown',
    limitations: Array.isArray(payload?.limitations) ? payload.limitations : [],
    lastError: payload?.last_error || null,
    requiresAdmin: !!payload?.requires_admin,
    requiresForeground: !!payload?.requires_foreground,
    supportsBackground: !!payload?.supports_background,
    supportsMinimized: !!payload?.supports_minimized,
    stability: payload?.stability || 'stable',
    sideEffectLevel: payload?.side_effect_level || 'read',
    capabilities: Array.isArray(payload?.capabilities) ? payload.capabilities : [],
    raw: payload || {},
  }
}

export function normalizeWorkspacePackage(payload = {}) {
  return {
    id: payload?.id || payload?.canonical_id || payload?.name || '',
    version: payload?.version || '',
    enabled: !!payload?.enabled,
    source: payload?.source || payload?.path || '',
    validationStatus: payload?.validation_status || payload?.status || 'unknown',
    lockDrift: !!payload?.lock_drift,
    raw: payload || {},
  }
}

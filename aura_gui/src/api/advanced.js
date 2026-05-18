import { api } from './client.js'

export async function getQueueRecoveryStatus() {
  return api.get('/queue/recovery/status')
}

export async function recoverQueue() {
  return api.post('/queue/recovery/recover')
}

export async function abandonStaleQueue() {
  return api.post('/queue/recovery/abandon-stale')
}

export async function getReloadStatus() {
  return api.get('/runtime/reload/status')
}

export async function planReload(payload = {}) {
  return api.post('/runtime/reload/plan', payload)
}

export async function applyReload(payload = { drain: false }) {
  return api.post('/runtime/reload/apply', payload)
}

export async function getMigrationStatus() {
  return api.get('/migrations/status')
}

export async function planMigrations() {
  return api.post('/migrations/plan')
}

export async function applyMigrations() {
  return api.post('/migrations/apply')
}

export async function getPolicy() {
  return api.get('/policy')
}

export async function getEffectivePolicy() {
  return api.get('/policy/effective')
}

export async function listDiagnostics() {
  return api.get('/diagnostics/recent')
}

export async function collectDiagnostics() {
  return api.post('/diagnostics/collect')
}

export async function getDiagnostic(bundleId) {
  return api.get(`/diagnostics/${encodeURIComponent(bundleId)}`)
}

export async function getObservabilitySummary() {
  const [errors, traces, queue] = await Promise.all([
    api.get('/observability/errors/summary').catch(() => ({ counts: {} })),
    api.get('/observability/traces').catch(() => ({ traces: [] })),
    api.get('/queue/recovery/status').catch(() => ({ items: [] })),
  ])
  return { errors, traces, queue }
}

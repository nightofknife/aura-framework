import { api } from './client.js'
import { normalizeRun } from './normalizers.js'

export async function listActiveRuns() {
  const data = await api.get('/runs/active')
  return Array.isArray(data) ? data.map(normalizeRun) : []
}

export async function listRunHistory(params = {}) {
  const data = await api.get('/runs/history', { params })
  const rows = Array.isArray(data?.runs) ? data.runs : []
  return rows.map(normalizeRun)
}

export async function getRunDetail(cid) {
  return normalizeRun(await api.get(`/runs/${encodeURIComponent(cid)}`))
}

export async function getRunDebugArtifacts(cid) {
  const encoded = encodeURIComponent(cid)
  const [debugReport, locators, evidenceManifest] = await Promise.all([
    api.get(`/runs/${encoded}/debug-report`).catch(() => null),
    api.get(`/runs/${encoded}/locators`).catch(() => ({ locators: [] })),
    api.get(`/runs/${encoded}/evidence/manifest`).catch(() => null),
  ])

  return {
    debugReport,
    locators: Array.isArray(locators?.locators) ? locators.locators : [],
    evidenceManifest,
  }
}

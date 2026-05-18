import { api } from './client.js'
import { normalizeCapability } from './normalizers.js'

export async function listCapabilities() {
  const data = await api.get('/capabilities')
  const domains = data?.domains || {}
  const rows = Object.entries(domains).flatMap(([domain, items]) =>
    (Array.isArray(items) ? items : []).map((item) => normalizeCapability({ ...item, domain: item.domain || domain }))
  )
  return {
    domains,
    rows,
  }
}

export async function listDomainCapabilities(domain) {
  const data = await api.get(`/capabilities/${encodeURIComponent(domain)}`)
  return Array.isArray(data) ? data.map(normalizeCapability) : []
}

export async function runSelfCheck() {
  return api.post('/capabilities/self-check')
}

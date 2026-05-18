import { api } from './client.js'
import { normalizeWorkspacePackage } from './normalizers.js'

export async function getWorkspace() {
  return api.get('/workspace')
}

export async function listWorkspacePackages() {
  const data = await api.get('/workspace/packages')
  return Array.isArray(data) ? data.map(normalizeWorkspacePackage) : []
}

export async function writePackageLock() {
  return api.post('/workspace/packages/lock')
}

export async function setPackageEnabled(packageId, enabled) {
  const action = enabled ? 'enable' : 'disable'
  return api.post(`/workspace/packages/${encodeURIComponent(packageId)}/${action}`)
}

export async function planPackageUpgrade(packageId, payload = {}) {
  return api.post(`/workspace/packages/${encodeURIComponent(packageId)}/upgrade-plan`, {
    ...payload,
    dry_run: true,
    apply: false,
  })
}

export async function applyPackageUpgrade(packageId, payload = {}) {
  return api.post(`/workspace/packages/${encodeURIComponent(packageId)}/upgrade`, {
    ...payload,
    dry_run: false,
    apply: true,
  })
}

export async function getPackagePermissions(packageId) {
  return api.get(`/workspace/packages/${encodeURIComponent(packageId)}/permissions`)
}

export async function getPackageMigrations(packageId) {
  return api.get(`/workspace/packages/${encodeURIComponent(packageId)}/migrations`)
}

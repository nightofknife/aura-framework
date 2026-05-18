import { setRuntimeConnection } from '../config.js'

export function isDesktopShell() {
  return typeof window !== 'undefined' && !!window.auraDesktop?.isElectron
}

export async function discoverRuntimeCandidates() {
  if (!isDesktopShell()) return []
  const candidates = await window.auraDesktop.getRuntimeCandidates()
  return Array.isArray(candidates) ? candidates.map(normalizeCandidate) : []
}

export async function readRuntimeToken(tokenPath) {
  if (!isDesktopShell()) throw new Error('Aura desktop shell is not available.')
  return window.auraDesktop.readRuntimeToken(tokenPath)
}

export function connectRuntime(candidate) {
  return setRuntimeConnection({
    id: candidate?.id,
    apiBase: candidate?.apiBase,
    wsBase: candidate?.wsBase,
  })
}

function normalizeCandidate(candidate) {
  return {
    id: candidate?.id || candidate?.apiBase || 'runtime',
    version: candidate?.version || '',
    apiBase: candidate?.apiBase || candidate?.api_base || '',
    wsBase: candidate?.wsBase || candidate?.ws_base || '',
    basePath: candidate?.basePath || candidate?.base_path || '',
    tokenPath: candidate?.tokenPath || candidate?.token_path || '',
    status: candidate?.status || 'unknown',
    health: candidate?.health || candidate?.status || 'unknown',
    source: candidate?.source || '',
  }
}

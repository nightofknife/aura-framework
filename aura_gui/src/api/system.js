import { api } from './client.js'
import { normalizeSystem } from './normalizers.js'

export async function getHealth() {
  return normalizeSystem(await api.get('/system/health'))
}

export async function getStatus() {
  return normalizeSystem(await api.get('/system/status'))
}

export async function startSystem() {
  return api.post('/system/start')
}

export async function stopSystem() {
  return api.post('/system/stop')
}

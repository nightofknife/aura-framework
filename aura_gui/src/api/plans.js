import { api } from './client.js'
import { normalizeAction, normalizePlan, normalizeTask, normalizeTaskLoadError } from './normalizers.js'

export async function listPlans() {
  const data = await api.get('/plans')
  return Array.isArray(data) ? data.map(normalizePlan) : []
}

export async function listTasks(planName) {
  if (!planName) return []
  const data = await api.get(`/plans/${encodeURIComponent(planName)}/tasks`)
  if (!Array.isArray(data)) return []

  const seen = new Set()
  return data
    .map(normalizeTask)
    .filter((task) => {
      const key = `${task.planName}::${task.taskRef || task.fullTaskId || task.key}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

export async function listTaskLoadErrors(planName) {
  if (!planName) return []
  const data = await api.get(`/plans/${encodeURIComponent(planName)}/task-load-errors`)
  return Array.isArray(data) ? data.map(normalizeTaskLoadError) : []
}

export async function listActions() {
  const data = await api.get('/actions')
  return Array.isArray(data) ? data.map(normalizeAction) : []
}

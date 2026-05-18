import { api, getApiConfig } from './client.js'
import { normalizeDispatch } from './normalizers.js'

export async function dispatchTask({ planName, taskRef, inputs = {} }) {
  const cfg = getApiConfig()
  const data = await api.post('/tasks/dispatch', {
    plan_name: planName,
    task_ref: taskRef,
    inputs,
  }, { timeout: cfg.dispatch_timeout_ms || cfg.timeout_ms || 10000 })
  return normalizeDispatch(data)
}

export async function validateTask({ planName, taskRef, strict = false }) {
  return api.post('/tasks/validate', {
    plan_name: planName,
    task_ref: taskRef,
    strict,
    dry_run: false,
  })
}

export async function dryRunTask({ planName, taskRef, strict = false }) {
  return api.post('/tasks/dry-run', {
    plan_name: planName,
    task_ref: taskRef,
    strict,
  })
}

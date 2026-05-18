import { api } from './client.js'

export async function getErrorSummary() {
  return api.get('/observability/errors/summary')
}

export async function getBackendMetrics() {
  return api.get('/observability/metrics/backends')
}

export async function getActionMetrics() {
  return api.get('/observability/metrics/actions')
}

export async function getServiceMetrics() {
  return api.get('/observability/metrics/services')
}

export async function getDesktopMetrics() {
  return api.get('/observability/metrics/desktop')
}

export async function getResourceSamples() {
  return api.get('/observability/resources')
}

export async function listTraces() {
  return api.get('/observability/traces')
}

export async function getErrorCategory(category) {
  return api.get(`/observability/errors/${encodeURIComponent(category)}`)
}

import axios from 'axios'
import { getGuiConfig, RUNTIME_CONNECTION_EVENT } from '../config.js'
import { normalizeApiError } from './errors.js'

const cfg = getGuiConfig()
const API_TOKEN_STORAGE_KEY = 'aura_local_api_token'
export const API_TOKEN_EVENT = 'aura-api-token-changed'

export const apiClient = axios.create({
  baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: cfg?.api?.timeout_ms || 5000,
})

function applyLocalToken(config) {
  if (!isMutatingMethod(config?.method)) return config
  const token = getApiToken()
  if (!token) throw buildMissingTokenError()
  return {
    ...config,
    headers: {
      ...(config.headers || {}),
      'X-Aura-CSRF-Token': token,
    },
  }
}

apiClient.interceptors.request.use(applyLocalToken)

export function refreshApiClientConfig() {
  const nextCfg = getGuiConfig()
  apiClient.defaults.baseURL = nextCfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1'
  apiClient.defaults.timeout = nextCfg?.api?.timeout_ms || 5000
}

if (typeof window !== 'undefined') {
  window.addEventListener(RUNTIME_CONNECTION_EVENT, refreshApiClientConfig)
}

export function createAuraAxiosClient(config = {}) {
  const client = axios.create(config)
  client.interceptors.request.use(applyLocalToken)
  client.interceptors.response.use(
    (response) => response,
    (error) => Promise.reject(normalizeApiError(error))
  )
  return client
}

function safeStorage(kind) {
  if (typeof window === 'undefined') return null
  try {
    return kind === 'local' ? window.localStorage : window.sessionStorage
  } catch {
    return null
  }
}

function notifyApiTokenChange() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(API_TOKEN_EVENT, { detail: { configured: hasApiToken() } }))
}

function isMutatingMethod(method = 'get') {
  return ['post', 'put', 'patch', 'delete'].includes(String(method).toLowerCase())
}

export function getApiToken() {
  return (
    safeStorage('session')?.getItem(API_TOKEN_STORAGE_KEY) ||
    safeStorage('local')?.getItem(API_TOKEN_STORAGE_KEY) ||
    ''
  ).trim()
}

export function hasApiToken() {
  return !!getApiToken()
}

export function getApiTokenPersistence() {
  if (safeStorage('session')?.getItem(API_TOKEN_STORAGE_KEY)) return 'session'
  if (safeStorage('local')?.getItem(API_TOKEN_STORAGE_KEY)) return 'local'
  return 'none'
}

export function setApiToken(token, { remember = false } = {}) {
  const value = String(token || '').trim()
  clearApiToken({ notify: false })
  if (value) {
    const target = safeStorage(remember ? 'local' : 'session')
    target?.setItem(API_TOKEN_STORAGE_KEY, value)
  }
  notifyApiTokenChange()
}

export function clearApiToken({ notify = true } = {}) {
  safeStorage('session')?.removeItem(API_TOKEN_STORAGE_KEY)
  safeStorage('local')?.removeItem(API_TOKEN_STORAGE_KEY)
  if (notify) notifyApiTokenChange()
}

function buildMissingTokenError() {
  return {
    name: 'AuraApiError',
    status: 0,
    message: 'Local API token is required for this operation. Configure it in Settings.',
    detail: 'Missing local API token.',
    data: null,
    requiresToken: true,
    featureUnavailable: false,
  }
}

export async function request(config) {
  try {
    const nextConfig = { ...config }
    if (isMutatingMethod(nextConfig.method)) {
      const token = getApiToken()
      if (!token) throw buildMissingTokenError()
      nextConfig.headers = {
        ...(nextConfig.headers || {}),
        'X-Aura-CSRF-Token': token,
      }
    }
    const response = await apiClient.request(nextConfig)
    return response.data
  } catch (error) {
    if (error?.requiresToken) throw error
    throw normalizeApiError(error)
  }
}

export const api = {
  get: (url, config = {}) => request({ ...config, method: 'get', url }),
  post: (url, data, config = {}) => request({ ...config, method: 'post', url, data }),
  put: (url, data, config = {}) => request({ ...config, method: 'put', url, data }),
  delete: (url, config = {}) => request({ ...config, method: 'delete', url }),
}

export function getApiConfig() {
  return getGuiConfig()?.api || {}
}

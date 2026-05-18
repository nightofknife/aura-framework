export function normalizeApiError(error) {
  const status = error?.response?.status || 0
  const detail = error?.response?.data?.detail
  const message = typeof detail === 'string'
    ? detail
    : detail?.message || error?.message || '请求失败'

  return {
    name: 'AuraApiError',
    status,
    message,
    detail,
    data: error?.response?.data || null,
    featureUnavailable: status === 404,
    requiresToken: !!error?.requiresToken || (
      [0, 401].includes(status) && String(message || '').toLowerCase().includes('local api token')
    ),
    original: error,
  }
}

export function errorMessage(error, fallback = '请求失败') {
  if (!error) return fallback
  if (typeof error === 'string') return error
  if (error.requiresToken) return 'Local API token is required. Open Settings and paste logs/local_api_token.'
  return error.message || error.detail?.message || fallback
}

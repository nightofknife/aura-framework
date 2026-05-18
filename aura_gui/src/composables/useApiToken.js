import { onMounted, onUnmounted, ref } from 'vue'

import { API_TOKEN_EVENT, getApiTokenPersistence, hasApiToken } from '../api/client.js'

export function useApiTokenStatus() {
  const hasToken = ref(hasApiToken())
  const persistence = ref(getApiTokenPersistence())

  function refresh() {
    hasToken.value = hasApiToken()
    persistence.value = getApiTokenPersistence()
  }

  onMounted(() => {
    refresh()
    window.addEventListener(API_TOKEN_EVENT, refresh)
    window.addEventListener('storage', refresh)
  })

  onUnmounted(() => {
    window.removeEventListener(API_TOKEN_EVENT, refresh)
    window.removeEventListener('storage', refresh)
  })

  return {
    hasToken,
    persistence,
    refresh,
  }
}

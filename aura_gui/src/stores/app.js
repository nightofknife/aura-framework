// 主应用状态管理 Store
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../api/client.js'

export const useAppStore = defineStore('app', () => {
  // ========== State ==========
  const systemRunning = ref(false)
  const connectionStatus = ref('disconnected') // 'connected' | 'disconnected' | 'connecting'
  const backendHealthy = ref(true)
  const lastHeartbeat = ref(null)

  // ========== Computed ==========
  const isConnected = computed(() => connectionStatus.value === 'connected')
  const isHealthy = computed(() => backendHealthy.value && systemRunning.value)

  // ========== Actions ==========

  /**
   * 获取系统状态
   */
  async function fetchSystemStatus() {
    try {
      const data = await api.get('/system/status')

      systemRunning.value = data?.is_running ?? false
      backendHealthy.value = true
      lastHeartbeat.value = Date.now()

      return data
    } catch (error) {
      console.error('[AppStore] 获取系统状态失败:', error)
      backendHealthy.value = false
      throw error
    }
  }

  /**
   * 启动系统
   */
  async function startSystem() {
    try {
      const data = await api.post('/system/start')

      if (data?.success) {
        systemRunning.value = true
      }

      return data
    } catch (error) {
      console.error('[AppStore] 启动系统失败:', error)
      throw error
    }
  }

  /**
   * 停止系统
   */
  async function stopSystem() {
    try {
      const data = await api.post('/system/stop')

      if (data?.success) {
        systemRunning.value = false
      }

      return data
    } catch (error) {
      console.error('[AppStore] 停止系统失败:', error)
      throw error
    }
  }

  /**
   * 更新连接状态
   */
  function setConnectionStatus(status) {
    connectionStatus.value = status
  }

  /**
   * 更新系统运行状态
   */
  function setSystemRunning(running) {
    systemRunning.value = running
  }

  /**
   * 重置状态
   */
  function reset() {
    systemRunning.value = false
    connectionStatus.value = 'disconnected'
    backendHealthy.value = true
    lastHeartbeat.value = null
  }

  return {
    // State
    systemRunning,
    connectionStatus,
    backendHealthy,
    lastHeartbeat,

    // Computed
    isConnected,
    isHealthy,

    // Actions
    fetchSystemStatus,
    startSystem,
    stopSystem,
    setConnectionStatus,
    setSystemRunning,
    reset
  }
})

// 主应用状态管理 Store
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import { getGuiConfig } from '../config.js'

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
      const config = getGuiConfig()
      const baseUrl = config.api?.base_url || 'http://127.0.0.1:18098/api/v1'
      const response = await axios.get(`${baseUrl}/system/status`, {
        timeout: config.api?.timeout_ms || 5000
      })

      systemRunning.value = response.data?.is_running ?? false
      backendHealthy.value = true
      lastHeartbeat.value = Date.now()

      return response.data
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
      const config = getGuiConfig()
      const baseUrl = config.api?.base_url || 'http://127.0.0.1:18098/api/v1'
      const response = await axios.post(`${baseUrl}/system/start`)

      if (response.data?.success) {
        systemRunning.value = true
      }

      return response.data
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
      const config = getGuiConfig()
      const baseUrl = config.api?.base_url || 'http://127.0.0.1:18098/api/v1'
      const response = await axios.post(`${baseUrl}/system/stop`)

      if (response.data?.success) {
        systemRunning.value = false
      }

      return response.data
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

// 主应用状态管理 Store
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios, { type AxiosResponse } from 'axios'
import { getGuiConfig } from '../config.js'
import type { SystemStatus } from '../types/api'

type ConnectionStatus = 'connected' | 'disconnected' | 'connecting'

interface SystemResponse {
  is_running?: boolean
  success?: boolean
}

export const useAppStore = defineStore('app', () => {
  // ========== State ==========
  const systemRunning = ref<boolean>(false)
  const connectionStatus = ref<ConnectionStatus>('disconnected')
  const backendHealthy = ref<boolean>(true)
  const lastHeartbeat = ref<number | null>(null)

  // ========== Computed ==========
  const isConnected = computed(() => connectionStatus.value === 'connected')
  const isHealthy = computed(() => backendHealthy.value && systemRunning.value)

  // ========== Actions ==========

  /**
   * 获取系统状态
   */
  async function fetchSystemStatus(): Promise<SystemStatus> {
    try {
      const config = getGuiConfig()
      const baseUrl = config.api?.base_url || 'http://127.0.0.1:18098/api/v1'
      const response: AxiosResponse<SystemStatus> = await axios.get(
        `${baseUrl}/system/status`,
        {
          timeout: config.api?.timeout_ms || 5000
        }
      )

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
  async function startSystem(): Promise<SystemResponse> {
    try {
      const config = getGuiConfig()
      const baseUrl = config.api?.base_url || 'http://127.0.0.1:18098/api/v1'
      const response: AxiosResponse<SystemResponse> = await axios.post(
        `${baseUrl}/system/start`
      )

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
  async function stopSystem(): Promise<SystemResponse> {
    try {
      const config = getGuiConfig()
      const baseUrl = config.api?.base_url || 'http://127.0.0.1:18098/api/v1'
      const response: AxiosResponse<SystemResponse> = await axios.post(
        `${baseUrl}/system/stop`
      )

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
  function setConnectionStatus(status: ConnectionStatus): void {
    connectionStatus.value = status
  }

  /**
   * 更新系统运行状态
   */
  function setSystemRunning(running: boolean): void {
    systemRunning.value = running
  }

  /**
   * 重置状态
   */
  function reset(): void {
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

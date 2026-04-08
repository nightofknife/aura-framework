// 任务队列状态管理 Store
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import { getGuiConfig } from '../config.js'

export const useQueueStore = defineStore('queue', () => {
  // ========== State ==========
  const backendQueue = ref([])
  const guiQueue = ref([])
  const loading = ref(false)
  const error = ref(null)
  const lastUpdate = ref(null)

  // ========== Computed ==========
  const backendQueueSize = computed(() => backendQueue.value.length)
  const guiQueueSize = computed(() => guiQueue.value.length)
  const totalQueueSize = computed(() => backendQueueSize.value + guiQueueSize.value)

  const hasQueuedTasks = computed(() => totalQueueSize.value > 0)

  // ========== Actions ==========

  /**
   * 获取后端队列
   */
  async function fetchBackendQueue() {
    loading.value = true
    error.value = null

    try {
      const config = getGuiConfig()
      const baseUrl = config.api?.base_url || 'http://127.0.0.1:18098/api/v1'
      const limit = config.api?.queue_list_limit || 200

      const response = await axios.get(`${baseUrl}/queue/list`, {
        params: { limit },
        timeout: config.api?.timeout_ms || 5000
      })

      backendQueue.value = response.data || []
      lastUpdate.value = Date.now()

      return backendQueue.value
    } catch (err) {
      console.error('[QueueStore] 获取后端队列失败:', err)
      error.value = err.message || '获取失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * 添加任务到 GUI 队列
   */
  function addToGuiQueue(task) {
    guiQueue.value.push(task)
    lastUpdate.value = Date.now()
  }

  /**
   * 从 GUI 队列移除任务
   */
  function removeFromGuiQueue(taskId) {
    const index = guiQueue.value.findIndex(t => t.id === taskId || t.cid === taskId)
    if (index !== -1) {
      guiQueue.value.splice(index, 1)
      lastUpdate.value = Date.now()
    }
  }

  /**
   * 清空 GUI 队列
   */
  function clearGuiQueue() {
    guiQueue.value = []
    lastUpdate.value = Date.now()
  }

  /**
   * 更新后端队列（通过 WebSocket 推送）
   */
  function updateBackendQueue(items) {
    backendQueue.value = items
    lastUpdate.value = Date.now()
  }

  /**
   * 添加任务到后端队列
   */
  function addToBackendQueue(task) {
    backendQueue.value.push(task)
    lastUpdate.value = Date.now()
  }

  /**
   * 从后端队列移除任务
   */
  function removeFromBackendQueue(taskId) {
    const index = backendQueue.value.findIndex(t => t.cid === taskId)
    if (index !== -1) {
      backendQueue.value.splice(index, 1)
      lastUpdate.value = Date.now()
    }
  }

  /**
   * 重置状态
   */
  function reset() {
    backendQueue.value = []
    guiQueue.value = []
    loading.value = false
    error.value = null
    lastUpdate.value = null
  }

  return {
    // State
    backendQueue,
    guiQueue,
    loading,
    error,
    lastUpdate,

    // Computed
    backendQueueSize,
    guiQueueSize,
    totalQueueSize,
    hasQueuedTasks,

    // Actions
    fetchBackendQueue,
    addToGuiQueue,
    removeFromGuiQueue,
    clearGuiQueue,
    updateBackendQueue,
    addToBackendQueue,
    removeFromBackendQueue,
    reset
  }
})

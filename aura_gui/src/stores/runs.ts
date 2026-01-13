// 运行中任务状态管理 Store
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios, { type AxiosResponse } from 'axios'
import { getGuiConfig } from '../config.js'
import type { TaskRun } from '../types/api'

export const useRunsStore = defineStore('runs', () => {
  // ========== State ==========
  const runs = ref<TaskRun[]>([])
  const loading = ref<boolean>(false)
  const error = ref<string | null>(null)
  const lastUpdate = ref<number | null>(null)

  // ========== Computed ==========
  const runningCount = computed(() => {
    return runs.value.filter(r => r.status === 'running').length
  })

  const completedCount = computed(() => {
    return runs.value.filter(r => r.status === 'success').length
  })

  const failedCount = computed(() => {
    return runs.value.filter(r => r.status === 'error').length
  })

  const totalCount = computed(() => runs.value.length)

  const runsByStatus = computed(() => {
    const byStatus: Record<string, TaskRun[]> = {}
    runs.value.forEach(run => {
      const status = run.status || 'unknown'
      if (!byStatus[status]) {
        byStatus[status] = []
      }
      byStatus[status].push(run)
    })
    return byStatus
  })

  // ========== Actions ==========

  /**
   * 获取所有运行中的任务
   */
  async function fetchRuns(): Promise<TaskRun[]> {
    loading.value = true
    error.value = null

    try {
      const config = getGuiConfig()
      const baseUrl = config.api?.base_url || 'http://127.0.0.1:18098/api/v1'
      const response: AxiosResponse<TaskRun[]> = await axios.get(
        `${baseUrl}/runs`,
        {
          timeout: config.api?.timeout_ms || 5000
        }
      )

      runs.value = response.data || []
      lastUpdate.value = Date.now()

      return runs.value
    } catch (err: any) {
      console.error('[RunsStore] 获取运行任务失败:', err)
      error.value = err.message || '获取失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * 根据 ID 获取单个运行任务
   */
  function getRunById(id: string): TaskRun | undefined {
    return runs.value.find(r => r.id === id || r.cid === id)
  }

  /**
   * 更新单个运行任务的状态
   */
  function updateRun(id: string, updates: Partial<TaskRun>): void {
    const index = runs.value.findIndex(r => r.id === id || r.cid === id)
    if (index !== -1) {
      runs.value[index] = { ...runs.value[index], ...updates }
    } else {
      // 如果不存在，添加新的
      runs.value.push({ id, cid: id, ...updates } as TaskRun)
    }
    lastUpdate.value = Date.now()
  }

  /**
   * 删除运行任务
   */
  function removeRun(id: string): void {
    const index = runs.value.findIndex(r => r.id === id || r.cid === id)
    if (index !== -1) {
      runs.value.splice(index, 1)
      lastUpdate.value = Date.now()
    }
  }

  /**
   * 批量更新运行任务
   */
  function batchUpdateRuns(updatedRuns: TaskRun[]): void {
    runs.value = updatedRuns
    lastUpdate.value = Date.now()
  }

  /**
   * 清空所有运行任务
   */
  function clearRuns(): void {
    runs.value = []
    lastUpdate.value = Date.now()
  }

  /**
   * 重置状态
   */
  function reset(): void {
    runs.value = []
    loading.value = false
    error.value = null
    lastUpdate.value = null
  }

  return {
    // State
    runs,
    loading,
    error,
    lastUpdate,

    // Computed
    runningCount,
    completedCount,
    failedCount,
    totalCount,
    runsByStatus,

    // Actions
    fetchRuns,
    getRunById,
    updateRun,
    removeRun,
    batchUpdateRuns,
    clearRuns,
    reset
  }
})

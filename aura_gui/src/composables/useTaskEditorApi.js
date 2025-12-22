import axios from 'axios'
import { getGuiConfig } from '../config.js'

const cfg = getGuiConfig()
const api = axios.create({
  baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: cfg?.api?.dispatch_timeout_ms || cfg?.api?.timeout_ms || 10000
})

export function useTaskEditorApi() {
  const listPlans = async () => (await api.get('/plans')).data || []
  const listTasksForPlan = async (planName) => (await api.get(`/plans/${planName}/tasks`)).data || []
  const listActions = async () => (await api.get('/actions')).data || []
  const getPlanFilesTree = async (planName) => (await api.get(`/plans/${planName}/files/tree`)).data || {}
  const getFileContent = async (planName, path) => (await api.get(`/plans/${planName}/files/content`, { params: { path } })).data
  const saveFileContent = async (planName, path, content) => api.put(`/plans/${planName}/files/content`, content, { params: { path } })
  const reloadFile = async (planName, path) => api.post(`/plans/${planName}/files/reload`, null, { params: { path } })

  return {
    listPlans,
    listTasksForPlan,
    listActions,
    getPlanFilesTree,
    getFileContent,
    saveFileContent,
    reloadFile
  }
}

import { api } from '../api/client.js'

export function useTaskEditorApi() {
  const listPlans = async () => await api.get('/plans') || []
  const listTasksForPlan = async (planName) => await api.get(`/plans/${planName}/tasks`) || []
  const listActions = async () => await api.get('/actions') || []
  const getPlanFilesTree = async (planName) => await api.get(`/plans/${planName}/files/tree`) || {}
  const getFileContent = async (planName, path) => api.get(`/plans/${planName}/files/content`, { params: { path } })
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

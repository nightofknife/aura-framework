import { reactive } from 'vue'
import { nanoid } from 'nanoid'

export function useTaskStore() {
  const state = reactive({
    taskFile: null,
    currentTaskKey: '',
    selected: { type: 'task', id: '' },
    actions: []
  })

  const setTaskFile = (taskFile) => {
    state.taskFile = taskFile
    const keys = Object.keys(taskFile?.tasks || {})
    state.currentTaskKey = keys[0] || ''
    state.selected = { type: 'task', id: '' }
  }

  const setCurrentTaskKey = (taskKey) => {
    state.currentTaskKey = taskKey
    state.selected = { type: 'task', id: '' }
  }

  const getCurrentTask = () => state.taskFile?.tasks?.[state.currentTaskKey] || null

  const addNode = () => {
    const task = getCurrentTask()
    if (!task) return null
    let baseId = 'node'
    let idx = 1
    let id = `${baseId}_${idx}`
    while (task.steps[id]) {
      idx += 1
      id = `${baseId}_${idx}`
    }
    task.steps[id] = { id, action: '', depends_on: { type: 'and', children: [] } }
    task.nodeOrder.push(id)
    return id
  }

  const addGateId = (prefix) => `${prefix}_${nanoid(6)}`

  const updateNode = (nodeId, patch) => {
    const task = getCurrentTask()
    if (!task || !task.steps[nodeId]) return
    task.steps[nodeId] = { ...task.steps[nodeId], ...patch }
  }

  const removeNode = (nodeId) => {
    const task = getCurrentTask()
    if (!task || !task.steps[nodeId]) return
    delete task.steps[nodeId]
    task.nodeOrder = task.nodeOrder.filter((id) => id !== nodeId)
  }

  const updateTask = (patch) => {
    const task = getCurrentTask()
    if (!task) return
    Object.assign(task, patch)
  }

  return {
    state,
    setTaskFile,
    setCurrentTaskKey,
    getCurrentTask,
    addNode,
    addGateId,
    updateNode,
    removeNode,
    updateTask
  }
}

<template>
  <div class="panel">
    <div class="panel-header">
      <strong>任务编辑器</strong>
      <div style="color:var(--text-secondary); font-size:13px;">图形化任务编排</div>
    </div>
    <div class="panel-body">
      <Toolbar
        @add-node="handleAddNode"
        @add-gate="handleAddGate"
        @auto-layout="handleAutoLayout"
        @validate="runValidation"
        @preview="openPreview"
        @save="handleSave"
      />

      <div class="task-editor-surface" ref="surfaceRef">
        <div class="task-editor-top" :style="{ height: `${topHeight}px` }">
          <TaskExplorer
            :plans="plans"
            :tasks="tasks"
            :selected-plan="selectedPlan"
            :selected-file="selectedFile"
            :selected-task-key="currentTaskKey"
            @select-plan="selectPlan"
            @select-file="selectFile"
            @select-task="selectTaskKey"
            @create-task="handleCreateTask"
          />
        </div>

        <div class="splitter horizontal" @pointerdown="startDrag('top', $event)"></div>

        <div class="task-editor-main">
          <div
            class="task-editor-left"
            :style="{ width: `${leftWidth}px` }"
          >
            <ActionLibrary :actions="actions" @add-action="handleAddAction" />
          </div>

          <div class="splitter vertical" @pointerdown="startDrag('left', $event)"></div>

          <div class="task-editor-center">
            <TaskCanvas
              ref="canvasRef"
              :nodes="currentNodes"
              :gates="graphStore.state.gates"
              :edges="graphStore.state.edges"
              :layout="layoutStore.state"
              :viewport="layoutStore.state.viewport"
              :selected="taskStore.state.selected"
              @select-node="selectNode"
              @select-gate="selectGate"
              @move-node="moveNode"
              @move-gate="moveGate"
              @connect="handleConnect"
              @remove-edge="removeEdge"
              @remove-node="removeNode"
              @remove-gate="removeGate"
              @zoom="handleZoom"
              @pan="handlePan"
            />
          </div>

          <div class="splitter vertical" @pointerdown="startDrag('right', $event)"></div>

          <div class="task-editor-right" ref="rightRef" :style="{ width: `${rightWidth}px` }">
            <div class="right-top" :style="{ height: `${rightTopHeight}px` }">
              <PropertyPanel
                :selection="taskStore.state.selected"
                :task="currentTask"
                :node="selectedNode"
                :gate="selectedGate"
                :actions="actions"
                @update-task="updateTask"
                @update-node="updateNode"
                @update-gate="updateGate"
                @remove-node="removeNode"
                @remove-gate="removeGate"
              />
            </div>
            <div class="splitter horizontal" @pointerdown="startDrag('right-height', $event)"></div>
            <div class="right-bottom">
              <ValidationPanel
                :errors="validationStore.state.errors"
                :warnings="validationStore.state.warnings"
                @focus="focusIssue"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div v-if="previewOpen" class="preview-mask" @click.self="previewOpen=false">
    <div class="panel preview-panel">
      <div class="panel-header"><strong>YAML 预览</strong></div>
      <div class="panel-body">
        <pre class="preview-text">{{ previewContent }}</pre>
      </div>
      <div class="panel-body" style="text-align:right;">
        <button class="btn btn-ghost" @click="previewOpen=false">关闭</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onBeforeUnmount, ref, computed } from 'vue'
import '../styles/task-editor.css'
import TaskExplorer from '../components/task-editor/TaskExplorer.vue'
import TaskCanvas from '../components/task-editor/TaskCanvas.vue'
import PropertyPanel from '../components/task-editor/PropertyPanel.vue'
import ValidationPanel from '../components/task-editor/ValidationPanel.vue'
import Toolbar from '../components/task-editor/Toolbar.vue'
import ActionLibrary from '../components/task-editor/ActionLibrary.vue'

import { useTaskEditorApi } from '../composables/useTaskEditorApi.js'
import { useTaskStore } from '../task_editor/state/taskStore.js'
import { useGraphStore } from '../task_editor/state/graphStore.js'
import { useLayoutStore } from '../task_editor/state/layoutStore.js'
import { useValidationStore } from '../task_editor/state/validationStore.js'
import { createEmptyGraph, depExprToGraph, buildDepExprFromGraph } from '../task_editor/convert/graphCompiler.js'
import { loadTaskFile, saveTaskFile } from '../task_editor/io/yamlIO.js'
import { stringifyTaskFile } from '../task_editor/convert/yamlCompiler.js'
import { loadLayout, saveLayout } from '../task_editor/io/sidecarIO.js'
import { autoLayout } from '../task_editor/layout/autoLayout.js'

const api = useTaskEditorApi()
const taskStore = useTaskStore()
const graphStore = useGraphStore()
const layoutStore = useLayoutStore()
const validationStore = useValidationStore()

const plans = ref([])
const tasks = ref([])
const actions = ref([])

const selectedPlan = ref('')
const selectedFile = ref('')
const currentTaskKey = computed(() => taskStore.state.currentTaskKey)


const previewOpen = ref(false)
const previewContent = ref('')

const currentTask = computed(() => taskStore.getCurrentTask())
const currentNodes = computed(() => currentTask.value?.steps || {})

const surfaceRef = ref(null)
const canvasRef = ref(null)
const rightRef = ref(null)

const topHeight = ref(220)
const leftWidth = ref(280)
const rightWidth = ref(320)
const rightTopHeight = ref(360)

const dragState = ref(null)
const splitterSize = 6
const minCenterWidth = 360
const minLeftWidth = 200
const minRightWidth = 260
const minTopAreaHeight = 160
const minPropertyHeight = 220
const minValidationHeight = 140
const clampValue = (value, min, max) => Math.min(Math.max(value, min), max)

const selectedNode = computed(() => {
  if (taskStore.state.selected.type !== 'node') return null
  return currentTask.value?.steps?.[taskStore.state.selected.id] || null
})

const selectedGate = computed(() => {
  if (taskStore.state.selected.type !== 'gate') return null
  return graphStore.state.gates[taskStore.state.selected.id] || null
})

const loadPlans = async () => {
  const [plansResult, actionsResult] = await Promise.allSettled([
    api.listPlans(),
    api.listActions()
  ])

  plans.value = plansResult.status === 'fulfilled' ? plansResult.value : []
  actions.value = actionsResult.status === 'fulfilled' ? actionsResult.value : []

  if (!selectedPlan.value && plans.value.length) {
    await selectPlan(plans.value[0].name)
  }
}

const selectPlan = async (planName) => {
  selectedPlan.value = planName
  selectedFile.value = ''
  taskStore.setTaskFile({ path: '', tasks: {} })
  graphStore.setGraph({ gates: {}, edges: [] })
  layoutStore.setLayout({ nodes: {}, gates: {}, viewport: { x: 0, y: 0, zoom: 1 } })
  tasks.value = await api.listTasksForPlan(planName)
}

const selectFile = async (filePath) => {
  selectedFile.value = filePath
  if (!selectedPlan.value || !filePath) return
  const taskFile = await loadTaskFile(api, selectedPlan.value, filePath)
  taskStore.setTaskFile(taskFile)
  if (taskStore.state.currentTaskKey) {
    await loadGraphForTask(taskStore.state.currentTaskKey)
  }
}

const selectTaskKey = async (payload) => {
  let taskKey = payload
  let filePath = selectedFile.value
  if (payload && typeof payload === 'object') {
    taskKey = payload.taskKey
    filePath = payload.filePath
  }
  if (filePath && filePath !== selectedFile.value) {
    await selectFile(filePath)
  }
  taskStore.setCurrentTaskKey(taskKey)
  await loadGraphForTask(taskKey)
}

const loadGraphForTask = async (taskKey) => {
  if (!selectedPlan.value || !selectedFile.value) return
  const task = taskStore.state.taskFile?.tasks?.[taskKey]
  if (!task) return

  const graph = createEmptyGraph()
  const gateIdFactory = (prefix) => taskStore.addGateId(prefix)

  for (const node of Object.values(task.steps)) {
    depExprToGraph(node.id, node.depends_on, graph, gateIdFactory)
  }

  graphStore.setGraph(graph)

  const layoutFile = await loadLayout(api, selectedPlan.value, selectedFile.value)
  if (!layoutFile.tasks) layoutFile.tasks = {}
  if (!layoutFile.tasks[taskKey]) {
    layoutFile.tasks[taskKey] = { nodes: {}, gates: {}, edges: graph.edges, viewport: { x: 0, y: 0, zoom: 1 } }
  }

  const layout = layoutFile.tasks[taskKey]
  layout.nodes = layout.nodes || {}
  layout.gates = layout.gates || {}
  layout.edges = graph.edges

  layoutStore.setLayout(layout)
  const canvasRect = canvasRef.value?.getCanvasRect()
  autoLayout(
    { nodes: task.steps, gates: graph.gates, edges: graph.edges },
    layoutStore.state,
    { width: canvasRect?.width, height: canvasRect?.height }
  )

  taskStore.state.selected = { type: 'task', id: '' }
}

const selectNode = (nodeId) => {
  taskStore.state.selected = { type: 'node', id: nodeId }
}

const selectGate = (gateId) => {
  taskStore.state.selected = { type: 'gate', id: gateId }
}

const moveNode = ({ id, x, y }) => {
  layoutStore.updateNodePos(id, { x, y })
}

const moveGate = ({ id, x, y }) => {
  layoutStore.updateGatePos(id, { x, y })
}

const handleConnect = ({ from, to, kind }) => {
  if (!from || !to || from === to) return
  if (kind === 'visual_only') {
    const gate = graphStore.state.gates[to]
    if (gate?.type === 'status') {
      graphStore.removeEdgesTo(to, 'visual_only')
      graphStore.updateGate(to, { node_id: from })
      graphStore.addEdge({ from, to, kind: 'visual_only' })
    }
    return
  }
  graphStore.addEdge({ from, to })
}

const removeEdge = (edge) => {
  if (!edge || edge.kind === 'visual_only') return
  graphStore.removeEdge(edge)
}

const handleAddNode = () => {
  const nodeId = taskStore.addNode()
  if (!nodeId) return
  placeNode(nodeId)
  taskStore.state.selected = { type: 'node', id: nodeId }
}

const handleAddGate = (type) => {
  if (!type) return
  const gateId = taskStore.addGateId(type)
  graphStore.addGate({ id: gateId, type })
  layoutStore.ensureGate(gateId, 120, 80)
  taskStore.state.selected = { type: 'gate', id: gateId }
}

const placeNode = (nodeId) => {
  const existing = Object.keys(layoutStore.state.nodes)
  const index = existing.length
  const col = index % 4
  const row = Math.floor(index / 4)
  const x = 80 + col * 220
  const y = 80 + row * 140
  layoutStore.ensureNode(nodeId, x, y)
}

const handleAddAction = (action) => {
  const nodeId = taskStore.addNode()
  if (!nodeId) return
  const name = action?.name || action?.fqid || ''
  if (name) {
    taskStore.updateNode(nodeId, { action: name })
  }
  placeNode(nodeId)
  taskStore.state.selected = { type: 'node', id: nodeId }
}

const deriveTaskPath = (taskName) => {
  let cleanName = taskName.replace(/^\/+/, '').replace(/\.yaml$/i, '')
  if (cleanName.startsWith('tasks/')) {
    cleanName = cleanName.slice(6)
  }
  const parts = cleanName.split('/').filter(Boolean)
  if (parts.length === 0) {
    return { filePath: '', taskKey: '' }
  }
  const taskKey = parts[parts.length - 1]
  const filePathParts = parts.length === 1 ? [taskKey] : parts.slice(0, -1)
  return { filePath: `tasks/${filePathParts.join('/')}.yaml`, taskKey }
}

const createEmptyTask = (taskKey) => ({
  meta: { title: taskKey || '' },
  execution_mode: 'sync',
  returns: undefined,
  steps: {},
  nodeOrder: []
})

const handleCreateTask = async (taskName) => {
  if (!selectedPlan.value) return
  const normalized = String(taskName || '').trim()
  if (!normalized) return

  let filePath = ''
  let taskKey = ''
  if (!normalized.includes('/') && selectedFile.value) {
    filePath = selectedFile.value
    taskKey = normalized
  } else {
    const derived = deriveTaskPath(normalized)
    filePath = derived.filePath
    taskKey = derived.taskKey
  }
  if (!filePath || !taskKey) return

  let taskFile
  try {
    taskFile = await loadTaskFile(api, selectedPlan.value, filePath)
  } catch (err) {
    taskFile = { path: filePath, tasks: {} }
  }

  taskFile.path = filePath
  if (!taskFile.tasks) taskFile.tasks = {}

  if (!taskFile.tasks[taskKey]) {
    taskFile.tasks[taskKey] = createEmptyTask(taskKey)
  }

  await saveTaskFile(api, selectedPlan.value, filePath, taskFile)
  await api.reloadFile(selectedPlan.value, filePath)

  tasks.value = await api.listTasksForPlan(selectedPlan.value)
  selectedFile.value = filePath
  taskStore.setTaskFile(taskFile)
  taskStore.setCurrentTaskKey(taskKey)
  await loadGraphForTask(taskKey)
}

const handleAutoLayout = () => {
  if (!currentTask.value) return
  const canvasRect = canvasRef.value?.getCanvasRect()
  autoLayout(
    { nodes: currentTask.value.steps, gates: graphStore.state.gates, edges: graphStore.state.edges },
    layoutStore.state,
    {
      width: canvasRect?.width,
      height: canvasRect?.height,
      force: true
    }
  )
  layoutStore.updateViewport({ x: 0, y: 0 })
}

const handleZoom = (action) => {
  const current = layoutStore.state.viewport?.zoom || 1
  let next = current
  if (action === 'in') next = current + 0.1
  if (action === 'out') next = current - 0.1
  if (action === 'reset') next = 1
  next = Math.min(2, Math.max(0.2, Number(next.toFixed(2))))
  layoutStore.updateViewport({ zoom: next })
}

const handlePan = (position) => {
  if (!position) return
  layoutStore.updateViewport({ x: position.x, y: position.y })
}


const startDrag = (type, event) => {
  if (event.button !== 0) return
  event.preventDefault()
  dragState.value = {
    type,
    startX: event.clientX,
    startY: event.clientY,
    leftWidth: leftWidth.value,
    rightWidth: rightWidth.value,
    topHeight: topHeight.value,
    rightTopHeight: rightTopHeight.value
  }
  document.body.classList.add('dragging')
  document.body.style.cursor = type === 'right-height' || type === 'top' ? 'row-resize' : 'col-resize'
  window.addEventListener('pointermove', handleDrag)
  window.addEventListener('pointerup', stopDrag)
}

const handleDrag = (event) => {
  if (!dragState.value) return
  const dx = event.clientX - dragState.value.startX
  const dy = event.clientY - dragState.value.startY
  const surfaceRect = surfaceRef.value?.getBoundingClientRect()
  const rightRect = rightRef.value?.getBoundingClientRect()
  const surfaceWidth = surfaceRect?.width || 1200
  const rightHeight = rightRect?.height || 520
  if (dragState.value.type === 'left') {
    const maxLeft = Math.max(minLeftWidth, surfaceWidth - rightWidth.value - minCenterWidth - splitterSize * 2)
    leftWidth.value = Math.min(Math.max(dragState.value.leftWidth + dx, minLeftWidth), maxLeft)
    return
  }

  if (dragState.value.type === 'right') {
    const maxRight = Math.max(minRightWidth, surfaceWidth - leftWidth.value - minCenterWidth - splitterSize * 2)
    rightWidth.value = Math.min(Math.max(dragState.value.rightWidth - dx, minRightWidth), maxRight)
    return
  }

  if (dragState.value.type === 'top') {
    topHeight.value = Math.max(dragState.value.topHeight + dy, minTopAreaHeight)
    return
  }

  if (dragState.value.type === 'right-height') {
    const maxTop = Math.max(minPropertyHeight, rightHeight - minValidationHeight - splitterSize)
    rightTopHeight.value = Math.min(Math.max(dragState.value.rightTopHeight + dy, minPropertyHeight), maxTop)
  }
}

const stopDrag = () => {
  dragState.value = null
  document.body.classList.remove('dragging')
  document.body.style.cursor = ''
  window.removeEventListener('pointermove', handleDrag)
  window.removeEventListener('pointerup', stopDrag)
}

const syncPanelSizes = () => {
  const surfaceRect = surfaceRef.value?.getBoundingClientRect()
  const rightRect = rightRef.value?.getBoundingClientRect()
  if (!surfaceRect) return
  const surfaceWidth = surfaceRect.width || 1200
  const rightHeight = rightRect?.height || 520
  const maxLeft = Math.max(minLeftWidth, surfaceWidth - rightWidth.value - minCenterWidth - splitterSize * 2)
  leftWidth.value = clampValue(leftWidth.value, minLeftWidth, maxLeft)

  const maxRight = Math.max(minRightWidth, surfaceWidth - leftWidth.value - minCenterWidth - splitterSize * 2)
  rightWidth.value = clampValue(rightWidth.value, minRightWidth, maxRight)

  topHeight.value = Math.max(topHeight.value, minTopAreaHeight)

  const maxTop = Math.max(minPropertyHeight, rightHeight - minValidationHeight - splitterSize)
  rightTopHeight.value = clampValue(rightTopHeight.value, minPropertyHeight, maxTop)
}

const updateNode = (patch) => {
  if (!selectedNode.value) return
  taskStore.updateNode(selectedNode.value.id, patch)
}

const updateGate = (patch) => {
  if (!selectedGate.value) return
  graphStore.updateGate(selectedGate.value.id, patch)
}

const updateTask = (patch) => {
  taskStore.updateTask(patch)
}

const removeNode = (nodeId) => {
  const targetId = nodeId || taskStore.state.selected?.id
  if (!targetId) return
  taskStore.removeNode(targetId)
  graphStore.removeEdgesForNode(targetId)
  graphStore.clearGateNodeRefs(targetId)
  layoutStore.removeNode(targetId)
  if (taskStore.state.selected.type === 'node' && taskStore.state.selected.id === targetId) {
    taskStore.state.selected = { type: 'task', id: '' }
  }
}

const removeGate = (gateId) => {
  const targetId = gateId || taskStore.state.selected?.id
  if (!targetId) return
  graphStore.removeGate(targetId)
  layoutStore.removeGate(targetId)
  if (taskStore.state.selected.type === 'gate' && taskStore.state.selected.id === targetId) {
    taskStore.state.selected = { type: 'task', id: '' }
  }
}

const runValidation = () => {
  const errors = []
  const warnings = []
  const edges = graphStore.state.edges.filter((edge) => edge.kind !== 'visual_only')
  const nodeIds = Object.keys(currentTask.value?.steps || {})
  const gateIds = Object.keys(graphStore.state.gates)
  const allIds = new Set([...nodeIds, ...gateIds])

  if (allIds.size) {
    const indegree = {}
    const outgoing = {}
    for (const id of allIds) {
      indegree[id] = 0
      outgoing[id] = []
    }
    for (const edge of edges) {
      if (!allIds.has(edge.from) || !allIds.has(edge.to)) continue
      outgoing[edge.from].push(edge.to)
      indegree[edge.to] += 1
    }
    const queue = Object.keys(indegree).filter((id) => indegree[id] === 0)
    let visited = 0
    while (queue.length) {
      const current = queue.shift()
      visited += 1
      for (const next of outgoing[current]) {
        indegree[next] -= 1
        if (indegree[next] === 0) queue.push(next)
      }
    }
    if (visited !== allIds.size) {
      errors.push({ message: '检测到依赖环', type: 'graph' })
    }
  }

  for (const gate of Object.values(graphStore.state.gates)) {
    const inputs = edges.filter((edge) => edge.to === gate.id)
    if (gate.type === 'not' && inputs.length !== 1) {
      errors.push({ message: `非门 ${gate.id} 只能有一个输入`, target: gate.id, type: 'gate' })
    }
    if ((gate.type === 'and' || gate.type === 'or') && inputs.length === 0) {
      errors.push({ message: `逻辑门 ${gate.id} 需要输入`, target: gate.id, type: 'gate' })
    }
    if (gate.type === 'when' && !gate.expr) {
      errors.push({ message: `条件门 ${gate.id} 需要表达式`, target: gate.id, type: 'gate' })
    }
    if (gate.type === 'status') {
      if (!gate.node_id || !gate.statuses || gate.statuses.length === 0) {
        errors.push({ message: `状态门 ${gate.id} 需要节点与状态列表`, target: gate.id, type: 'gate' })
      }
    }
  }

  for (const node of Object.values(currentTask.value?.steps || {})) {
    if (!node.action) {
      warnings.push({ message: `节点 ${node.id} 未设置动作`, target: node.id, type: 'node' })
    }
  }

  validationStore.setErrors(errors)
  validationStore.setWarnings(warnings)
  return errors.length === 0
}

const applyGraphToTask = () => {
  const task = currentTask.value
  if (!task) return
  for (const node of Object.values(task.steps)) {
    const expr = buildDepExprFromGraph(node.id, graphStore.state)
    taskStore.updateNode(node.id, { depends_on: expr })
  }
}

const handleSave = async () => {
  if (!selectedPlan.value || !selectedFile.value) return
  if (!runValidation()) return

  applyGraphToTask()
  await saveTaskFile(api, selectedPlan.value, selectedFile.value, taskStore.state.taskFile)
  const layoutPayload = await loadLayout(api, selectedPlan.value, selectedFile.value)
  if (!layoutPayload.tasks) layoutPayload.tasks = {}
  layoutPayload.tasks[currentTaskKey.value] = {
    nodes: layoutStore.state.nodes,
    gates: layoutStore.state.gates,
    edges: graphStore.state.edges,
    viewport: layoutStore.state.viewport
  }
  await saveLayout(api, selectedPlan.value, selectedFile.value, layoutPayload)
  await api.reloadFile(selectedPlan.value, selectedFile.value)
}

const openPreview = () => {
  applyGraphToTask()
  previewContent.value = stringifyTaskFile(taskStore.state.taskFile)
  previewOpen.value = true
}

const focusIssue = (issue) => {
  if (issue.type === 'node') {
    taskStore.state.selected = { type: 'node', id: issue.target }
  }
  if (issue.type === 'gate') {
    taskStore.state.selected = { type: 'gate', id: issue.target }
  }
}

onMounted(() => {
  loadPlans()
  syncPanelSizes()
  window.addEventListener('resize', syncPanelSizes)
})
onBeforeUnmount(() => {
  stopDrag()
  window.removeEventListener('resize', syncPanelSizes)
})
</script>

<style scoped>
.preview-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
}
.preview-panel { width: 70vw; max-height: 80vh; overflow: hidden; }
.preview-text {
  max-height: 60vh;
  overflow: auto;
  background: rgba(0, 0, 0, 0.05);
  padding: 12px;
  border-radius: 8px;
}
</style>

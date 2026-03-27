<template>
  <div class="panel">
    <div class="panel-header">
      <strong>文件编辑器</strong>
      <div class="panel-subtitle">任务文件整理与迁移</div>
    </div>
    <div class="panel-body">
      <div class="file-editor-toolbar">
        <div class="field">
          <label>方案</label>
          <select class="select" v-model="selectedPlan" @change="refreshPlan">
            <option value="" disabled>请选择方案</option>
            <option v-for="plan in plans" :key="plan.name" :value="plan.name">
              {{ plan.name }}
            </option>
          </select>
        </div>
        <div class="field">
          <label>文件搜索</label>
          <input class="input" v-model="fileFilter" placeholder="输入路径关键字" />
        </div>
        <div class="field">
          <label>任务搜索</label>
          <input class="input" v-model="taskFilter" placeholder="输入任务名或标题" />
        </div>
      </div>

      <div class="file-editor-grid" ref="gridRef">
        <div class="panel file-panel" :style="{ width: `${leftWidth}px` }">
          <div class="panel-header">
            <strong>文件</strong>
            <button class="btn btn-ghost btn-mini" @click="openModal('create-file')">新建文件</button>
          </div>
          <div class="panel-body">
            <div v-if="!filteredFiles.length" class="empty">暂无文件</div>
            <button
              v-for="file in filteredFiles"
              :key="file.path"
              class="file-item"
              :class="{ active: file.path === selectedFile }"
              @click="selectFile(file.path)"
            >
              <span class="tag">YAML</span>
              <div class="meta">
                <div class="title">{{ file.path }}</div>
                <div class="sub">任务 {{ file.count }}</div>
              </div>
            </button>
          </div>
        </div>

        <div class="file-splitter" @pointerdown="startDrag('left', $event)"></div>

        <div class="panel file-panel">
          <div class="panel-header">
            <strong>任务</strong>
            <div class="panel-actions">
              <button class="btn btn-ghost btn-mini" @click="selectAllInFile">全选</button>
              <button class="btn btn-ghost btn-mini" @click="clearSelection">清空</button>
            </div>
          </div>
          <div class="panel-body">
            <div v-if="!selectedFile" class="empty">请先选择一个任务文件</div>
            <div v-else-if="!filteredTasks.length" class="empty">当前文件暂无任务</div>
            <button
              v-for="task in filteredTasks"
              :key="taskId(task)"
              class="task-item"
              :class="{ active: selectedTaskIds.includes(taskId(task)) }"
              @click="toggleSelection(selectedTaskIds, taskId(task))"
            >
              <input type="checkbox" :checked="selectedTaskIds.includes(taskId(task))" />
              <div class="meta">
                <div class="title">{{ task.title }}</div>
                <div class="sub">{{ task.taskKey }}</div>
              </div>
            </button>
          </div>
        </div>

        <div class="file-splitter" @pointerdown="startDrag('right', $event)"></div>

        <div class="panel file-panel" :style="{ width: `${rightWidth}px` }">
          <div class="panel-header">
            <strong>操作</strong>
          </div>
          <div class="panel-body">
            <div class="ops-group">
              <div class="ops-title">任务操作</div>
              <button class="btn btn-ghost" @click="openModal('merge-tasks')" :disabled="!selectedPlan">
                合并任务
              </button>
              <button class="btn btn-ghost" @click="openModal('split-tasks')" :disabled="!selectedFile">
                拆分任务
              </button>
            </div>
            <div class="ops-group">
              <div class="ops-title">文件操作</div>
              <button class="btn btn-ghost" @click="openModal('transfer-file')" :disabled="!selectedFile">
                文件复制/移动
              </button>
            </div>
            <div class="summary">
              <div class="summary-item">当前方案：<strong>{{ selectedPlan || '未选择' }}</strong></div>
              <div class="summary-item">当前文件：<strong>{{ selectedFile || '未选择' }}</strong></div>
              <div class="summary-item">已选任务：<strong>{{ selectedTaskIds.length }}</strong></div>
              <div class="summary-item">冲突策略：<strong>重命名（task_2）</strong></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div v-if="activeModal" class="modal-mask" @click.self="closeModal">
    <div class="panel modal-panel">
      <div class="panel-header">
        <strong>{{ modalTitle }}</strong>
      </div>
      <div class="panel-body modal-body">
        <template v-if="activeModal === 'create-file'">
          <div class="inline-grid">
            <label>新文件路径</label>
            <input
              class="input"
              v-model="newFilePath"
              placeholder="tasks/your_path.yaml"
            />
            <div class="hint">仅创建任务文件，不会生成任务内容。</div>
          </div>
        </template>

        <template v-if="activeModal === 'merge-tasks'">
          <div class="inline-grid">
            <label>目标文件（可输入新路径）</label>
            <input class="input" v-model="mergeTargetFile" list="file-options" placeholder="tasks/target.yaml" />
            <datalist id="file-options">
              <option v-for="file in fileList" :key="file.path" :value="file.path" />
            </datalist>
          </div>
          <div class="inline-grid">
            <label>模式</label>
            <select class="select" v-model="mergeMode">
              <option value="move">移动</option>
              <option value="copy">复制</option>
            </select>
          </div>
          <div class="inline-grid">
            <label>选择要合并的任务</label>
            <div v-if="!taskGroups.length" class="empty">暂无任务可合并</div>
            <div v-else class="list">
              <div v-for="group in taskGroups" :key="group.path">
                <div class="hint">{{ group.path }}</div>
                <button
                  v-for="task in group.tasks"
                  :key="taskId(task)"
                  class="task-item"
                  :class="{ active: mergeSelectionIds.includes(taskId(task)) }"
                  @click="toggleSelection(mergeSelectionIds, taskId(task))"
                >
                  <input type="checkbox" :checked="mergeSelectionIds.includes(taskId(task))" />
                  <div class="meta">
                    <div class="title">{{ task.title }}</div>
                    <div class="sub">{{ task.taskKey }}</div>
                  </div>
                </button>
              </div>
            </div>
          </div>
          <div class="hint">冲突将自动重命名为 task_2、task_3。</div>
        </template>

        <template v-if="activeModal === 'split-tasks'">
          <div class="inline-grid">
            <label>目标文件路径</label>
            <input class="input" v-model="splitTargetPath" placeholder="tasks/new_file.yaml" />
          </div>
          <div class="inline-grid">
            <label>模式</label>
            <select class="select" v-model="splitMode">
              <option value="move">移动</option>
              <option value="copy">复制</option>
            </select>
          </div>
          <div class="inline-grid">
            <label>选择要拆分的任务</label>
            <div v-if="!selectedFileTasks.length" class="empty">当前文件无任务</div>
            <div v-else class="list">
              <button
                v-for="task in selectedFileTasks"
                :key="taskId(task)"
                class="task-item"
                :class="{ active: splitSelectionIds.includes(taskId(task)) }"
                @click="toggleSelection(splitSelectionIds, taskId(task))"
              >
                <input type="checkbox" :checked="splitSelectionIds.includes(taskId(task))" />
                <div class="meta">
                  <div class="title">{{ task.title }}</div>
                  <div class="sub">{{ task.taskKey }}</div>
                </div>
              </button>
            </div>
          </div>
          <div class="hint">拆分仅限同一方案内。</div>
        </template>

        <template v-if="activeModal === 'transfer-file'">
          <div class="inline-grid">
            <label>目标方案</label>
            <select class="select" v-model="transferTargetPlan">
              <option v-for="plan in plans" :key="plan.name" :value="plan.name">
                {{ plan.name }}
              </option>
            </select>
          </div>
          <div class="inline-grid">
            <label>目标路径</label>
            <input class="input" v-model="transferTargetPath" placeholder="tasks/target.yaml" />
          </div>
          <div class="inline-grid">
            <label>模式</label>
            <select class="select" v-model="transferMode">
              <option value="copy">复制</option>
              <option value="move">移动</option>
            </select>
          </div>
          <div class="hint">移动会清空源文件内容（保留空文件）。</div>
        </template>
      </div>
      <div class="panel-body modal-actions">
        <button class="btn btn-ghost" @click="closeModal" :disabled="processing">取消</button>
        <button class="btn btn-primary" @click="confirmModal" :disabled="processing || !canConfirm">
          {{ processing ? '处理中...' : '执行' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import '../styles/file-editor.css'
import { useTaskEditorApi } from '../composables/useTaskEditorApi.js'
import { loadTaskFile, saveTaskFile } from '../task_editor/io/yamlIO.js'
import { loadLayout, saveLayout } from '../task_editor/io/sidecarIO.js'

const api = useTaskEditorApi()

const plans = ref([])
const tasks = ref([])
const filesTree = ref({})
const selectedPlan = ref('')
const selectedFile = ref('')

const fileFilter = ref('')
const taskFilter = ref('')
const selectedTaskIds = ref([])

const activeModal = ref('')
const processing = ref(false)

const newFilePath = ref('')
const mergeTargetFile = ref('')
const mergeSelectionIds = ref([])
const mergeMode = ref('move')
const splitTargetPath = ref('')
const splitSelectionIds = ref([])
const splitMode = ref('move')
const transferTargetPlan = ref('')
const transferTargetPath = ref('')
const transferMode = ref('copy')

const gridRef = ref(null)
const leftWidth = ref(260)
const rightWidth = ref(320)
const dragState = ref(null)
const splitterSize = 8
const minLeftWidth = 220
const minRightWidth = 260
const minCenterWidth = 360

const normalizeTaskFilePath = (value) => {
  if (!value) return ''
  let path = String(value).trim().replace(/^\/+/, '').replace(/\\/g, '/')
  if (!path) return ''
  if (!path.startsWith('tasks/')) path = `tasks/${path}`
  if (!path.endsWith('.yaml') && !path.endsWith('.yml')) {
    path = `${path}.yaml`
  }
  return path
}

const deriveFilePath = (taskName) => {
  const parts = taskName.split('/')
  if (parts.length === 1) {
    return `tasks/${parts[0]}.yaml`
  }
  const filePath = parts.slice(0, -1).join('/')
  return `tasks/${filePath}.yaml`
}

const taskId = (task) => `${task.filePath}::${task.taskKey}`

const flattenTree = (tree, prefix = '') => {
  const output = []
  for (const [name, child] of Object.entries(tree || {})) {
    const nextPath = prefix ? `${prefix}/${name}` : name
    if (child && typeof child === 'object') {
      output.push(...flattenTree(child, nextPath))
    } else {
      output.push(nextPath)
    }
  }
  return output
}

const taskRecords = computed(() => {
  return (tasks.value || [])
    .map((task) => {
      const taskName = task.task_name_in_plan || task.task_name || ''
      const filePath = deriveFilePath(taskName)
      const taskKey = taskName.split('/').slice(-1)[0]
      return {
        taskName,
        taskKey,
        filePath,
        title: task.meta?.title || taskKey
      }
    })
    .filter((task) => task.taskKey)
})

const tasksByFile = computed(() => {
  const map = new Map()
  for (const task of taskRecords.value) {
    if (!map.has(task.filePath)) map.set(task.filePath, [])
    map.get(task.filePath).push(task)
  }
  for (const list of map.values()) {
    list.sort((a, b) => a.taskKey.localeCompare(b.taskKey))
  }
  return map
})

const taskLookup = computed(() => {
  const map = new Map()
  for (const task of taskRecords.value) {
    map.set(taskId(task), task)
  }
  return map
})

const taskFilesFromTree = computed(() => {
  const files = flattenTree(filesTree.value)
  return files.filter((path) => {
    const normalized = path.replace(/\\/g, '/')
    if (!normalized.startsWith('tasks/')) return false
    if (normalized.includes('/.ui/')) return false
    return normalized.endsWith('.yaml') || normalized.endsWith('.yml')
  })
})

const fileList = computed(() => {
  const files = new Set(taskFilesFromTree.value)
  for (const key of tasksByFile.value.keys()) {
    files.add(key)
  }
  return Array.from(files)
    .sort((a, b) => a.localeCompare(b))
    .map((path) => ({
      path,
      count: tasksByFile.value.get(path)?.length || 0
    }))
})

const filteredFiles = computed(() => {
  const keyword = fileFilter.value.trim().toLowerCase()
  if (!keyword) return fileList.value
  return fileList.value.filter((file) => file.path.toLowerCase().includes(keyword))
})

const selectedFileTasks = computed(() => {
  return tasksByFile.value.get(selectedFile.value) || []
})

const filteredTasks = computed(() => {
  const keyword = taskFilter.value.trim().toLowerCase()
  const list = selectedFileTasks.value
  if (!keyword) return list
  return list.filter((task) => {
    return task.taskKey.toLowerCase().includes(keyword) || task.title.toLowerCase().includes(keyword)
  })
})

const taskGroups = computed(() => {
  return Array.from(tasksByFile.value.entries())
    .map(([path, list]) => ({ path, tasks: list }))
    .sort((a, b) => a.path.localeCompare(b.path))
})

const modalTitle = computed(() => {
  const map = {
    'create-file': '创建任务文件',
    'merge-tasks': '合并任务',
    'split-tasks': '拆分任务',
    'transfer-file': '文件复制/移动'
  }
  return map[activeModal.value] || ''
})

const canConfirm = computed(() => {
  if (activeModal.value === 'create-file') {
    return !!normalizeTaskFilePath(newFilePath.value)
  }
  if (activeModal.value === 'merge-tasks') {
    return !!normalizeTaskFilePath(mergeTargetFile.value) && mergeSelectionIds.value.length > 0
  }
  if (activeModal.value === 'split-tasks') {
    const target = normalizeTaskFilePath(splitTargetPath.value)
    return !!target && target !== selectedFile.value && splitSelectionIds.value.length > 0
  }
  if (activeModal.value === 'transfer-file') {
    return !!transferTargetPlan.value && !!normalizeTaskFilePath(transferTargetPath.value)
  }
  return false
})

const toggleSelection = (target, id) => {
  const set = new Set(target.value)
  if (set.has(id)) set.delete(id)
  else set.add(id)
  target.value = Array.from(set)
}

const selectFile = (path) => {
  selectedFile.value = path
  selectedTaskIds.value = []
}

const selectAllInFile = () => {
  selectedTaskIds.value = selectedFileTasks.value.map((task) => taskId(task))
}

const clearSelection = () => {
  selectedTaskIds.value = []
}

const openModal = (type) => {
  activeModal.value = type
  processing.value = false
  if (type === 'create-file') {
    newFilePath.value = ''
  }
  if (type === 'merge-tasks') {
    mergeTargetFile.value = selectedFile.value || fileList.value[0]?.path || ''
    mergeSelectionIds.value = [...selectedTaskIds.value]
    mergeMode.value = 'move'
  }
  if (type === 'split-tasks') {
    splitTargetPath.value = ''
    splitSelectionIds.value = [...selectedTaskIds.value]
    splitMode.value = 'move'
  }
  if (type === 'transfer-file') {
    transferTargetPlan.value = selectedPlan.value || plans.value[0]?.name || ''
    transferTargetPath.value = selectedFile.value || ''
    transferMode.value = 'copy'
  }
}

const closeModal = () => {
  activeModal.value = ''
  processing.value = false
}

const loadTaskFileSafe = async (planName, path) => {
  try {
    return await loadTaskFile(api, planName, path)
  } catch (err) {
    return { path, tasks: {} }
  }
}

const loadLayoutSafe = async (planName, path) => {
  const layout = await loadLayout(api, planName, path)
  layout.tasks = layout.tasks || {}
  layout.file = path
  return layout
}

const clone = (value) => JSON.parse(JSON.stringify(value))

const resolveTaskKey = (baseKey, existingKeys) => {
  const clean = baseKey || 'task'
  if (!existingKeys.has(clean)) {
    existingKeys.add(clean)
    return clean
  }
  let index = 2
  let next = `${clean}_${index}`
  while (existingKeys.has(next)) {
    index += 1
    next = `${clean}_${index}`
  }
  existingKeys.add(next)
  return next
}

const refreshPlan = async () => {
  if (!selectedPlan.value) return
  const [tasksResult, treeResult] = await Promise.allSettled([
    api.listTasksForPlan(selectedPlan.value),
    api.getPlanFilesTree(selectedPlan.value)
  ])
  tasks.value = tasksResult.status === 'fulfilled' ? tasksResult.value : []
  filesTree.value = treeResult.status === 'fulfilled' ? treeResult.value : {}
  if (selectedFile.value && fileList.value.some((file) => file.path === selectedFile.value)) {
    return
  }
  selectedFile.value = fileList.value[0]?.path || ''
  selectedTaskIds.value = []
}

const createFile = async () => {
  const path = normalizeTaskFilePath(newFilePath.value)
  if (!path || !selectedPlan.value) return
  await api.saveFileContent(selectedPlan.value, path, '{}\n')
  await api.reloadFile(selectedPlan.value, path)
  await refreshPlan()
  selectedFile.value = path
}

const applyMergeTasks = async () => {
  if (!selectedPlan.value) return
  const targetPath = normalizeTaskFilePath(mergeTargetFile.value)
  const selection = mergeSelectionIds.value
    .map((id) => taskLookup.value.get(id))
    .filter(Boolean)
    .filter((task) => task.filePath !== targetPath)
  if (!targetPath || selection.length === 0) return

  const targetFile = await loadTaskFileSafe(selectedPlan.value, targetPath)
  const targetLayout = await loadLayoutSafe(selectedPlan.value, targetPath)
  const existingKeys = new Set(Object.keys(targetFile.tasks || {}))

  const sourceMap = new Map()
  const getSource = async (path) => {
    if (!sourceMap.has(path)) {
      const file = await loadTaskFileSafe(selectedPlan.value, path)
      const layout = await loadLayoutSafe(selectedPlan.value, path)
      sourceMap.set(path, { file, layout, changed: false })
    }
    return sourceMap.get(path)
  }

  for (const task of selection) {
    const source = await getSource(task.filePath)
    const taskDef = source.file.tasks?.[task.taskKey]
    if (!taskDef) continue
    const newKey = resolveTaskKey(task.taskKey, existingKeys)
    targetFile.tasks[newKey] = clone(taskDef)
    if (source.layout.tasks?.[task.taskKey]) {
      targetLayout.tasks[newKey] = clone(source.layout.tasks[task.taskKey])
    }
    if (mergeMode.value === 'move') {
      delete source.file.tasks[task.taskKey]
      delete source.layout.tasks[task.taskKey]
      source.changed = true
    }
  }

  await saveTaskFile(api, selectedPlan.value, targetPath, targetFile)
  await saveLayout(api, selectedPlan.value, targetPath, targetLayout)
  await api.reloadFile(selectedPlan.value, targetPath)

  for (const [path, payload] of sourceMap.entries()) {
    if (!payload.changed || path === targetPath) continue
    await saveTaskFile(api, selectedPlan.value, path, payload.file)
    await saveLayout(api, selectedPlan.value, path, payload.layout)
    await api.reloadFile(selectedPlan.value, path)
  }
  await refreshPlan()
}

const applySplitTasks = async () => {
  if (!selectedPlan.value || !selectedFile.value) return
  const targetPath = normalizeTaskFilePath(splitTargetPath.value)
  if (!targetPath || targetPath === selectedFile.value) return
  const selection = splitSelectionIds.value
    .map((id) => taskLookup.value.get(id))
    .filter(Boolean)
    .filter((task) => task.filePath === selectedFile.value)
  if (selection.length === 0) return

  const sourceFile = await loadTaskFileSafe(selectedPlan.value, selectedFile.value)
  const sourceLayout = await loadLayoutSafe(selectedPlan.value, selectedFile.value)
  const targetFile = await loadTaskFileSafe(selectedPlan.value, targetPath)
  const targetLayout = await loadLayoutSafe(selectedPlan.value, targetPath)
  const existingKeys = new Set(Object.keys(targetFile.tasks || {}))

  for (const task of selection) {
    const taskDef = sourceFile.tasks?.[task.taskKey]
    if (!taskDef) continue
    const newKey = resolveTaskKey(task.taskKey, existingKeys)
    targetFile.tasks[newKey] = clone(taskDef)
    if (sourceLayout.tasks?.[task.taskKey]) {
      targetLayout.tasks[newKey] = clone(sourceLayout.tasks[task.taskKey])
    }
    if (splitMode.value === 'move') {
      delete sourceFile.tasks[task.taskKey]
      delete sourceLayout.tasks[task.taskKey]
    }
  }

  await saveTaskFile(api, selectedPlan.value, targetPath, targetFile)
  await saveLayout(api, selectedPlan.value, targetPath, targetLayout)
  await api.reloadFile(selectedPlan.value, targetPath)

  if (splitMode.value === 'move') {
    await saveTaskFile(api, selectedPlan.value, selectedFile.value, sourceFile)
    await saveLayout(api, selectedPlan.value, selectedFile.value, sourceLayout)
    await api.reloadFile(selectedPlan.value, selectedFile.value)
  }
  await refreshPlan()
}

const applyFileTransfer = async () => {
  if (!selectedPlan.value || !selectedFile.value) return
  const targetPlan = transferTargetPlan.value
  const targetPath = normalizeTaskFilePath(transferTargetPath.value)
  if (!targetPlan || !targetPath) return

  const raw = await api.getFileContent(selectedPlan.value, selectedFile.value)
  await api.saveFileContent(targetPlan, targetPath, raw)
  await api.reloadFile(targetPlan, targetPath)

  const layout = await loadLayoutSafe(selectedPlan.value, selectedFile.value)
  layout.file = targetPath
  await saveLayout(api, targetPlan, targetPath, layout)

  if (transferMode.value === 'move') {
    await api.saveFileContent(selectedPlan.value, selectedFile.value, '{}\n')
    await api.reloadFile(selectedPlan.value, selectedFile.value)
    const emptyLayout = { version: 1, file: selectedFile.value, tasks: {} }
    await saveLayout(api, selectedPlan.value, selectedFile.value, emptyLayout)
  }
  await refreshPlan()
}

const confirmModal = async () => {
  if (!canConfirm.value) return
  processing.value = true
  try {
    if (activeModal.value === 'create-file') await createFile()
    if (activeModal.value === 'merge-tasks') await applyMergeTasks()
    if (activeModal.value === 'split-tasks') await applySplitTasks()
    if (activeModal.value === 'transfer-file') await applyFileTransfer()
    closeModal()
  } finally {
    processing.value = false
  }
}

const startDrag = (type, event) => {
  if (event.button !== 0) return
  event.preventDefault()
  dragState.value = {
    type,
    startX: event.clientX,
    leftWidth: leftWidth.value,
    rightWidth: rightWidth.value
  }
  document.body.classList.add('dragging')
  document.body.style.cursor = 'col-resize'
  window.addEventListener('pointermove', handleDrag)
  window.addEventListener('pointerup', stopDrag)
}

const handleDrag = (event) => {
  if (!dragState.value) return
  const dx = event.clientX - dragState.value.startX
  const gridWidth = gridRef.value?.getBoundingClientRect().width || 1200
  if (dragState.value.type === 'left') {
    const maxLeft = Math.max(minLeftWidth, gridWidth - rightWidth.value - minCenterWidth - splitterSize * 2)
    leftWidth.value = Math.min(Math.max(dragState.value.leftWidth + dx, minLeftWidth), maxLeft)
    return
  }
  if (dragState.value.type === 'right') {
    const maxRight = Math.max(minRightWidth, gridWidth - leftWidth.value - minCenterWidth - splitterSize * 2)
    rightWidth.value = Math.min(Math.max(dragState.value.rightWidth - dx, minRightWidth), maxRight)
  }
}

const stopDrag = () => {
  dragState.value = null
  document.body.classList.remove('dragging')
  document.body.style.cursor = ''
  window.removeEventListener('pointermove', handleDrag)
  window.removeEventListener('pointerup', stopDrag)
}

const loadPlans = async () => {
  plans.value = await api.listPlans()
  if (!selectedPlan.value && plans.value.length) {
    selectedPlan.value = plans.value[0].name
  }
  if (selectedPlan.value) {
    await refreshPlan()
  }
}

onMounted(loadPlans)
</script>

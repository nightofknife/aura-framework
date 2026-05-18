<template>
  <div class="page-shell execute-page">
    <div class="page-heading">
      <div class="heading-block">
        <h1 class="page-title">执行台</h1>
      </div>
      <div class="heading-actions">
        <span class="pill" :class="systemOnline ? 'pill-green' : 'pill-red'">
          {{ systemOnline ? '后端在线' : '后端离线' }}
        </span>
        <span class="pill" :class="systemRunning ? 'pill-running' : 'pill-gray'">
          {{ systemRunning ? '调度运行中' : '调度已停止' }}
        </span>
        <button class="btn btn-ghost" @click="refreshAll">
          <RefreshCw class="icon" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="pageError" class="notice notice-danger">{{ pageError }}</div>

    <section class="execute-grid">
      <aside class="panel task-picker">
        <header class="panel-header">
          <div>
            <span class="panel-kicker">任务选择</span>
            <strong>计划与任务</strong>
          </div>
          <span class="pill pill-gray">{{ filteredTasks.length }}</span>
        </header>

        <div class="panel-body stack">
          <select v-model="selectedPlan" class="select" @change="loadTasksForSelectedPlan">
            <option v-for="plan in plans" :key="plan.name" :value="plan.name">
              {{ plan.name }} ({{ plan.taskCount }})
            </option>
          </select>

          <label class="search-box">
            <Search class="icon" />
            <input v-model="query" class="input" placeholder="搜索任务名称或引用" />
          </label>

          <div class="task-list">
            <button
              v-for="task in filteredTasks"
              :key="task.key"
              class="task-row"
              :class="{ 'is-active': task.key === selectedTaskKey }"
              @click="selectedTaskKey = task.key"
            >
              <span>
                <strong>{{ task.title }}</strong>
                <code>{{ task.taskRef }}</code>
              </span>
              <span v-if="task.entryPoint" class="pill pill-gray">{{ task.entryPoint }}</span>
            </button>

            <div v-if="loadingTasks" class="empty-state">正在加载任务...</div>
            <div v-else-if="!filteredTasks.length" class="empty-state">没有匹配的任务。</div>
          </div>
        </div>
      </aside>

      <section class="panel task-config">
        <header class="panel-header">
          <div>
            <span class="panel-kicker">任务配置</span>
            <strong>{{ selectedTask?.title || '未选择任务' }}</strong>
          </div>
          <span v-if="selectedTask" class="pill pill-gray">{{ selectedTask.planName }}</span>
        </header>

        <div class="panel-body config-body">
          <template v-if="selectedTask">
            <div class="task-summary">
              <code>{{ selectedTask.taskRef }}</code>
              <p v-if="selectedTask.description">{{ selectedTask.description }}</p>
            </div>

            <div v-if="taskInputs.length" class="input-stack">
              <InputFieldRenderer
                v-for="input in taskInputs"
                :key="input.name"
                :schema="input"
                v-model="inputModel[input.name]"
              />
            </div>
            <div v-else class="empty-state">该任务没有声明输入字段。</div>

            <div class="dispatch-bar">
              <button class="btn btn-primary" :disabled="dispatching || !systemOnline || !apiTokenConfigured" @click="submitTask">
                <Play class="icon" />
                {{ dispatching ? '提交中...' : '执行任务' }}
              </button>
              <span v-if="!systemOnline" class="hint">后端离线时不可提交。</span>
              <span v-else-if="!apiTokenConfigured" class="hint">Local API token required. Configure it in Settings.</span>
            </div>
          </template>

          <div v-else class="empty-state">请选择一个任务。</div>
        </div>
      </section>

      <aside class="runtime-column">
        <section class="panel">
          <header class="panel-header">
            <div>
              <span class="panel-kicker">提交反馈</span>
              <strong>最近提交</strong>
            </div>
          </header>
          <div class="panel-body stack">
            <div v-if="lastDispatch" class="dispatch-card">
              <div class="dispatch-card__head">
                <span class="pill" :class="statusClass(lastDispatch.status)">{{ statusLabel(lastDispatch.status) }}</span>
                <code>{{ lastDispatch.cid || lastDispatch.traceId || '--' }}</code>
              </div>
              <p v-if="lastDispatch.message">{{ lastDispatch.message }}</p>
              <button v-if="lastDispatch.cid" class="btn btn-ghost btn-sm" @click="openRun({ cid: lastDispatch.cid })">
                打开运行详情
              </button>
            </div>
            <div v-else class="empty-state">暂无提交结果。</div>
          </div>
        </section>

        <section class="panel">
          <header class="panel-header">
            <div>
              <span class="panel-kicker">运行中</span>
              <strong>Active Runs</strong>
            </div>
            <span class="pill pill-gray">{{ activeRuns.length }}</span>
          </header>
          <div class="panel-body run-list">
            <button v-for="run in activeRuns" :key="run.key" class="run-row" @click="openRun(run)">
              <span>
                <strong>{{ run.taskRef || run.title }}</strong>
                <code>{{ run.shortCid }}</code>
              </span>
              <span class="pill" :class="statusClass(run.status)">{{ statusLabel(run.status) }}</span>
            </button>
            <div v-if="!activeRuns.length" class="empty-state">当前没有运行中的任务。</div>
          </div>
        </section>

        <section class="panel">
          <header class="panel-header">
            <div>
              <span class="panel-kicker">最近记录</span>
              <strong>Recent Runs</strong>
            </div>
          </header>
          <div class="panel-body run-list">
            <button v-for="run in recentRuns.slice(0, 8)" :key="run.key" class="run-row" @click="openRun(run)">
              <span>
                <strong>{{ run.taskRef || run.title }}</strong>
                <small>{{ formatTime(run.startedAtMs) }}</small>
              </span>
              <span class="pill" :class="statusClass(run.status)">{{ statusLabel(run.status) }}</span>
            </button>
            <div v-if="!recentRuns.length" class="empty-state">暂无运行记录。</div>
          </div>
        </section>
      </aside>
    </section>

    <RunDetailDrawer :open="drawerOpen" :run="currentRun" @close="drawerOpen = false" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { Play, RefreshCw, Search } from 'lucide-vue-next'

import InputFieldRenderer from '../components/InputFieldRenderer.vue'
import RunDetailDrawer from '../components/RunDetailDrawer.vue'
import { listPlans, listTasks } from '../api/plans.js'
import { getHealth } from '../api/system.js'
import { dispatchTask } from '../api/tasks.js'
import { getRunDetail, listActiveRuns, listRunHistory } from '../api/runs.js'
import { errorMessage } from '../api/errors.js'
import { useApiTokenStatus } from '../composables/useApiToken.js'
import { useToasts } from '../composables/useToasts.js'
import { getGuiConfig } from '../config.js'
import { buildDefaultFromSchema, cloneInputs, normalizeInputSchema } from '../utils/inputSchema.js'

const cfg = getGuiConfig()
const { push: toast } = useToasts()
const { hasToken: apiTokenConfigured } = useApiTokenStatus()

const plans = ref([])
const tasks = ref([])
const selectedPlan = ref('')
const selectedTaskKey = ref('')
const query = ref('')
const loadingTasks = ref(false)
const dispatching = ref(false)
const pageError = ref('')
const system = ref(null)
const activeRuns = ref([])
const recentRuns = ref([])
const lastDispatch = ref(null)
const currentRun = ref(null)
const drawerOpen = ref(false)
const inputModel = reactive({})

const systemOnline = computed(() => system.value?.status === 'ok')
const systemRunning = computed(() => !!system.value?.isRunning)

const filteredTasks = computed(() => {
  const q = query.value.trim().toLowerCase()
  return tasks.value.filter((task) => {
    if (!q) return true
    return `${task.title} ${task.taskRef} ${task.description}`.toLowerCase().includes(q)
  })
})

const selectedTask = computed(() =>
  tasks.value.find((task) => task.key === selectedTaskKey.value) ||
  filteredTasks.value[0] ||
  null
)

const taskInputs = computed(() =>
  (selectedTask.value?.inputs || []).map((input) => normalizeInputSchema(input))
)

watch(selectedTask, (task) => {
  resetInputModel(task)
})

async function refreshAll() {
  await Promise.all([refreshSystem(), refreshRuns(), refreshCatalog()])
}

async function refreshCatalog() {
  try {
    const loadedPlans = await listPlans()
    plans.value = loadedPlans
    if (!loadedPlans.some((plan) => plan.name === selectedPlan.value)) {
      selectedPlan.value = loadedPlans.find((plan) => plan.taskCount > 0)?.name || loadedPlans[0]?.name || ''
    }
    await loadTasksForSelectedPlan()
    pageError.value = ''
  } catch (error) {
    plans.value = []
    tasks.value = []
    selectedTaskKey.value = ''
    pageError.value = errorMessage(error, '任务目录加载失败。')
  }
}

async function loadTasksForSelectedPlan() {
  if (!selectedPlan.value) {
    tasks.value = []
    selectedTaskKey.value = ''
    return
  }
  loadingTasks.value = true
  try {
    const loadedTasks = await listTasks(selectedPlan.value)
    tasks.value = loadedTasks
    if (!loadedTasks.some((task) => task.key === selectedTaskKey.value)) {
      selectedTaskKey.value = loadedTasks[0]?.key || ''
    }
  } catch (error) {
    tasks.value = []
    selectedTaskKey.value = ''
    pageError.value = errorMessage(error, '任务加载失败。')
  } finally {
    loadingTasks.value = false
  }
}

async function refreshSystem() {
  try {
    system.value = await getHealth()
  } catch {
    system.value = { status: 'offline', isRunning: false }
  }
}

async function refreshRuns() {
  const [active, history] = await Promise.all([
    listActiveRuns().catch(() => []),
    listRunHistory({ limit: 30 }).catch(() => []),
  ])
  activeRuns.value = active
  recentRuns.value = history
}

function resetInputModel(task) {
  for (const key of Object.keys(inputModel)) {
    delete inputModel[key]
  }
  if (!task) return
  const defaults = cloneInputs(task.defaults || {}) || {}
  for (const input of task.inputs || []) {
    const normalized = normalizeInputSchema(input)
    if (!normalized.name) continue
    inputModel[normalized.name] = Object.prototype.hasOwnProperty.call(defaults, normalized.name)
      ? defaults[normalized.name]
      : buildDefaultFromSchema(normalized)
  }
}

async function submitTask() {
  if (!selectedTask.value || dispatching.value) return
  if (!apiTokenConfigured.value) {
    toast({
      title: 'Local API token required',
      message: 'Open Settings and paste logs/local_api_token before dispatching tasks.',
      type: 'error',
    })
    return
  }
  dispatching.value = true
  try {
    const result = await dispatchTask({
      planName: selectedTask.value.planName,
      taskRef: selectedTask.value.taskRef,
      inputs: cloneInputs(inputModel) || {},
    })
    lastDispatch.value = result
    toast({
      title: '任务已提交',
      message: result.cid ? `CID: ${result.cid}` : result.message,
      type: 'success',
    })
    await refreshRuns()
  } catch (error) {
    const message = errorMessage(error, '任务提交失败。')
    toast({ title: '任务提交失败', message, type: 'error' })
    lastDispatch.value = { status: 'failed', message }
  } finally {
    dispatching.value = false
  }
}

async function openRun(run) {
  if (!run?.cid) return
  try {
    currentRun.value = await getRunDetail(run.cid)
  } catch {
    currentRun.value = run
  }
  drawerOpen.value = true
}

function statusClass(status) {
  const value = String(status || '').toLowerCase()
  if (value === 'success') return 'pill-green'
  if (value === 'failed') return 'pill-red'
  if (value === 'running') return 'pill-running'
  if (value === 'cancelled') return 'pill-gray'
  return 'pill-queued'
}

function statusLabel(status) {
  const labels = {
    queued: '排队',
    running: '运行中',
    success: '成功',
    failed: '失败',
    cancelled: '已取消',
    unknown: '未知',
  }
  return labels[status] || status || '未知'
}

function formatTime(ms) {
  if (!ms) return '--'
  return new Date(ms).toLocaleString('zh-CN', { hour12: false })
}

let pollTimer = null

onMounted(async () => {
  await refreshAll()
  pollTimer = window.setInterval(() => {
    refreshSystem()
    refreshRuns()
  }, cfg?.api?.status_poll_ms || 3000)
})

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<style scoped>
.execute-grid {
  display: grid;
  grid-template-columns: minmax(220px, 0.82fr) minmax(300px, 1.14fr) minmax(240px, 0.86fr);
  gap: 14px;
  align-items: start;
}

.task-picker,
.task-config,
.runtime-column {
  min-width: 0;
}

.search-box {
  position: relative;
  display: block;
}

.search-box .icon {
  position: absolute;
  top: 11px;
  left: 10px;
  color: var(--text-muted);
}

.search-box .input {
  padding-left: 34px;
}

.task-list,
.run-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-row,
.run-row {
  display: flex;
  width: 100%;
  min-width: 0;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  padding: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-surface-2);
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
}

.task-row:hover,
.run-row:hover,
.task-row.is-active {
  border-color: var(--border-strong);
  background: var(--bg-elevated);
}

.task-row.is-active {
  box-shadow: inset 3px 0 0 var(--accent);
}

.task-row > span:first-child,
.run-row > span:first-child {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
}

.task-row strong,
.run-row strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-row small {
  color: var(--text-muted);
  font-size: 12px;
}

.config-body {
  display: flex;
  min-height: 540px;
  flex-direction: column;
  gap: 16px;
}

.task-summary {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-summary p {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.55;
}

.input-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.dispatch-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-top: auto;
  padding-top: 14px;
  border-top: 1px solid var(--border-subtle);
}

.runtime-column {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.dispatch-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.dispatch-card__head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.dispatch-card p {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.5;
}

.notice {
  padding: 10px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
}

.notice-danger {
  border-color: rgba(239, 91, 91, 0.34);
  background: var(--danger-soft);
  color: #ffb4b4;
}

@media (max-width: 1180px) {
  .execute-grid {
    grid-template-columns: minmax(220px, 0.8fr) minmax(300px, 1fr);
  }

  .runtime-column {
    grid-column: 1 / -1;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>

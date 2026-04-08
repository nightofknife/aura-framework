<template>
  <div class="page-shell execute-page">
    <section class="desk-header">
      <div class="desk-header__copy">
        <span class="eyebrow">Industrial Expedition Table</span>
        <h1 class="page-title">Execute</h1>
        <p class="page-subtitle">
          A single task desk for picking mission shards, arranging a dispatch order, and handing work over to the backend rail.
        </p>
      </div>

      <div class="desk-header__stats">
        <div class="desk-stat">
          <span class="desk-stat__label">catalog</span>
          <strong class="desk-stat__value">{{ filteredTasks.length }}</strong>
        </div>
        <div class="desk-stat">
          <span class="desk-stat__label">staged</span>
          <strong class="desk-stat__value">{{ guiItems.length }}</strong>
        </div>
        <div class="desk-stat">
          <span class="desk-stat__label">queue</span>
          <strong class="desk-stat__value">{{ queueOverview.ready_count || readyQueue.length }}</strong>
        </div>
        <div class="desk-stat">
          <span class="desk-stat__label">live</span>
          <strong class="desk-stat__value">{{ activeRuns.length }}</strong>
        </div>
      </div>
    </section>

    <section class="mission-desk">
      <div class="mission-desk__plate mission-desk__plate--catalog">
        <header class="desk-pane__head">
          <div>
            <span class="desk-pane__kicker">Task Fragments</span>
            <strong class="desk-pane__title">Catalog</strong>
          </div>
          <span class="pill" :class="engineRunning ? 'pill-running' : 'pill-red'">
            {{ engineRunning ? 'backend online' : 'backend offline' }}
          </span>
        </header>

        <div class="catalog-controls">
          <select v-model="selectedPlan" class="select">
            <option v-for="plan in plans" :key="plan.name" :value="plan.name">{{ plan.name }}</option>
          </select>
          <input v-model="query" class="input" placeholder="Search task title or ref" />
        </div>

        <div class="catalog-pile">
          <TaskMiniCard
            v-for="task in filteredTasks"
            :key="task.key"
            :title="task.title"
            :description="task.description"
            :plan="task.plan_name"
            :tag="task.meta?.entry_point || task.meta?.concurrency"
            :starred="favSet.has(task.key)"
            @select="openConfig(task)"
            @toggle-fav="toggleFav(task.key)"
          />
        </div>

        <div v-if="!filteredTasks.length" class="empty-state">No task fragments match the active plan and search input.</div>
      </div>

      <div class="mission-desk__plate mission-desk__plate--stage">
        <header class="desk-pane__head">
          <div>
            <span class="desk-pane__kicker">Local Arrangement</span>
            <strong class="desk-pane__title">Desk Route</strong>
          </div>
          <div class="toolbar">
            <button class="btn btn-ghost" @click="clearGuiQueue" :disabled="!guiItems.length">Clear</button>
            <button class="btn btn-primary" @click="pushAllGui" :disabled="!guiItems.length || !engineRunning">Dispatch All</button>
          </div>
        </header>

        <div class="stage-note">
          <span class="stage-note__tag">manual composition</span>
          <p>Arrange the route here before it crosses into the scheduler. Each piece should read like a physical mission board placed on the table.</p>
        </div>

        <div class="stage-route">
          <article v-for="(item, index) in guiItems" :key="item.id" class="route-board">
            <div class="route-board__number">{{ String(index + 1).padStart(2, '0') }}</div>

            <div class="route-board__body">
              <div class="route-board__head">
                <div>
                  <strong class="route-board__plan">{{ item.plan }}</strong>
                  <div class="route-board__task">{{ item.task }}</div>
                </div>
                <span class="pill" :class="guiStatusClass(item.status)">{{ guiStatusLabel(item.status) }}</span>
              </div>

              <div class="route-board__rail"></div>

              <div class="route-board__actions">
                <button class="btn btn-ghost btn-sm" @click="moveGui(item.id, 'up')" :disabled="index === 0">Raise</button>
                <button class="btn btn-ghost btn-sm" @click="moveGui(item.id, 'down')" :disabled="index === guiItems.length - 1">Lower</button>
                <button class="btn btn-ghost btn-sm" @click="pushToBackend(item)" :disabled="!engineRunning">Send</button>
                <button class="btn btn-danger btn-sm" @click="removeGui(item.id)">Remove</button>
              </div>
            </div>
          </article>

          <div v-if="!guiItems.length" class="stage-empty">
            <span class="stage-empty__stamp">STAGING EMPTY</span>
            <p>Select a task shard on the left to place the first board on the desk.</p>
          </div>
        </div>
      </div>

      <div class="mission-desk__plate mission-desk__plate--runtime">
        <section class="runtime-section">
          <header class="desk-pane__head">
            <div>
              <span class="desk-pane__kicker">Backend Rail</span>
              <strong class="desk-pane__title">Queued</strong>
            </div>
            <div class="toolbar">
              <button class="btn btn-ghost btn-sm" @click="refreshQueue">Refresh</button>
              <button class="btn btn-ghost btn-sm" @click="clearQueue" :disabled="!readyQueue.length">Clear</button>
            </div>
          </header>

          <div class="runtime-summary">
            <span class="pill pill-queued">ready {{ queueOverview.ready_count || 0 }}</span>
            <span class="pill pill-running">running {{ queueOverview.running_count || 0 }}</span>
            <span class="pill pill-gray">delayed {{ queueOverview.delayed_count || 0 }}</span>
          </div>

          <div class="runtime-stack">
            <article v-for="item in readyQueue" :key="item.cid" class="queue-ticket">
              <div class="queue-ticket__head">
                <code>{{ item.cid }}</code>
                <span class="pill pill-queued">{{ item.status || 'queued' }}</span>
              </div>
              <strong class="queue-ticket__title">{{ item.trace_label || item.plan_name }}</strong>
              <div class="queue-ticket__task">{{ item.task_ref }}</div>
              <div class="queue-ticket__meta">
                <span>{{ fmtTimeMs(item.queued_at) }}</span>
                <span>{{ item.source || 'gui' }}</span>
              </div>
              <div class="row-actions">
                <button class="btn btn-ghost btn-sm" @click="moveFront(item.cid)">Front</button>
                <button class="btn btn-danger btn-sm" @click="removeQueue(item.cid)">Delete</button>
              </div>
            </article>

            <div v-if="!readyQueue.length" class="empty-state">No queued items are currently waiting on the backend rail.</div>
          </div>
        </section>

        <section class="runtime-section runtime-section--live">
          <header class="desk-pane__head">
            <div>
              <span class="desk-pane__kicker">Live Passage</span>
              <strong class="desk-pane__title">Running</strong>
            </div>
          </header>

          <div class="runtime-stack">
            <article v-for="run in activeRuns" :key="run.cid || run.trace_id" class="live-ticket">
              <span class="live-ticket__flag"></span>
              <div class="live-ticket__body">
                <div class="live-ticket__head">
                  <strong>{{ run.plan_name }}</strong>
                  <span class="pill pill-running">{{ run.status }}</span>
                </div>
                <div class="live-ticket__task">{{ run.task_ref || run.task_name }}</div>
                <div class="live-ticket__meta">
                  <code>{{ run.cid || run.trace_id || '-' }}</code>
                  <span>{{ fmtTimeMs(run.started_at || run.startedAt) }}</span>
                </div>
              </div>
            </article>

            <div v-if="!activeRuns.length" class="empty-state">No active runs are visible on the live rail.</div>
          </div>
        </section>
      </div>
    </section>

    <ProContextPanel v-model:open="config.open" :title="config.title">
      <div class="drawer-context">
        <span class="pill">{{ config.plan }}</span>
        <code>{{ config.task }}</code>
      </div>

      <div v-if="config.meta?.description" class="hint">{{ config.meta.description }}</div>

      <div v-if="normalizedInputs.length" class="stack">
        <InputFieldRenderer
          v-for="input in normalizedInputs"
          :key="input.name"
          :schema="input"
          v-model="inputModel[input.name]"
        />
      </div>
      <div v-else class="empty-state">This task does not declare any input slots.</div>

      <div class="field">
        <label class="label">Repeat</label>
        <input v-model.number="config.repeat" class="input" type="number" min="1" max="500" />
        <span class="hint">Lay down multiple copies of the same board in one gesture.</span>
      </div>

      <div class="drawer-actions">
        <button class="btn btn-ghost" @click="config.open = false">Cancel</button>
        <button class="btn btn-primary" @click="addToGuiQueue" :disabled="!canAdd">Add To Desk</button>
      </div>
    </ProContextPanel>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import axios from 'axios'

import TaskMiniCard from '../components/TaskMiniCard.vue'
import ProContextPanel from '../components/ProContextPanel.vue'
import InputFieldRenderer from '../components/InputFieldRenderer.vue'
import { useToasts } from '../composables/useToasts.js'
import { getGuiConfig } from '../config.js'
import { useGuiQueue } from '../composables/useGuiQueue.js'
import { buildDefaultFromSchema, normalizeInputSchema } from '../utils/inputSchema.js'

const cfg = getGuiConfig()
const api = axios.create({
  baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: cfg?.api?.timeout_ms || 5000,
})

const { push: toast } = useToasts()
const { items: guiItems, add: addGui, update: updateGui, remove: removeGuiItem, clear: clearGuiItems, move: moveGuiItem } = useGuiQueue()

const plans = ref([])
const tasks = ref([])
const selectedPlan = ref('')
const query = ref('')
const engineRunning = ref(false)
const readyQueue = ref([])
const activeRuns = ref([])
const queueOverview = reactive({ ready_count: 0, running_count: 0, delayed_count: 0 })

const favKey = 'expedition.execute.favs'
const favSet = reactive(new Set(JSON.parse(localStorage.getItem(favKey) || '[]')))

const config = reactive({
  open: false,
  plan: '',
  task: '',
  title: 'Task Brief',
  meta: null,
  repeat: 1,
})

const inputModel = reactive({})

const normalizedInputs = computed(() => {
  if (!Array.isArray(config.meta?.inputs)) return []
  return config.meta.inputs
    .filter((input) => input && typeof input === 'object' && input.name)
    .map((input) => normalizeInputSchema({ ...input, label: input.label || input.name }))
})

const canAdd = computed(() => !!config.plan && !!config.task)

const filteredTasks = computed(() => {
  const activePlan = selectedPlan.value || plans.value[0]?.name || ''
  const q = query.value.trim().toLowerCase()

  return tasks.value
    .filter((task) => task.plan_name === activePlan)
    .filter((task) => {
      if (!q) return true
      return `${task.task_ref} ${task.title} ${task.description}`.toLowerCase().includes(q)
    })
    .sort((a, b) => {
      const aFav = favSet.has(a.key) ? -1 : 0
      const bFav = favSet.has(b.key) ? -1 : 0
      return aFav - bFav || a.title.localeCompare(b.title)
    })
})

async function loadPlans() {
  const { data } = await api.get('/plans')
  plans.value = Array.isArray(data) ? data : []
  if (!selectedPlan.value && plans.value.length) {
    selectedPlan.value = plans.value[0].name
  }
}

async function loadTasks() {
  const responses = await Promise.all(
    plans.value.map((plan) => api.get(`/plans/${plan.name}/tasks`).catch(() => ({ data: [] })))
  )

  tasks.value = responses.flatMap((response, index) => {
    const planName = plans.value[index]?.name || ''
    const list = Array.isArray(response.data) ? response.data : []
    return list.map((task) => ({
      key: `${planName}::${task.task_ref}`,
      plan_name: planName,
      task_ref: task.task_ref,
      title: task.meta?.title || task.task_ref,
      description: task.meta?.description || '',
      meta: task.meta || {},
    }))
  })
}

function persistFavs() {
  localStorage.setItem(favKey, JSON.stringify([...favSet]))
}

function toggleFav(key) {
  if (favSet.has(key)) favSet.delete(key)
  else favSet.add(key)
  persistFavs()
}

function resetInputModel() {
  Object.keys(inputModel).forEach((key) => delete inputModel[key])
}

function applyInputDefaults() {
  resetInputModel()
  const defaults = typeof config.meta?.defaults === 'object' && config.meta.defaults ? config.meta.defaults : {}
  normalizedInputs.value.forEach((schema) => {
    inputModel[schema.name] = defaults[schema.name] ?? buildDefaultFromSchema(schema)
  })
}

function openConfig(task) {
  config.open = true
  config.plan = task.plan_name
  config.task = task.task_ref
  config.title = task.title
  config.meta = task.meta
  config.repeat = 1
  applyInputDefaults()
}

function addToGuiQueue() {
  const repeat = Math.max(1, Math.min(500, Number(config.repeat) || 1))
  const payload = { ...inputModel }

  for (let index = 0; index < repeat; index += 1) {
    addGui({ plan: config.plan, task: config.task, inputs: payload })
  }

  config.open = false
  toast({ type: 'success', title: 'Staged', message: `${config.plan} / ${config.task} x${repeat}` })
}

async function fetchSystemStatus() {
  try {
    const { data } = await api.get('/system/status')
    engineRunning.value = !!data?.is_running
  } catch {
    engineRunning.value = false
  }
}

async function fetchQueueOverview() {
  try {
    const { data } = await api.get('/queue/overview')
    Object.assign(queueOverview, data || {})
  } catch {
    Object.assign(queueOverview, { ready_count: 0, running_count: 0, delayed_count: 0 })
  }
}

async function fetchReadyQueue() {
  try {
    const { data } = await api.get('/queue/list', { params: { state: 'ready', limit: cfg?.api?.queue_list_limit || 200 } })
    readyQueue.value = data?.items || []
  } catch {
    readyQueue.value = []
  }
}

async function fetchActiveRuns() {
  try {
    const { data } = await api.get('/runs/active')
    activeRuns.value = Array.isArray(data) ? data : []
  } catch {
    activeRuns.value = []
  }
}

async function refreshQueue() {
  await Promise.all([fetchQueueOverview(), fetchReadyQueue(), fetchActiveRuns(), fetchSystemStatus()])
}

async function refreshAll() {
  await loadPlans()
  await loadTasks()
  await refreshQueue()
}

async function pushToBackend(item) {
  updateGui(item.id, { status: 'pushing' })

  try {
    const { data } = await api.post('/tasks/dispatch', {
      plan_name: item.plan,
      task_ref: item.task,
      inputs: item.inputs || {},
    })

    updateGui(item.id, { status: 'queued', lastCid: data?.cid || null, pushedAt: Date.now() })
    removeGuiItem(item.id)
    await refreshQueue()
    toast({ type: 'success', title: 'Queued', message: `${item.plan} / ${item.task}` })
  } catch (error) {
    updateGui(item.id, { status: 'pending' })
    toast({ type: 'error', title: 'Dispatch Failed', message: error?.response?.data?.detail || error.message })
  }
}

async function pushAllGui() {
  for (const item of [...guiItems.value]) {
    // eslint-disable-next-line no-await-in-loop
    await pushToBackend(item)
  }
}

function removeGui(id) {
  removeGuiItem(id)
}

function moveGui(id, direction) {
  moveGuiItem(id, direction)
}

function clearGuiQueue() {
  clearGuiItems()
}

async function removeQueue(cid) {
  await api.delete(`/queue/${cid}`)
  await refreshQueue()
}

async function moveFront(cid) {
  await api.post(`/queue/${cid}/move-to-front`)
  await refreshQueue()
}

async function clearQueue() {
  await api.delete('/queue/clear')
  await refreshQueue()
}

function guiStatusLabel(status) {
  if (status === 'pushing') return 'dispatching'
  if (status === 'queued') return 'queued'
  return 'staged'
}

function guiStatusClass(status) {
  if (status === 'pushing') return 'pill-running'
  if (status === 'queued') return 'pill-queued'
  return 'pill-gray'
}

function fmtTimeMs(value) {
  if (!value) return '--'
  const ms = value > 1e12 ? value : value * 1000
  return new Date(ms).toLocaleString()
}

let pollTimer = null

onMounted(async () => {
  await refreshAll()
  pollTimer = window.setInterval(refreshQueue, 2000)
})

onUnmounted(() => {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<style scoped>
.execute-page {
  gap: 22px;
}

.desk-header {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) 420px;
  gap: 18px;
}

.desk-header__copy,
.desk-header__stats {
  padding: 18px;
  border: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(59, 68, 72, 0.92), rgba(39, 46, 49, 0.92));
  box-shadow: var(--shadow-plate), var(--shadow-inset);
}

.desk-header__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.desk-stat {
  display: flex;
  min-height: 88px;
  flex-direction: column;
  justify-content: space-between;
  padding: 12px 12px 10px;
  border: 1px solid rgba(224, 214, 186, 0.1);
  background: rgba(24, 30, 32, 0.42);
}

.desk-stat__label {
  color: var(--text-soft);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.desk-stat__value {
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 40px;
  letter-spacing: 0.08em;
  line-height: 0.9;
}

.mission-desk {
  position: relative;
  display: grid;
  grid-template-columns: minmax(320px, 0.95fr) minmax(420px, 1.2fr) minmax(320px, 0.95fr);
  gap: 18px;
  min-height: calc(100vh - 280px);
  padding: 24px 20px 20px;
  border: 1px solid rgba(224, 214, 186, 0.08);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.012), transparent 12%),
    repeating-linear-gradient(0deg, rgba(255, 255, 255, 0.006), rgba(255, 255, 255, 0.006) 1px, transparent 1px, transparent 5px),
    linear-gradient(180deg, #31393c, #252d30);
  box-shadow: var(--shadow-soft), var(--shadow-inset);
}

.mission-desk::before {
  content: '';
  position: absolute;
  inset: 16px;
  border: 1px solid rgba(224, 214, 186, 0.06);
  pointer-events: none;
}

.mission-desk__plate {
  position: relative;
  z-index: 1;
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: 14px;
  padding: 18px;
  border: 1px solid rgba(224, 214, 186, 0.12);
  background:
    linear-gradient(180deg, rgba(69, 79, 83, 0.95), rgba(44, 53, 56, 0.95));
  box-shadow: var(--shadow-plate), var(--shadow-inset);
}

.mission-desk__plate--catalog {
  transform: rotate(-1deg);
}

.mission-desk__plate--stage {
  transform: rotate(0.45deg);
  background:
    linear-gradient(180deg, rgba(83, 74, 55, 0.28), transparent 22%),
    linear-gradient(180deg, rgba(69, 79, 83, 0.96), rgba(44, 53, 56, 0.96));
}

.mission-desk__plate--runtime {
  transform: rotate(1deg);
}

.desk-pane__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: start;
  flex-wrap: wrap;
}

.desk-pane__kicker {
  display: block;
  color: var(--paper);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.desk-pane__title {
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 34px;
  letter-spacing: 0.08em;
  line-height: 0.9;
  text-transform: uppercase;
}

.catalog-controls {
  display: grid;
  grid-template-columns: 190px minmax(0, 1fr);
  gap: 10px;
}

.catalog-pile {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
  overflow: auto;
  padding-right: 8px;
}

.stage-note {
  display: grid;
  grid-template-columns: 140px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  padding: 12px 14px;
  border: 1px solid rgba(224, 214, 186, 0.1);
  background: rgba(31, 38, 41, 0.42);
}

.stage-note__tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 34px;
  background: rgba(199, 104, 63, 0.14);
  color: var(--paper-2);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.stage-note p {
  margin: 0;
  color: var(--text-soft);
  font-size: 13px;
  line-height: 1.65;
}

.stage-route,
.runtime-stack {
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: 14px;
  overflow: auto;
  padding-right: 6px;
}

.route-board {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  gap: 12px;
  align-items: stretch;
}

.route-board__number {
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(224, 214, 186, 0.14);
  background: linear-gradient(180deg, rgba(199, 104, 63, 0.86), rgba(146, 77, 49, 0.9));
  color: #efe2c9;
  font-family: var(--font-display);
  font-size: 34px;
  letter-spacing: 0.08em;
}

.route-board__body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  border: 1px solid rgba(224, 214, 186, 0.12);
  background:
    linear-gradient(180deg, rgba(207, 194, 154, 0.09), transparent 28%),
    linear-gradient(180deg, rgba(62, 72, 76, 0.95), rgba(43, 52, 55, 0.95));
}

.route-board__head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: start;
}

.route-board__plan {
  display: block;
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 30px;
  letter-spacing: 0.08em;
  line-height: 0.9;
  text-transform: uppercase;
}

.route-board__task {
  color: var(--text-soft);
  font-family: var(--font-mono);
  font-size: 11px;
}

.route-board__rail {
  height: 10px;
  border: 1px solid rgba(224, 214, 186, 0.08);
  background: linear-gradient(90deg, rgba(201, 157, 84, 0.2), rgba(199, 104, 63, 0.3), rgba(201, 187, 149, 0.12));
}

.route-board__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.stage-empty {
  display: flex;
  min-height: 220px;
  flex-direction: column;
  justify-content: center;
  gap: 10px;
  padding: 20px;
  border: 1px dashed rgba(224, 214, 186, 0.16);
  background: rgba(25, 31, 33, 0.36);
}

.stage-empty__stamp {
  color: rgba(201, 187, 149, 0.24);
  font-family: var(--font-display);
  font-size: 54px;
  letter-spacing: 0.1em;
  line-height: 0.9;
}

.stage-empty p {
  margin: 0;
  color: var(--text-soft);
  max-width: 320px;
}

.runtime-section {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 12px;
}

.runtime-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.queue-ticket,
.live-ticket {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid rgba(224, 214, 186, 0.12);
  background: linear-gradient(180deg, rgba(56, 64, 68, 0.95), rgba(37, 45, 48, 0.95));
}

.queue-ticket__head,
.queue-ticket__meta,
.live-ticket__head,
.live-ticket__meta {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.queue-ticket__title,
.live-ticket__head strong {
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 26px;
  letter-spacing: 0.08em;
  line-height: 0.9;
  text-transform: uppercase;
}

.queue-ticket__task,
.queue-ticket__meta,
.live-ticket__task,
.live-ticket__meta {
  color: var(--text-soft);
  font-size: 12px;
}

.live-ticket {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr);
  gap: 10px;
}

.live-ticket__flag {
  background: linear-gradient(180deg, var(--status-running), rgba(139, 162, 110, 0.34));
}

.live-ticket__body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.drawer-context,
.drawer-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.drawer-actions {
  justify-content: flex-end;
}
</style>

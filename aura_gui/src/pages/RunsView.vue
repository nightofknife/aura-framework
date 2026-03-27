<template>
  <div class="page-shell runs-page">
    <section class="runs-header">
      <div class="runs-header__copy">
        <span class="eyebrow">Route Record Wall</span>
        <h1 class="page-title">Runs</h1>
        <p class="page-subtitle">Execution history should feel like pinned route slips and mission receipts, not a system console.</p>
      </div>

      <div class="runs-header__stats">
        <div class="runs-stat">
          <span class="runs-stat__label">active</span>
          <strong class="runs-stat__value">{{ activeRuns.length }}</strong>
        </div>
        <div class="runs-stat">
          <span class="runs-stat__label">queued</span>
          <strong class="runs-stat__value">{{ queuedCount }}</strong>
        </div>
        <div class="runs-stat">
          <span class="runs-stat__label">success</span>
          <strong class="runs-stat__value">{{ successCount }}</strong>
        </div>
        <div class="runs-stat">
          <span class="runs-stat__label">failed</span>
          <strong class="runs-stat__value">{{ failedCount }}</strong>
        </div>
      </div>
    </section>

    <section class="runs-wall">
      <div class="runs-wall__filters">
        <ProFilterBar
          v-model="filters"
          :status-options="['running', 'queued', 'success', 'failed', 'cancelled']"
          :plan-options="planOptions"
          @reset="refreshRuns"
        >
          <button class="btn btn-ghost" @click="refreshRuns">Refresh</button>
        </ProFilterBar>
      </div>

      <div class="runs-wall__body">
        <aside class="runs-wall__rail">
          <div class="runs-wall__rail-card">
            <span class="label">Status Split</span>
            <span class="pill pill-running">active {{ activeRuns.length }}</span>
            <span class="pill pill-queued">queued {{ queuedCount }}</span>
            <span class="pill pill-green">success {{ successCount }}</span>
            <span class="pill pill-red">failed {{ failedCount }}</span>
          </div>
          <p class="runs-wall__copy">Open any run slip to inspect the dossier on the right edge of the app.</p>
        </aside>

        <main class="runs-wall__list">
          <VirtualRunsList :runs="rowsView" max-height="68vh" @row-click="openRun" />
          <div v-if="detailError" class="runs-error">{{ detailError }}</div>
        </main>
      </div>
    </section>

    <RunDetailDrawer :open="drawerOpen" :run="currentRun" @close="drawerOpen = false" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import axios from 'axios'

import { getGuiConfig } from '../config.js'
import ProFilterBar from '../components/ProFilterBar.vue'
import VirtualRunsList from '../components/VirtualRunsList.vue'
import RunDetailDrawer from '../components/RunDetailDrawer.vue'

const cfg = getGuiConfig()
const api = axios.create({
  baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: cfg?.api?.timeout_ms || 5000,
})

const activeRuns = ref([])
const historyRuns = ref([])
const filters = ref({ query: '', status: '', plan: '' })
const currentRun = ref(null)
const drawerOpen = ref(false)
const detailError = ref('')

const mergedRuns = computed(() => {
  const byCid = new Map()
  for (const run of [...activeRuns.value, ...historyRuns.value]) {
    const normalized = normalizeRun(run)
    byCid.set(normalized.cid || normalized.key, normalized)
  }
  return [...byCid.values()].sort((a, b) => (b.finishedAt || b.startedAt || 0) - (a.finishedAt || a.startedAt || 0))
})

const planOptions = computed(() => [...new Set(mergedRuns.value.map((run) => run.plan_name).filter(Boolean))])

const rowsView = computed(() => {
  const q = filters.value.query.trim().toLowerCase()
  return mergedRuns.value.filter((run) => {
    if (q) {
      const haystack = `${run.plan_name} ${run.task_name} ${run.task_ref} ${run.cid}`.toLowerCase()
      if (!haystack.includes(q)) return false
    }
    if (filters.value.status && run.status !== filters.value.status) return false
    if (filters.value.plan && run.plan_name !== filters.value.plan) return false
    return true
  })
})

const queuedCount = computed(() => mergedRuns.value.filter((run) => run.status === 'queued').length)
const successCount = computed(() => mergedRuns.value.filter((run) => run.status === 'success').length)
const failedCount = computed(() => mergedRuns.value.filter((run) => run.status === 'failed').length)

function normalizeRun(run) {
  const startedAt = run?.started_at ?? run?.startedAt ?? null
  const finishedAt = run?.finished_at ?? run?.finishedAt ?? null
  const startMs = startedAt ? (startedAt > 1e12 ? startedAt : startedAt * 1000) : null
  const finishMs = finishedAt ? (finishedAt > 1e12 ? finishedAt : finishedAt * 1000) : null
  return {
    ...run,
    key: run?.cid || run?.id || `${run?.plan_name || 'plan'}::${run?.task_ref || run?.task_name || 'task'}::${startMs || 0}`,
    task_name: run?.task_name ?? run?.task_ref ?? run?.task ?? '-',
    task_ref: run?.task_ref ?? run?.task_name ?? '-',
    startedAt: startMs ? new Date(startMs) : null,
    finishedAt: finishMs ? new Date(finishMs) : null,
    elapsed: run?.duration_ms ?? (startMs && finishMs ? finishMs - startMs : null),
  }
}

async function refreshRuns() {
  try {
    const [active, history] = await Promise.all([
      api.get('/runs/active').catch(() => ({ data: [] })),
      api.get('/runs/history', { params: { limit: 50 } }).catch(() => ({ data: { runs: [] } })),
    ])
    activeRuns.value = Array.isArray(active.data) ? active.data : []
    historyRuns.value = Array.isArray(history.data?.runs) ? history.data.runs : []
  } catch {
    activeRuns.value = []
    historyRuns.value = []
  }
}

async function openRun(row) {
  const runId = row.cid || row.id
  detailError.value = ''
  try {
    const { data } = await api.get(`/runs/${runId}`)
    currentRun.value = { ...row, ...data }
    drawerOpen.value = true
  } catch (error) {
    detailError.value = error?.response?.data?.detail || error?.message || 'Failed to load run details.'
  }
}

let pollTimer = null

onMounted(async () => {
  await refreshRuns()
  pollTimer = window.setInterval(refreshRuns, 5000)
})

onUnmounted(() => {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<style scoped>
.runs-page {
  gap: 20px;
}

.runs-header {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) 420px;
  gap: 18px;
}

.runs-header__copy,
.runs-header__stats {
  padding: 18px;
  border: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(59, 68, 72, 0.92), rgba(39, 46, 49, 0.92));
  box-shadow: var(--shadow-plate), var(--shadow-inset);
}

.runs-header__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.runs-stat {
  display: flex;
  min-height: 88px;
  flex-direction: column;
  justify-content: space-between;
  padding: 12px;
  border: 1px solid rgba(224, 214, 186, 0.1);
  background: rgba(26, 31, 33, 0.34);
}

.runs-stat__label {
  color: var(--text-soft);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.runs-stat__value {
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 38px;
  letter-spacing: 0.08em;
  line-height: 0.9;
}

.runs-wall {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 16px;
  min-height: calc(100vh - 280px);
  padding: 20px;
  border: 1px solid rgba(224, 214, 186, 0.08);
  background: linear-gradient(180deg, rgba(56, 64, 68, 0.94), rgba(37, 45, 48, 0.94));
  box-shadow: var(--shadow-soft), var(--shadow-inset);
}

.runs-wall__body {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 16px;
  min-height: 0;
}

.runs-wall__rail {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.runs-wall__rail-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border: 1px solid rgba(224, 214, 186, 0.1);
  background: rgba(26, 31, 33, 0.38);
}

.runs-wall__copy {
  margin: 0;
  color: var(--text-soft);
  font-size: 13px;
  line-height: 1.7;
}

.runs-wall__list {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.runs-error {
  color: #e8c1bb;
  font-size: 13px;
}
</style>

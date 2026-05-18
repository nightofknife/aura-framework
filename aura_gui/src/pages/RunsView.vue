<template>
  <div class="page-shell runs-page">
    <div class="page-heading">
      <div class="heading-block">
        <h1 class="page-title">运行记录</h1>
      </div>
      <div class="heading-actions">
        <button class="btn btn-ghost" @click="refreshRuns">
          <RefreshCw class="icon" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="detailError" class="notice notice-danger">{{ detailError }}</div>

    <ProFilterBar
      v-model="filters"
      :status-options="statusOptions"
      :plan-options="planOptions"
      @reset="refreshRuns"
    />

    <section class="panel">
      <header class="panel-header">
        <div>
          <span class="panel-kicker">记录</span>
          <strong>{{ rowsView.length }} 条</strong>
        </div>
        <span class="pill pill-gray">active {{ activeRuns.length }}</span>
      </header>

      <div class="panel-body table-body">
        <ProDataTable
          :columns="columns"
          :rows="rowsView"
          row-key="key"
          max-height="calc(100vh - 260px)"
          :sort-default="{ key: 'startedAtMs', dir: 'desc' }"
          @row-click="openRun"
        >
          <template #col-status="{ value }">
            <span class="pill" :class="statusClass(value)">{{ statusLabel(value) }}</span>
          </template>
          <template #col-taskRef="{ row }">
            <div class="task-cell">
              <strong>{{ row.taskRef || row.title || '-' }}</strong>
              <code>{{ row.shortCid }}</code>
            </div>
          </template>
          <template #col-startedAtMs="{ value }">
            {{ formatTime(value) }}
          </template>
          <template #col-durationMs="{ value }">
            {{ formatDuration(value) }}
          </template>
          <template #col-errorSummary="{ value }">
            <span class="error-cell">{{ value || '--' }}</span>
          </template>
        </ProDataTable>
      </div>
    </section>

    <RunDetailDrawer :open="drawerOpen" :run="currentRun" @close="drawerOpen = false" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RefreshCw } from 'lucide-vue-next'

import ProDataTable from '../components/ProDataTable.vue'
import ProFilterBar from '../components/ProFilterBar.vue'
import RunDetailDrawer from '../components/RunDetailDrawer.vue'
import { getRunDetail, listActiveRuns, listRunHistory } from '../api/runs.js'
import { errorMessage } from '../api/errors.js'

const columns = [
  { key: 'status', label: '状态', width: '120px', sortable: true },
  { key: 'taskRef', label: '任务', sortable: true },
  { key: 'planName', label: '计划', width: '160px', sortable: true },
  { key: 'startedAtMs', label: '开始时间', width: '180px', sortable: true },
  { key: 'durationMs', label: '耗时', width: '110px', sortable: true },
  { key: 'errorSummary', label: '错误摘要', width: '260px' },
]

const statusOptions = ['queued', 'running', 'success', 'failed', 'cancelled', 'unknown']

const activeRuns = ref([])
const historyRuns = ref([])
const filters = ref({ query: '', status: '', plan: '' })
const currentRun = ref(null)
const drawerOpen = ref(false)
const detailError = ref('')

const mergedRuns = computed(() => {
  const byCid = new Map()
  for (const run of [...activeRuns.value, ...historyRuns.value]) {
    byCid.set(run.cid || run.key, run)
  }
  return [...byCid.values()].sort((a, b) => {
    const av = a.finishedAtMs || a.startedAtMs || 0
    const bv = b.finishedAtMs || b.startedAtMs || 0
    return bv - av
  })
})

const planOptions = computed(() =>
  [...new Set(mergedRuns.value.map((run) => run.planName).filter(Boolean))].sort()
)

const rowsView = computed(() => {
  const q = filters.value.query.trim().toLowerCase()
  return mergedRuns.value.filter((run) => {
    if (q) {
      const haystack = `${run.planName} ${run.taskRef} ${run.title} ${run.cid}`.toLowerCase()
      if (!haystack.includes(q)) return false
    }
    if (filters.value.status && run.status !== filters.value.status) return false
    if (filters.value.plan && run.planName !== filters.value.plan) return false
    return true
  })
})

async function refreshRuns() {
  const [active, history] = await Promise.all([
    listActiveRuns().catch(() => []),
    listRunHistory({ limit: 100 }).catch(() => []),
  ])
  activeRuns.value = active
  historyRuns.value = history
}

async function openRun(row) {
  if (!row?.cid) return
  detailError.value = ''
  try {
    currentRun.value = await getRunDetail(row.cid)
    drawerOpen.value = true
  } catch (error) {
    detailError.value = errorMessage(error, '运行详情加载失败。')
  }
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

function formatDuration(ms) {
  if (ms === null || ms === undefined || Number.isNaN(Number(ms))) return '--'
  const value = Number(ms)
  if (value < 1000) return `${Math.round(value)}ms`
  if (value < 60000) return `${(value / 1000).toFixed(1)}s`
  return `${Math.floor(value / 60000)}m ${Math.floor((value % 60000) / 1000)}s`
}

let pollTimer = null

onMounted(async () => {
  await refreshRuns()
  pollTimer = window.setInterval(refreshRuns, 5000)
})

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<style scoped>
.table-body {
  padding: 0;
}

.task-cell {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 5px;
}

.task-cell strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.error-cell {
  display: inline-block;
  max-width: 240px;
  overflow: hidden;
  color: var(--text-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
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
</style>

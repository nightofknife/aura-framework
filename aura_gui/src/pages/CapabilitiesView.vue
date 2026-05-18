<template>
  <div class="page-shell capabilities-page">
    <div class="page-heading">
      <div class="heading-block">
        <h1 class="page-title">能力中心</h1>
      </div>
      <div class="heading-actions">
        <button class="btn btn-primary" :disabled="checking || !apiTokenConfigured" @click="runCapabilityCheck">
          <Activity class="icon" />
          {{ checking ? '检查中...' : 'Self-check' }}
        </button>
        <button class="btn btn-ghost" @click="refresh">
          <RefreshCw class="icon" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="error" class="notice notice-danger">{{ error }}</div>
    <div v-if="!apiTokenConfigured" class="notice">Local API token required for self-check. Configure it in Settings.</div>

    <section class="domain-grid">
      <button
        v-for="domain in domainSummary"
        :key="domain.name"
        class="domain-card"
        :class="{ 'is-active': selectedDomain === domain.name }"
        @click="selectedDomain = selectedDomain === domain.name ? '' : domain.name"
      >
        <span>{{ domain.name }}</span>
        <strong>{{ domain.available }}/{{ domain.total }}</strong>
        <small>{{ domain.unhealthy }} 个异常</small>
      </button>
    </section>

    <section class="panel">
      <header class="panel-header">
        <div>
          <span class="panel-kicker">Backend</span>
          <strong>{{ filteredRows.length }} 条能力</strong>
        </div>
        <select v-model="selectedDomain" class="select domain-select">
          <option value="">全部 domain</option>
          <option v-for="domain in domainSummary" :key="domain.name" :value="domain.name">{{ domain.name }}</option>
        </select>
      </header>

      <div class="panel-body">
        <table>
          <thead>
            <tr>
              <th>Domain</th>
              <th>Backend</th>
              <th>可用性</th>
              <th>Health</th>
              <th>首条限制 / 错误</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in filteredRows" :key="`${row.domain}:${row.backendId}`">
              <td><code>{{ row.domain }}</code></td>
              <td>{{ row.backendId || '-' }}</td>
              <td>
                <span class="pill" :class="row.available ? 'pill-green' : 'pill-red'">
                  {{ row.available ? '可用' : '不可用' }}
                </span>
              </td>
              <td><span class="pill" :class="healthClass(row.healthStatus)">{{ row.healthStatus || 'unknown' }}</span></td>
              <td class="issue-cell">{{ firstIssue(row) }}</td>
              <td>
                <details class="capability-details">
                  <summary>展开</summary>
                  <div class="detail-grid">
                    <div><span>稳定性</span><code>{{ row.stability }}</code></div>
                    <div><span>副作用</span><code>{{ row.sideEffectLevel }}</code></div>
                    <div><span>需要管理员</span><code>{{ row.requiresAdmin ? '是' : '否' }}</code></div>
                    <div><span>前台窗口</span><code>{{ row.requiresForeground ? '需要' : '不需要' }}</code></div>
                  </div>
                  <div class="stack">
                    <span class="label">Capabilities</span>
                    <pre class="json">{{ pretty(row.capabilities || []) }}</pre>
                  </div>
                  <div class="stack">
                    <span class="label">Limitations</span>
                    <pre class="json">{{ pretty(row.limitations || []) }}</pre>
                  </div>
                  <div v-if="row.lastError" class="notice notice-danger">{{ row.lastError }}</div>
                </details>
              </td>
            </tr>
            <tr v-if="!filteredRows.length">
              <td colspan="6" class="empty-cell">暂无能力数据。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="selfCheckResult" class="panel">
      <header class="panel-header">
        <div>
          <span class="panel-kicker">Self-check</span>
          <strong>最近结果</strong>
        </div>
      </header>
      <div class="panel-body">
        <pre class="json">{{ pretty(selfCheckResult) }}</pre>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Activity, RefreshCw } from 'lucide-vue-next'

import { listCapabilities, runSelfCheck } from '../api/capabilities.js'
import { errorMessage } from '../api/errors.js'
import { useApiTokenStatus } from '../composables/useApiToken.js'

const rows = ref([])
const selectedDomain = ref('')
const checking = ref(false)
const error = ref('')
const selfCheckResult = ref(null)
const { hasToken: apiTokenConfigured } = useApiTokenStatus()

const domainSummary = computed(() => {
  const map = new Map()
  for (const row of rows.value) {
    const current = map.get(row.domain) || { name: row.domain, total: 0, available: 0, unhealthy: 0 }
    current.total += 1
    if (row.available) current.available += 1
    if (!row.available || !['ok', 'healthy', 'ready'].includes(String(row.healthStatus || '').toLowerCase())) {
      current.unhealthy += 1
    }
    map.set(row.domain, current)
  }
  return [...map.values()].sort((a, b) => a.name.localeCompare(b.name))
})

const filteredRows = computed(() =>
  rows.value
    .filter((row) => !selectedDomain.value || row.domain === selectedDomain.value)
    .sort((a, b) => `${a.domain}:${a.backendId}`.localeCompare(`${b.domain}:${b.backendId}`))
)

async function refresh() {
  try {
    const data = await listCapabilities()
    rows.value = data.rows
    error.value = ''
  } catch (err) {
    rows.value = []
    error.value = errorMessage(err, '能力数据加载失败。')
  }
}

async function runCapabilityCheck() {
  if (!apiTokenConfigured.value) {
    error.value = 'Local API token required. Configure it in Settings.'
    return
  }
  checking.value = true
  try {
    selfCheckResult.value = await runSelfCheck()
    await refresh()
  } catch (err) {
    error.value = errorMessage(err, 'Self-check 执行失败。')
  } finally {
    checking.value = false
  }
}

function firstIssue(row) {
  return row.lastError || row.limitations?.[0] || '无'
}

function healthClass(status) {
  const value = String(status || '').toLowerCase()
  if (['ok', 'healthy', 'ready'].includes(value)) return 'pill-green'
  if (['failed', 'error', 'unhealthy'].includes(value)) return 'pill-red'
  if (['degraded', 'warning'].includes(value)) return 'pill-yellow'
  return 'pill-gray'
}

function pretty(value) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

onMounted(refresh)
</script>

<style scoped>
.domain-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.domain-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
  align-items: flex-start;
  padding: 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
}

.domain-card:hover,
.domain-card.is-active {
  border-color: var(--border-strong);
  background: var(--bg-surface-2);
}

.domain-card.is-active {
  box-shadow: inset 3px 0 0 var(--accent);
}

.domain-card span,
.domain-card small {
  color: var(--text-muted);
}

.domain-card strong {
  font-size: 22px;
}

.domain-select {
  width: 220px;
}

.issue-cell {
  max-width: 320px;
  overflow: hidden;
  color: var(--text-secondary);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.capability-details {
  min-width: 240px;
}

summary {
  color: var(--text-secondary);
  cursor: pointer;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin: 10px 0;
}

.detail-grid div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 5px;
}

.detail-grid span {
  color: var(--text-muted);
  font-size: 12px;
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

@media (max-width: 1120px) {
  .domain-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>

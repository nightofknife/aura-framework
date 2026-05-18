<template>
  <div class="page-shell">
    <div class="page-heading">
      <div class="heading-block">
        <span class="eyebrow">Operations</span>
        <h1 class="page-title">Observability</h1>
        <p class="page-subtitle">Error taxonomy, backend metrics, action latency, and recent trace lookup from the local SQLite store.</p>
      </div>
      <div class="heading-actions">
        <button class="btn btn-primary" @click="refresh">Refresh</button>
      </div>
    </div>

    <div v-if="errorMessage" class="notice-error">{{ errorMessage }}</div>

    <section class="observability-grid">
      <div class="ops-panel">
        <div class="section-title">
          <span class="label">Error Summary</span>
          <code>{{ totalErrors }} classified</code>
        </div>
        <div class="metric-list">
          <div v-for="row in errorRows" :key="row.category" class="metric-row">
            <button class="link-button" @click="loadErrorCategory(row.category)">{{ row.category }}</button>
            <span class="pill" :class="row.count ? 'pill-red' : 'pill-gray'">{{ row.count }}</span>
          </div>
        </div>
      </div>

      <div class="ops-panel">
        <div class="section-title">
          <span class="label">Backend Metrics</span>
          <code>{{ backendRows.length }} backends</code>
        </div>
        <div class="metric-list">
          <div v-for="row in backendRows" :key="row.backend" class="metric-row">
            <div>
              <strong>{{ row.backend }}</strong>
              <p>{{ row.ok }} ok / {{ row.failed }} failed / {{ row.fallbacks }} fallback</p>
            </div>
            <span class="pill pill-gray">{{ row.count }}</span>
          </div>
          <div v-if="!backendRows.length" class="empty-state">No backend samples.</div>
        </div>
      </div>

      <div class="ops-panel wide">
        <div class="section-title">
          <span class="label">Action Latency</span>
          <code>{{ actionRows.length }} actions</code>
        </div>
        <div class="action-table">
          <div class="action-row action-row-head">
            <span>Action</span>
            <span>Count</span>
            <span>Avg</span>
            <span>Failed</span>
          </div>
          <div v-for="row in actionRows" :key="row.action" class="action-row">
            <strong>{{ row.action }}</strong>
            <code>{{ row.count }}</code>
            <code>{{ Math.round(row.duration_ms_avg || 0) }}ms</code>
            <span class="pill" :class="row.failed ? 'pill-red' : 'pill-gray'">{{ row.failed }}</span>
          </div>
          <div v-if="!actionRows.length" class="empty-state">No action samples.</div>
        </div>
      </div>

      <div class="ops-panel wide">
        <div class="section-title">
          <span class="label">Desktop Metrics</span>
          <code>{{ desktopRows.length }} rows</code>
        </div>
        <div class="action-table desktop-table">
          <div class="action-row action-row-head">
            <span>Domain</span>
            <span>Backend</span>
            <span>Count</span>
            <span>Failed</span>
            <span>Avg</span>
          </div>
          <div v-for="row in desktopRows" :key="`${row.domain}-${row.backend}`" class="action-row">
            <strong>{{ row.domain || '-' }}</strong>
            <code>{{ row.backend || '-' }}</code>
            <code>{{ row.count || 0 }}</code>
            <span class="pill" :class="row.failed ? 'pill-red' : 'pill-gray'">{{ row.failed || 0 }}</span>
            <code>{{ Math.round(row.duration_ms_avg || 0) }}ms</code>
          </div>
          <div v-if="!desktopRows.length" class="empty-state">No desktop metrics.</div>
        </div>
      </div>

      <div class="ops-panel wide">
        <div class="section-title">
          <span class="label">Service Latency</span>
          <code>{{ serviceRows.length }} services</code>
        </div>
        <div class="action-table service-table">
          <div class="action-row action-row-head">
            <span>Service</span>
            <span>Count</span>
            <span>Failed</span>
            <span>Avg</span>
          </div>
          <div v-for="row in serviceRows" :key="row.service" class="action-row">
            <strong>{{ row.service || '-' }}</strong>
            <code>{{ row.count || 0 }}</code>
            <span class="pill" :class="row.failed ? 'pill-red' : 'pill-gray'">{{ row.failed || 0 }}</span>
            <code>{{ Math.round(row.duration_ms_avg || 0) }}ms</code>
          </div>
          <div v-if="!serviceRows.length" class="empty-state">No service metrics.</div>
        </div>
      </div>

      <div class="ops-panel wide">
        <div class="section-title">
          <span class="label">Resource Samples</span>
          <code>{{ resourceRows.length }} samples</code>
        </div>
        <div class="action-table resource-table">
          <div class="action-row action-row-head">
            <span>Run</span>
            <span>Node</span>
            <span>RSS</span>
            <span>Duration</span>
          </div>
          <div v-for="row in resourceRows.slice(0, 8)" :key="`${row.cid}-${row.node_id}-${row.updated_at_ms}`" class="action-row">
            <code>{{ row.cid || '-' }}</code>
            <strong>{{ row.node_id || '-' }}</strong>
            <code>{{ formatBytes(row.rss_bytes) }}</code>
            <code>{{ Math.round(row.duration_ms || 0) }}ms</code>
          </div>
          <div v-if="!resourceRows.length" class="empty-state">No resource samples.</div>
        </div>
      </div>

      <div v-if="selectedErrorCategory" class="ops-panel wide">
        <div class="section-title">
          <span class="label">Error Drilldown</span>
          <code>{{ selectedErrorCategory }}</code>
        </div>
        <div class="trace-list">
          <div v-for="(item, index) in errorDetailRows" :key="index" class="trace-row">
            <div>
              <strong>{{ item.cid || item.trace_id || '-' }}</strong>
              <p>{{ item.action || item.node_id || item.message || 'classified error' }}</p>
            </div>
            <span class="pill pill-red">{{ item.category || selectedErrorCategory }}</span>
          </div>
          <div v-if="!errorDetailRows.length" class="empty-state">No rows for this category.</div>
        </div>
      </div>

      <div class="ops-panel wide">
        <div class="section-title">
          <span class="label">Recent Traces</span>
          <code>{{ traceRows.length }} rows</code>
        </div>
        <div class="trace-list">
          <div v-for="trace in traceRows" :key="trace.cid" class="trace-row">
            <div>
              <strong>{{ trace.trace_id }}</strong>
              <p>{{ trace.plan_name || 'unknown' }} / {{ trace.task_name || 'unknown' }}</p>
            </div>
            <span class="pill" :class="trace.status === 'success' ? 'pill-green' : 'pill-gray'">{{ trace.status || 'unknown' }}</span>
          </div>
          <div v-if="!traceRows.length" class="empty-state">No traces found.</div>
        </div>
      </div>

      <div class="ops-panel wide">
        <div class="section-title">
          <span class="label">Queue Recovery</span>
          <code>{{ recoverySummary }}</code>
        </div>
        <div class="heading-actions recovery-actions">
          <button class="btn btn-ghost btn-sm" @click="loadRecovery">Refresh</button>
          <button class="btn btn-primary btn-sm" :disabled="!apiTokenConfigured" :title="tokenGateTitle" @click="recoverQueue">Recover</button>
          <button class="btn btn-danger btn-sm" :disabled="!apiTokenConfigured" :title="tokenGateTitle" @click="abandonStale">Abandon Stale</button>
        </div>
        <div class="trace-list">
          <div v-for="item in recoveryItems" :key="item.cid" class="trace-row">
            <div>
              <strong>{{ item.cid }}</strong>
              <p>{{ item.plan_name || 'unknown' }} / {{ item.task_name || 'unknown' }}</p>
            </div>
            <span class="pill" :class="item.state === 'leased' ? 'pill-yellow' : 'pill-gray'">{{ item.state }}</span>
          </div>
          <div v-if="!recoveryItems.length" class="empty-state">No recovery candidates.</div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { abandonStaleQueue, getQueueRecoveryStatus, recoverQueue as recoverRuntimeQueue } from '../api/advanced.js'
import {
  getActionMetrics,
  getBackendMetrics,
  getDesktopMetrics,
  getErrorCategory,
  getErrorSummary,
  getResourceSamples,
  getServiceMetrics,
  listTraces,
} from '../api/observability.js'
import { useApiTokenStatus } from '../composables/useApiToken.js'

const { hasToken: apiTokenConfigured } = useApiTokenStatus()

const errorSummary = ref({ counts: {} })
const backendMetrics = ref({ backends: [] })
const actionMetrics = ref({ actions: [] })
const serviceMetrics = ref({ services: [] })
const desktopMetrics = ref({ desktop: [] })
const resources = ref({ samples: [] })
const errorDetail = ref({ errors: [] })
const selectedErrorCategory = ref('')
const traces = ref({ traces: [] })
const recovery = ref({ items: [] })
const errorMessage = ref('')
const tokenGateTitle = computed(() =>
  apiTokenConfigured.value ? '' : 'Local API token required. Configure it in Settings.'
)

const errorRows = computed(() =>
  Object.entries(errorSummary.value?.counts || {}).map(([category, count]) => ({ category, count }))
)
const totalErrors = computed(() => errorRows.value.reduce((sum, row) => sum + Number(row.count || 0), 0))
const backendRows = computed(() => backendMetrics.value?.backends || [])
const actionRows = computed(() => actionMetrics.value?.actions || [])
const serviceRows = computed(() => serviceMetrics.value?.services || [])
const desktopRows = computed(() => desktopMetrics.value?.desktop || [])
const resourceRows = computed(() => resources.value?.samples || [])
const errorDetailRows = computed(() => errorDetail.value?.errors || errorDetail.value?.items || errorDetail.value?.runs || [])
const traceRows = computed(() => traces.value?.traces || [])
const recoveryItems = computed(() => recovery.value?.items || [])
const recoverySummary = computed(() => `${recovery.value?.recoverable_count || 0} recoverable / ${recovery.value?.stale_leased_count || 0} stale`)

async function refresh() {
  try {
    const [errors, backends, actions, services, desktop, resourceResp, traceList, recoveryResp] = await Promise.all([
      getErrorSummary(),
      getBackendMetrics(),
      getActionMetrics(),
      getServiceMetrics().catch(() => ({ services: [] })),
      getDesktopMetrics().catch(() => ({ desktop: [] })),
      getResourceSamples().catch(() => ({ samples: [] })),
      listTraces(),
      getQueueRecoveryStatus().catch(() => ({ items: [] })),
    ])
    errorSummary.value = errors || { counts: {} }
    backendMetrics.value = backends || { backends: [] }
    actionMetrics.value = actions || { actions: [] }
    serviceMetrics.value = services || { services: [] }
    desktopMetrics.value = desktop || { desktop: [] }
    resources.value = resourceResp || { samples: [] }
    traces.value = traceList || { traces: [] }
    recovery.value = recoveryResp || { items: [] }
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || 'Unable to load observability data.'
  }
}

async function loadErrorCategory(category) {
  selectedErrorCategory.value = category
  errorDetail.value = await getErrorCategory(category).catch(() => ({ errors: [] }))
}

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (!bytes) return '-'
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KiB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`
}

async function loadRecovery() {
  recovery.value = await getQueueRecoveryStatus()
}

async function recoverQueue() {
  if (!apiTokenConfigured.value) {
    errorMessage.value = tokenGateTitle.value
    return
  }
  await recoverRuntimeQueue()
  await loadRecovery()
}

async function abandonStale() {
  if (!apiTokenConfigured.value) {
    errorMessage.value = tokenGateTitle.value
    return
  }
  await abandonStaleQueue()
  await loadRecovery()
}

onMounted(refresh)
</script>

<style scoped>
.observability-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.ops-panel {
  padding: 16px;
  border: 1px solid rgba(224, 214, 186, 0.1);
  background: rgba(35, 43, 46, 0.9);
}

.ops-panel.wide {
  grid-column: 1 / -1;
}

.section-title,
.metric-row,
.trace-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.metric-list,
.trace-list,
.action-table {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
}

.metric-row,
.trace-row,
.action-row {
  padding: 10px;
  border: 1px solid rgba(224, 214, 186, 0.08);
  background: rgba(23, 29, 31, 0.42);
}

.action-row {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) 80px 90px 80px;
  align-items: center;
  gap: 12px;
}

.desktop-table .action-row {
  grid-template-columns: minmax(100px, 0.5fr) minmax(180px, 1fr) 70px 80px 80px;
}

.service-table .action-row,
.resource-table .action-row {
  grid-template-columns: minmax(220px, 1fr) 80px 80px 90px;
}

.action-row-head {
  color: var(--text-soft);
  font-size: 12px;
  text-transform: uppercase;
}

.metric-row strong,
.trace-row strong,
.action-row strong {
  color: var(--paper-2);
}

.metric-row p,
.trace-row p {
  margin: 4px 0 0;
  color: var(--text-soft);
  font-size: 12px;
}

.link-button {
  border: 0;
  background: transparent;
  color: var(--paper-2);
  font: inherit;
  font-weight: 700;
  text-align: left;
  cursor: pointer;
}

.notice-error {
  margin-bottom: 16px;
  color: #e8c1bb;
}

.recovery-actions {
  margin-top: 12px;
}
</style>

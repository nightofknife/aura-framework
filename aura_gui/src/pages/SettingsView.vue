<template>
  <div class="page-shell settings-page">
    <div class="page-heading">
      <div class="heading-block">
        <h1 class="page-title">设置</h1>
      </div>
      <div class="heading-actions">
        <button class="btn btn-ghost" :disabled="loading" @click="refreshOverview">
          <RefreshCw class="icon" />
          {{ loading ? '刷新中...' : '刷新' }}
        </button>
      </div>
    </div>

    <div v-if="actionError" class="notice notice-danger">{{ actionError }}</div>
    <div v-if="actionMessage" class="notice notice-info">{{ actionMessage }}</div>

    <section class="summary-grid">
      <article class="panel summary-card">
        <header class="panel-header">
          <div>
            <span class="panel-kicker">系统</span>
            <strong>Runtime</strong>
          </div>
          <span class="pill" :class="system?.status === 'ok' ? 'pill-green' : 'pill-red'">
            {{ system?.status || 'offline' }}
          </span>
        </header>
        <div class="panel-body stack">
          <div class="settings-line"><span>调度</span><code>{{ system?.isRunning ? 'running' : 'stopped' }}</code></div>
          <div class="settings-line"><span>Ready</span><code>{{ system?.ready ? 'true' : 'false' }}</code></div>
          <div class="settings-line"><span>Scheduler</span><code>{{ system?.schedulerRunning ? 'running' : 'stopped' }}</code></div>
        </div>
      </article>

      <article class="panel summary-card">
        <header class="panel-header">
          <div>
            <span class="panel-kicker">API</span>
            <strong>Transport</strong>
          </div>
        </header>
        <div class="panel-body stack">
          <div class="settings-line"><span>Base</span><code>{{ cfg.api.base_url }}</code></div>
          <div class="settings-line"><span>Timeout</span><code>{{ cfg.api.timeout_ms }}ms</code></div>
          <div class="settings-line"><span>Poll</span><code>{{ cfg.api.status_poll_ms }}ms</code></div>
          <div class="settings-line"><span>Local token</span><code>{{ apiTokenConfigured ? 'configured' : 'missing' }}</code></div>
          <div class="settings-line"><span>Local admin</span><code>{{ localAdminEnabled ? 'enabled' : 'disabled' }}</code></div>
        </div>
      </article>

      <article class="panel summary-card">
        <header class="panel-header">
          <div>
            <span class="panel-kicker">Workspace</span>
            <strong>{{ workspaceProfile }}</strong>
          </div>
        </header>
        <div class="panel-body stack">
          <div class="settings-line"><span>Root</span><code>{{ workspaceRoot }}</code></div>
          <div class="settings-line"><span>Persistence</span><code>{{ workspacePersistence }}</code></div>
          <div class="settings-line"><span>Policy</span><code>{{ policyProfile }}</code></div>
        </div>
      </article>

      <article class="panel summary-card">
        <header class="panel-header">
          <div>
            <span class="panel-kicker">Packages</span>
            <strong>{{ enabledPackageCount }}/{{ packages.length }} enabled</strong>
          </div>
        </header>
        <div class="panel-body stack">
          <div class="settings-line"><span>Lock drift</span><code>{{ driftPackageCount }}</code></div>
          <div class="settings-line"><span>Validation</span><code>{{ packageValidationSummary }}</code></div>
          <div class="settings-line"><span>Latest diagnostics</span><code>{{ latestDiagnostic }}</code></div>
        </div>
      </article>
    </section>

    <section class="panel token-panel">
      <header class="panel-header">
        <div>
          <span class="panel-kicker">Security</span>
          <strong>Local API Token</strong>
        </div>
        <span class="pill" :class="apiTokenConfigured ? 'pill-green' : 'pill-red'">
          {{ apiTokenConfigured ? 'configured' : 'missing' }}
        </span>
      </header>
      <div class="panel-body token-body">
        <input
          v-model="tokenInput"
          class="input token-input"
          type="password"
          autocomplete="off"
          placeholder="Paste logs/local_api_token"
        />
        <label class="remember-token">
          <input v-model="rememberToken" type="checkbox" />
          <span>Remember in this browser</span>
        </label>
        <div class="section-actions token-actions">
          <button class="btn btn-primary btn-sm" :disabled="!tokenInput.trim()" @click="saveLocalApiToken">Save token</button>
          <button class="btn btn-ghost btn-sm" :disabled="!apiTokenConfigured" @click="clearLocalApiToken">Clear token</button>
        </div>
        <span class="hint">Token value is not displayed after saving.</span>
      </div>
    </section>

    <section class="panel desktop-panel">
      <header class="panel-header">
        <div>
          <span class="panel-kicker">Desktop</span>
          <strong>Runtime Discovery</strong>
        </div>
        <span class="pill" :class="desktopShellAvailable ? 'pill-green' : 'pill-gray'">
          {{ desktopShellAvailable ? 'electron' : 'browser' }}
        </span>
      </header>
      <div class="panel-body desktop-body">
        <div class="section-actions">
          <button class="btn btn-ghost btn-sm" :disabled="!desktopShellAvailable || discoveringRuntimes" @click="discoverDesktopRuntimes">
            {{ discoveringRuntimes ? 'Discovering...' : 'Discover runtimes' }}
          </button>
        </div>
        <table v-if="runtimeCandidates.length">
          <thead>
            <tr>
              <th>Runtime</th>
              <th>Health</th>
              <th>API</th>
              <th>Source</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="candidate in runtimeCandidates" :key="candidate.id + candidate.apiBase">
              <td><code>{{ candidate.id }}</code></td>
              <td>
                <span class="pill" :class="candidate.health === 'running' ? 'pill-green' : 'pill-gray'">
                  {{ candidate.health }}
                </span>
              </td>
              <td class="source-cell">{{ candidate.apiBase }}</td>
              <td class="source-cell">{{ candidate.source || '--' }}</td>
              <td>
                <div class="row-actions">
                  <button class="btn btn-primary btn-sm" @click="connectDesktopRuntime(candidate)">Connect</button>
                  <button class="btn btn-ghost btn-sm" :disabled="!candidate.tokenPath" @click="useDesktopRuntimeToken(candidate)">
                    Use token
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <span v-else class="hint">
          {{ desktopShellAvailable ? 'No runtime candidates loaded.' : 'Runtime discovery is available in the Electron app.' }}
        </span>
      </div>
    </section>

    <section class="panel advanced-panel">
      <header class="panel-header">
        <div>
          <span class="panel-kicker">高级</span>
          <strong>维护与诊断</strong>
        </div>
      </header>

      <div class="panel-body advanced-stack">
        <details class="advanced-section">
          <summary>Workspace Packages</summary>
          <div class="section-actions">
            <button class="btn btn-ghost btn-sm" @click="refreshOverview">刷新包列表</button>
            <button class="btn btn-primary btn-sm" :disabled="adminActionDisabled" :title="adminGateTitle" @click="writeLockFile">写入 lock</button>
          </div>
          <table>
            <thead>
              <tr>
                <th>Package</th>
                <th>版本</th>
                <th>状态</th>
                <th>校验</th>
                <th>来源</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="pkg in packages" :key="pkg.id">
                <td><code>{{ pkg.id }}</code></td>
                <td>{{ pkg.version || '--' }}</td>
                <td>
                  <span class="pill" :class="pkg.enabled ? 'pill-green' : 'pill-gray'">
                    {{ pkg.enabled ? '启用' : '禁用' }}
                  </span>
                </td>
                <td>{{ pkg.validationStatus }}</td>
                <td class="source-cell">{{ pkg.source || '--' }}</td>
                <td>
                  <button class="btn btn-ghost btn-sm" :disabled="adminActionDisabled" :title="adminGateTitle" @click="togglePackage(pkg)">
                    {{ pkg.enabled ? '禁用' : '启用' }}
                  </button>
                </td>
              </tr>
              <tr v-if="!packages.length">
                <td colspan="6" class="empty-cell">暂无 package 数据。</td>
              </tr>
            </tbody>
          </table>
        </details>

        <details class="advanced-section">
          <summary>Runtime Reload</summary>
          <div class="detail-grid">
            <div><span>Status</span><code>{{ featureStatus(reloadInfo) }}</code></div>
            <div><span>Reload ID</span><code>{{ reloadInfo?.reload_id || '--' }}</code></div>
            <div><span>Blocked</span><code>{{ reloadInfo?.blocked_by?.length || 0 }}</code></div>
          </div>
          <div class="section-actions">
            <button class="btn btn-ghost btn-sm" :disabled="tokenActionDisabled" :title="tokenGateTitle" @click="planRuntimeReload">Plan</button>
            <button class="btn btn-primary btn-sm" :disabled="adminActionDisabled" :title="adminGateTitle" @click="applyRuntimeReload">Apply</button>
          </div>
          <pre v-if="advancedResult.reload" class="json">{{ pretty(advancedResult.reload) }}</pre>
        </details>

        <details class="advanced-section">
          <summary>Migrations</summary>
          <div class="detail-grid">
            <div><span>Status</span><code>{{ featureStatus(migrationsInfo) }}</code></div>
            <div><span>Schema</span><code>{{ migrationsInfo?.run_store_schema_version ?? '--' }}</code></div>
            <div><span>Legacy DB</span><code>{{ migrationsInfo?.legacy_db_exists ? 'detected' : 'none' }}</code></div>
          </div>
          <div class="section-actions">
            <button class="btn btn-ghost btn-sm" :disabled="tokenActionDisabled" :title="tokenGateTitle" @click="planMigrationRun">Plan</button>
            <button class="btn btn-primary btn-sm" :disabled="adminActionDisabled" :title="adminGateTitle" @click="applyMigrationRun">Apply</button>
          </div>
          <pre v-if="advancedResult.migrations" class="json">{{ pretty(advancedResult.migrations) }}</pre>
        </details>

        <details class="advanced-section">
          <summary>Policy</summary>
          <div class="detail-grid">
            <div><span>Profile</span><code>{{ policyProfile }}</code></div>
            <div><span>Mode</span><code>{{ policyInfo?.mode || '--' }}</code></div>
          </div>
          <div class="section-actions">
            <button class="btn btn-ghost btn-sm" @click="loadEffectivePolicy">加载 effective policy</button>
          </div>
          <pre v-if="advancedResult.policy" class="json">{{ pretty(advancedResult.policy) }}</pre>
        </details>

        <details class="advanced-section">
          <summary>Diagnostics</summary>
          <div class="detail-grid">
            <div><span>Recent</span><code>{{ diagnostics.length }}</code></div>
            <div><span>Latest</span><code>{{ latestDiagnostic }}</code></div>
          </div>
          <div class="section-actions">
            <button class="btn btn-primary btn-sm" :disabled="tokenActionDisabled" :title="tokenGateTitle" @click="collectDiagnosticBundle">Collect</button>
          </div>
          <pre v-if="advancedResult.diagnostics" class="json">{{ pretty(advancedResult.diagnostics) }}</pre>
        </details>

        <details class="advanced-section">
          <summary>Queue Recovery</summary>
          <div class="detail-grid">
            <div><span>Status</span><code>{{ queueStatusText }}</code></div>
            <div><span>Items</span><code>{{ queueItemCount }}</code></div>
          </div>
          <div class="section-actions">
            <button class="btn btn-ghost btn-sm" @click="loadQueueStatus">刷新状态</button>
            <button class="btn btn-primary btn-sm" :disabled="adminActionDisabled" :title="adminGateTitle" @click="recoverRuntimeQueue">Recover</button>
            <button class="btn btn-danger btn-sm" :disabled="adminActionDisabled" :title="adminGateTitle" @click="abandonQueueItems">Abandon stale</button>
          </div>
          <pre v-if="advancedResult.queue" class="json">{{ pretty(advancedResult.queue) }}</pre>
        </details>

        <details class="advanced-section">
          <summary>Observability</summary>
          <div class="section-actions">
            <button class="btn btn-ghost btn-sm" @click="loadObservability">按需加载摘要</button>
          </div>
          <pre v-if="advancedResult.observability" class="json">{{ pretty(advancedResult.observability) }}</pre>
        </details>
      </div>
    </section>

    <ConfirmModal
      :open="confirmState.open"
      :title="confirmState.title"
      :message="confirmState.message"
      :danger="confirmState.danger"
      @confirm="resolveConfirm(true)"
      @cancel="resolveConfirm(false)"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { RefreshCw } from 'lucide-vue-next'

import ConfirmModal from '../components/ConfirmModal.vue'
import { getGuiConfig } from '../config.js'
import { loadSettingsOverview } from '../api/settings.js'
import {
  abandonStaleQueue,
  applyMigrations,
  applyReload,
  collectDiagnostics,
  getEffectivePolicy,
  getObservabilitySummary,
  getQueueRecoveryStatus,
  planMigrations,
  planReload,
  recoverQueue,
} from '../api/advanced.js'
import { setPackageEnabled, writePackageLock } from '../api/workspace.js'
import { errorMessage } from '../api/errors.js'
import { clearApiToken, setApiToken } from '../api/client.js'
import {
  connectRuntime,
  discoverRuntimeCandidates,
  isDesktopShell,
  readRuntimeToken,
} from '../api/desktop.js'
import { useApiTokenStatus } from '../composables/useApiToken.js'

const cfg = getGuiConfig()
const { hasToken: apiTokenConfigured, persistence: apiTokenPersistence, refresh: refreshApiTokenStatus } = useApiTokenStatus()

const loading = ref(false)
const overview = ref({})
const queueRecovery = ref(null)
const actionMessage = ref('')
const actionError = ref('')
const tokenInput = ref('')
const rememberToken = ref(false)
const desktopShellAvailable = ref(isDesktopShell())
const discoveringRuntimes = ref(false)
const runtimeCandidates = ref([])
const advancedResult = reactive({
  reload: null,
  migrations: null,
  policy: null,
  diagnostics: null,
  queue: null,
  observability: null,
})
const confirmState = reactive({
  open: false,
  title: '确认操作',
  message: '',
  danger: false,
  resolve: null,
})

const system = computed(() => overview.value?.system || {})
const workspaceInfo = computed(() => overview.value?.workspace || {})
const packages = computed(() => overview.value?.packages || [])
const policyInfo = computed(() => overview.value?.policy || {})
const diagnostics = computed(() => overview.value?.diagnostics || [])
const reloadInfo = computed(() => overview.value?.reload || {})
const migrationsInfo = computed(() => overview.value?.migrations || {})
const localAdminEnabled = computed(() => !!cfg?.features?.local_admin)
const tokenActionDisabled = computed(() => !apiTokenConfigured.value)
const adminActionDisabled = computed(() => !apiTokenConfigured.value || !localAdminEnabled.value)
const tokenGateTitle = computed(() =>
  apiTokenConfigured.value ? '' : 'Local API token required. Configure it in Settings.'
)
const adminGateTitle = computed(() => {
  if (!apiTokenConfigured.value) return 'Local API token required. Configure it in Settings.'
  if (!localAdminEnabled.value) return 'Local admin is disabled in GUI config.'
  return ''
})

const workspaceProfile = computed(() =>
  workspaceInfo.value?.workspace?.profile ||
  workspaceInfo.value?.workspace?.workspace?.profile ||
  workspaceInfo.value?.profile ||
  'workspace-default'
)
const workspaceRoot = computed(() =>
  workspaceInfo.value?.workspace?.root ||
  workspaceInfo.value?.root ||
  workspaceInfo.value?.path ||
  '--'
)
const workspacePersistence = computed(() =>
  workspaceInfo.value?.runtime?.persistence ||
  workspaceInfo.value?.workspace?.runtime?.persistence ||
  'sqlite'
)
const policyProfile = computed(() => policyInfo.value?.profile || 'default')
const enabledPackageCount = computed(() => packages.value.filter((pkg) => pkg.enabled).length)
const driftPackageCount = computed(() => packages.value.filter((pkg) => pkg.lockDrift).length)
const latestDiagnostic = computed(() => diagnostics.value?.[0]?.id || diagnostics.value?.[0]?.bundle_id || '--')
const queueStatusText = computed(() => queueRecovery.value?.status || queueRecovery.value?.state || '--')
const queueItemCount = computed(() => {
  const items = queueRecovery.value?.items || queueRecovery.value?.stale_items || queueRecovery.value?.runs || []
  return Array.isArray(items) ? items.length : 0
})
const packageValidationSummary = computed(() => {
  if (!packages.value.length) return '--'
  const invalid = packages.value.filter((pkg) => !['ok', 'valid', 'unknown'].includes(String(pkg.validationStatus).toLowerCase())).length
  return invalid ? `${invalid} issue` : 'ok'
})

function saveLocalApiToken() {
  const token = tokenInput.value.trim()
  if (!token) return
  setApiToken(token, { remember: rememberToken.value })
  tokenInput.value = ''
  refreshApiTokenStatus()
  actionError.value = ''
  actionMessage.value = `Local API token saved (${apiTokenPersistence.value}).`
}

function clearLocalApiToken() {
  clearApiToken()
  tokenInput.value = ''
  refreshApiTokenStatus()
  actionMessage.value = 'Local API token cleared.'
}

async function discoverDesktopRuntimes() {
  if (!desktopShellAvailable.value) return
  discoveringRuntimes.value = true
  actionError.value = ''
  try {
    runtimeCandidates.value = await discoverRuntimeCandidates()
    actionMessage.value = `Discovered ${runtimeCandidates.value.length} runtime candidate(s).`
  } catch (error) {
    actionError.value = errorMessage(error, 'Runtime discovery failed.')
  } finally {
    discoveringRuntimes.value = false
  }
}

async function connectDesktopRuntime(candidate) {
  try {
    connectRuntime(candidate)
    actionMessage.value = `Connected GUI to ${candidate.apiBase}.`
    await refreshOverview()
  } catch (error) {
    actionError.value = errorMessage(error, 'Runtime connection failed.')
  }
}

async function useDesktopRuntimeToken(candidate) {
  try {
    const token = await readRuntimeToken(candidate.tokenPath)
    setApiToken(token, { remember: false })
    refreshApiTokenStatus()
    actionMessage.value = `Loaded local token for ${candidate.id}.`
  } catch (error) {
    actionError.value = errorMessage(error, 'Runtime token read failed.')
  }
}

function canRunMutatingAction() {
  if (apiTokenConfigured.value) return true
  actionError.value = 'Local API token required. Open Settings and paste logs/local_api_token.'
  actionMessage.value = ''
  return false
}

function canRunAdminAction() {
  if (!canRunMutatingAction()) return false
  if (localAdminEnabled.value) return true
  actionError.value = 'Local admin is disabled in GUI config.'
  actionMessage.value = ''
  return false
}

async function refreshOverview() {
  loading.value = true
  actionError.value = ''
  try {
    overview.value = await loadSettingsOverview()
    await loadQueueStatus(false)
  } catch (error) {
    actionError.value = errorMessage(error, '设置概览加载失败。')
  } finally {
    loading.value = false
  }
}

async function togglePackage(pkg) {
  if (!canRunAdminAction()) return
  const next = !pkg.enabled
  await confirmAndRun(
    `${next ? '启用' : '禁用'} package：${pkg.id}？`,
    async () => {
      await setPackageEnabled(pkg.id, next)
      actionMessage.value = `Package 已${next ? '启用' : '禁用'}：${pkg.id}`
      await refreshOverview()
    },
    { danger: !next }
  )
}

async function writeLockFile() {
  if (!canRunAdminAction()) return
  await confirmAndRun('写入 workspace package lock？', async () => {
    advancedResult.queue = null
    const result = await writePackageLock()
    actionMessage.value = 'Package lock 已写入。'
    advancedResult.diagnostics = result
    await refreshOverview()
  })
}

async function planRuntimeReload() {
  if (!canRunMutatingAction()) return
  await runAction(async () => {
    advancedResult.reload = await planReload({})
    actionMessage.value = 'Runtime reload plan 已生成。'
  })
}

async function applyRuntimeReload() {
  if (!canRunAdminAction()) return
  await confirmAndRun(
    '应用 runtime reload？运行中的任务可能受影响。',
    async () => {
      advancedResult.reload = await applyReload({ drain: false })
      actionMessage.value = 'Runtime reload 已提交。'
      await refreshOverview()
    },
    { danger: true }
  )
}

async function planMigrationRun() {
  if (!canRunMutatingAction()) return
  await runAction(async () => {
    advancedResult.migrations = await planMigrations()
    actionMessage.value = 'Migration plan 已生成。'
  })
}

async function applyMigrationRun() {
  if (!canRunAdminAction()) return
  await confirmAndRun(
    '应用数据库 migration？',
    async () => {
      advancedResult.migrations = await applyMigrations()
      actionMessage.value = 'Migration 已执行。'
      await refreshOverview()
    },
    { danger: true }
  )
}

async function loadEffectivePolicy() {
  await runAction(async () => {
    advancedResult.policy = await getEffectivePolicy()
    actionMessage.value = 'Effective policy 已加载。'
  })
}

async function collectDiagnosticBundle() {
  if (!canRunMutatingAction()) return
  await runAction(async () => {
    advancedResult.diagnostics = await collectDiagnostics()
    actionMessage.value = 'Diagnostic bundle 已生成。'
    await refreshOverview()
  })
}

async function loadQueueStatus(showMessage = true) {
  try {
    queueRecovery.value = await getQueueRecoveryStatus()
    advancedResult.queue = queueRecovery.value
    if (showMessage) actionMessage.value = 'Queue recovery 状态已刷新。'
  } catch (error) {
    if (showMessage) actionError.value = errorMessage(error, 'Queue recovery 状态加载失败。')
  }
}

async function recoverRuntimeQueue() {
  if (!canRunAdminAction()) return
  await confirmAndRun(
    '执行 queue recovery？',
    async () => {
      advancedResult.queue = await recoverQueue()
      queueRecovery.value = advancedResult.queue
      actionMessage.value = 'Queue recovery 已执行。'
    },
    { danger: true }
  )
}

async function abandonQueueItems() {
  if (!canRunAdminAction()) return
  await confirmAndRun(
    '放弃 stale queue items？该操作不可自动恢复。',
    async () => {
      advancedResult.queue = await abandonStaleQueue()
      queueRecovery.value = advancedResult.queue
      actionMessage.value = 'Stale queue items 已处理。'
    },
    { danger: true }
  )
}

async function loadObservability() {
  await runAction(async () => {
    advancedResult.observability = await getObservabilitySummary()
    actionMessage.value = 'Observability 摘要已加载。'
  })
}

async function confirmAndRun(message, fn, options = {}) {
  if (!(await askConfirm(message, options))) return
  await runAction(fn)
}

function askConfirm(message, options = {}) {
  return new Promise((resolve) => {
    confirmState.open = true
    confirmState.title = options.title || '确认操作'
    confirmState.message = message
    confirmState.danger = !!options.danger
    confirmState.resolve = resolve
  })
}

function resolveConfirm(value) {
  const resolve = confirmState.resolve
  confirmState.open = false
  confirmState.resolve = null
  if (resolve) resolve(value)
}

async function runAction(fn) {
  actionError.value = ''
  actionMessage.value = ''
  try {
    await fn()
  } catch (error) {
    actionError.value = error?.featureUnavailable
      ? '功能未启用或后端未暴露该接口 (404)。'
      : errorMessage(error)
  }
}

function featureStatus(value) {
  if (value?.featureUnavailable) return 'feature-unavailable (404)'
  return value?.status || value?.state || '--'
}

function pretty(value) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

onMounted(async () => {
  await refreshOverview()
  await discoverDesktopRuntimes()
})
</script>

<style scoped>
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.summary-card {
  min-width: 0;
}

.settings-line {
  display: flex;
  min-width: 0;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.settings-line span {
  color: var(--text-secondary);
}

.settings-line code {
  justify-content: flex-end;
}

.advanced-panel {
  min-width: 0;
}

.token-panel {
  min-width: 0;
}

.desktop-panel {
  min-width: 0;
}

.token-body {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.token-input {
  max-width: 420px;
}

.remember-token {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  color: var(--text-secondary);
}

.token-actions {
  margin: 0;
}

.advanced-stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.desktop-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.row-actions {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 8px;
}

.advanced-section {
  padding: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-surface-2);
}

.advanced-section summary {
  color: var(--text-primary);
  cursor: pointer;
  font-weight: 650;
}

.section-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.detail-grid div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-field);
}

.detail-grid span {
  color: var(--text-muted);
  font-size: 12px;
}

.source-cell {
  max-width: 280px;
  overflow: hidden;
  color: var(--text-secondary);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.notice {
  padding: 10px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
}

.notice-info {
  border-color: rgba(79, 140, 255, 0.34);
  background: var(--info-soft);
  color: #b9d1ff;
}

.notice-danger {
  border-color: rgba(239, 91, 91, 0.34);
  background: var(--danger-soft);
  color: #ffb4b4;
}

@media (max-width: 1180px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .detail-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>

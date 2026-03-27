<template>
  <div class="page-shell settings-page">
    <div class="page-heading">
      <div class="heading-block">
        <span class="eyebrow">Platform Envelope</span>
        <h1 class="page-title">Settings</h1>
        <p class="page-subtitle">A restrained status page for transport and local storage details. It should stay secondary to the main desk.</p>
      </div>

      <div class="heading-actions">
        <button class="btn btn-ghost" @click="refreshStatus">Refresh Status</button>
      </div>
    </div>

    <div class="settings-grid">
      <section class="settings-card">
        <span class="label">System State</span>
        <div class="settings-line">
          <span>Backend</span>
          <span class="pill" :class="healthOk ? 'pill-green' : 'pill-red'">{{ healthOk ? 'ok' : 'offline' }}</span>
        </div>
        <div class="settings-line">
          <span>Scheduler</span>
          <span class="pill" :class="isRunning ? 'pill-running' : 'pill-gray'">{{ isRunning ? 'running' : 'stopped' }}</span>
        </div>
        <div class="settings-line">
          <span>Last Check</span>
          <code>{{ lastCheckedText }}</code>
        </div>
        <div v-if="errorMessage" class="settings-error">{{ errorMessage }}</div>
      </section>

      <section class="settings-card">
        <span class="label">Transport</span>
        <div class="settings-line"><span>API Base</span><code>{{ cfg.api.base_url }}</code></div>
        <div class="settings-line"><span>Status Poll</span><code>{{ cfg.api.status_poll_ms }} ms</code></div>
        <div class="settings-line"><span>Queue Limit</span><code>{{ cfg.api.queue_list_limit }}</code></div>
        <div class="settings-line"><span>Dispatch Timeout</span><code>{{ cfg.api.dispatch_timeout_ms }} ms</code></div>
      </section>

      <section class="settings-card">
        <span class="label">Theme Lock</span>
        <div class="settings-note">
          <strong>Industrial Expedition Table</strong>
          <p>Matte plates, warm paper accents, muted orange warnings, and dossier-style panels. No HUD treatment.</p>
        </div>
      </section>

      <section class="settings-card">
        <span class="label">Local Keys</span>
        <div class="settings-line"><span>GUI Queue</span><code>{{ cfg.staging.storage_keys.queue }}</code></div>
        <div class="settings-line"><span>History</span><code>{{ cfg.staging.storage_keys.history }}</code></div>
        <div class="settings-line"><span>Auto Mode</span><code>{{ cfg.staging.storage_keys.auto }}</code></div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import axios from 'axios'
import { getGuiConfig } from '../config.js'

const cfg = getGuiConfig()
const api = axios.create({
  baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: cfg?.api?.timeout_ms || 5000,
})

const healthOk = ref(false)
const isRunning = ref(false)
const errorMessage = ref('')
const lastChecked = ref(null)

const lastCheckedText = computed(() => (lastChecked.value ? new Date(lastChecked.value).toLocaleString() : '--'))

async function refreshStatus() {
  try {
    const { data } = await api.get('/system/health')
    healthOk.value = data?.status === 'ok'
    isRunning.value = !!data?.is_running
    errorMessage.value = ''
  } catch (error) {
    healthOk.value = false
    isRunning.value = false
    errorMessage.value = error?.response?.data?.detail || error?.message || 'Unable to load system health.'
  } finally {
    lastChecked.value = Date.now()
  }
}

onMounted(refreshStatus)
</script>

<style scoped>
.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.settings-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  border: 1px solid rgba(224, 214, 186, 0.1);
  background: linear-gradient(180deg, rgba(56, 64, 68, 0.92), rgba(37, 45, 48, 0.92));
  box-shadow: var(--shadow-plate), var(--shadow-inset);
}

.settings-line {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.settings-note {
  padding: 12px 14px;
  border: 1px solid rgba(224, 214, 186, 0.1);
  background: rgba(25, 31, 33, 0.3);
}

.settings-note strong {
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 26px;
  letter-spacing: 0.08em;
  line-height: 0.9;
  text-transform: uppercase;
}

.settings-note p {
  margin: 8px 0 0;
  color: var(--text-soft);
  font-size: 13px;
  line-height: 1.65;
}

.settings-error {
  color: #e8c1bb;
  font-size: 13px;
}
</style>

<template>
  <div class="app">
    <DynamicBackground v-if="bgEnabled" />

    <div class="app-chrome">
      <Titlebar />

      <div class="shell-grid">
        <ProSidebar
          :active="route"
          :items="sidebarItems"
          @navigate="route = $event"
        />

        <div class="shell-column">
          <ProTopbar
            :route-label="activeRouteLabel"
            :is-connected="isBackendHealthy"
            :is-system-running="isSystemRunning"
          />

          <main class="main">
            <component :is="activeView" />
          </main>
        </div>
      </div>
    </div>

    <ToastHost />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import axios from 'axios'

import Titlebar from './components/Titlebar.vue'
import DynamicBackground from './components/DynamicBackground.vue'
import ProTopbar from './components/ProTopbar.vue'
import ProSidebar from './components/ProSidebar.vue'
import ToastHost from './components/ToastHost.vue'
import ExecuteView from './pages/ExecuteView.vue'
import RunsView from './pages/RunsView.vue'
import PlansView from './pages/PlansView.vue'
import SettingsView from './pages/SettingsView.vue'

import { useTheme } from './composables/useTheme.js'
import { getGuiConfig } from './config.js'

useTheme()

const cfg = getGuiConfig()
const route = ref(cfg?.navigation?.default_route || 'execute')
const isSystemRunning = ref(false)
const isBackendHealthy = ref(false)
const bgEnabled = computed(() => cfg?.background?.dynamic_enabled !== false)

const activeView = computed(() => {
  const views = {
    execute: ExecuteView,
    runs: RunsView,
    plans: PlansView,
    settings: SettingsView,
  }
  return views[route.value] || ExecuteView
})

const sidebarItems = cfg?.navigation?.items || [
  { key: 'execute', label: 'Execute', icon: 'execute' },
  { key: 'runs', label: 'Runs', icon: 'runs' },
  { key: 'plans', label: 'Plans', icon: 'plans' },
  { key: 'settings', label: 'Settings', icon: 'settings' },
]

const activeRouteLabel = computed(() =>
  sidebarItems.find((item) => item.key === route.value)?.label || 'Execute'
)

const api = axios.create({
  baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: cfg?.api?.timeout_ms || 5000,
})

let statusPollTimer = null
const statusPollMs = cfg?.api?.status_poll_ms || 3000

async function fetchSystemStatus() {
  try {
    const { data } = await api.get('/system/health')
    isSystemRunning.value = !!data?.is_running
    isBackendHealthy.value = data?.status === 'ok'
  } catch {
    isSystemRunning.value = false
    isBackendHealthy.value = false
  }
}

onMounted(() => {
  fetchSystemStatus()
  statusPollTimer = window.setInterval(fetchSystemStatus, statusPollMs)
})

onUnmounted(() => {
  if (statusPollTimer) {
    window.clearInterval(statusPollTimer)
    statusPollTimer = null
  }
})
</script>

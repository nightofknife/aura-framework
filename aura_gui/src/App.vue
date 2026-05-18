<template>
  <div class="app">
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

import Titlebar from './components/Titlebar.vue'
import ProTopbar from './components/ProTopbar.vue'
import ProSidebar from './components/ProSidebar.vue'
import ToastHost from './components/ToastHost.vue'
import ExecuteView from './pages/ExecuteView.vue'
import RunsView from './pages/RunsView.vue'
import PlansView from './pages/PlansView.vue'
import CapabilitiesView from './pages/CapabilitiesView.vue'
import SettingsView from './pages/SettingsView.vue'

import { useTheme } from './composables/useTheme.js'
import { getGuiConfig } from './config.js'
import { getHealth } from './api/system.js'

useTheme()

const cfg = getGuiConfig()
const route = ref(cfg?.navigation?.default_route || 'execute')
const isSystemRunning = ref(false)
const isBackendHealthy = ref(false)

const activeView = computed(() => {
  const views = {
    execute: ExecuteView,
    tasks: PlansView,
    runs: RunsView,
    capabilities: CapabilitiesView,
    settings: SettingsView,
  }
  return views[route.value] || ExecuteView
})

const sidebarItems = cfg?.navigation?.items || [
  { key: 'execute', label: '执行台', icon: 'play' },
  { key: 'tasks', label: '任务库', icon: 'library' },
  { key: 'runs', label: '运行记录', icon: 'history' },
  { key: 'capabilities', label: '能力中心', icon: 'cpu' },
  { key: 'settings', label: '设置', icon: 'settings' },
]

const activeRouteLabel = computed(() =>
  sidebarItems.find((item) => item.key === route.value)?.label || '执行台'
)

let statusPollTimer = null
const statusPollMs = cfg?.api?.status_poll_ms || 3000

async function fetchSystemStatus() {
  try {
    const data = await getHealth()
    isSystemRunning.value = !!data?.isRunning
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

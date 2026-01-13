<!-- === App.vue (REST API) === -->
<template>
  <div class="app">
    <DynamicBackground v-if="bgEnabled" />
    <Titlebar />

    <ProTopbar
      :is-connected="logsConnected"
      :is-system-running="isSystemRunning"
      env="dev"
      @start="startSystem"
      @stop="stopSystem"
    />

    <ProSidebar :active="route" @navigate="route=$event" :items="sidebarItems" />

    <main class="main">
      <component :is="activeView" />
    </main>

    <ToastHost />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import axios from 'axios'

// Components
import Titlebar from './components/Titlebar.vue'
import DynamicBackground from './components/DynamicBackground.vue'
import ProTopbar from './components/ProTopbar.vue'
import ProSidebar from './components/ProSidebar.vue'
import ToastHost from './components/ToastHost.vue'
import DashboardView from './pages/DashboardView.vue'
import PlansView from './pages/PlansView.vue'
import RunsView from './pages/RunsView.vue'
import ExecuteView from './pages/ExecuteView.vue'
import TaskWorkspaceView from './pages/TaskWorkspaceView.vue'
import AutomationView from './pages/AutomationView.vue'
import SettingsView from './pages/SettingsView.vue'

// Composables
import { useToasts } from './composables/useToasts.js'
import { useAuraSockets } from './composables/useAuraSockets.js'
import { useStagingRunner } from './composables/useStagingRunner.js'
import { useTheme } from './composables/useTheme.js'
import { getGuiConfig } from './config.js'

useTheme()
useStagingRunner()

const { push: toast } = useToasts()
const cfg = getGuiConfig()
const route = ref(cfg?.navigation?.default_route || 'execute')
const activeView = computed(() => {
  const views = {
    dashboard: DashboardView,
    runs: RunsView,
    execute: ExecuteView,
    plans: PlansView,
    automation: AutomationView,
    task_editor: TaskWorkspaceView,
    settings: SettingsView,
  }
  return views[route.value] || PlansView
})

const sidebarItems = cfg?.navigation?.items || [
  { key: 'dashboard', label: '仪表盘', icon: 'dashboard' },
  { key: 'execute', label: '执行台', icon: 'execute' },
  { key: 'runs', label: '运行中', icon: 'runs' },
  { key: 'plans', label: '方案/任务', icon: 'plans' },
  { key: 'automation', label: '自动化', icon: 'automation' },
  { key: 'task_editor', label: '任务编辑', icon: 'task_editor' },
  { key: 'settings', label: '设置', icon: 'settings' },
]

// WebSocket 连接和系统状态（来自 WebSocket 推送）
const { logs, isSystemRunning: wsSystemRunning, events } = useAuraSockets()
const logsConnected = computed(() => logs.isConnected.value)
const bgEnabled = computed(() => cfg?.background?.dynamic_enabled !== false)

// 本地系统状态（用于降级策略和手动刷新）
const isSystemRunning = ref(false)

// 监听 WebSocket 推送的系统状态变化
let previousSystemRunning = false
watch(wsSystemRunning, (newStatus) => {
  const statusChanged = previousSystemRunning !== newStatus
  isSystemRunning.value = newStatus

  if (statusChanged) {
    previousSystemRunning = newStatus
    if (newStatus) {
      toast({ type: 'success', title: 'Scheduler Started', message: 'System is now running' })
    } else {
      toast({ type: 'info', title: 'Scheduler Stopped', message: 'System is idle' })
    }
  }
}, { immediate: true })

const api = axios.create({
  baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: cfg?.api?.timeout_ms || 5000,
})

// 降级策略：WebSocket 未连接时使用 HTTP 轮询
let statusPollTimer = null
const STATUS_POLL_INTERVAL = cfg?.api?.status_poll_ms || 5000 // 降级时使用更长的轮询间隔

async function fetchSystemStatus() {
  try {
    const { data } = await api.get('/system/status')
    isSystemRunning.value = !!data.is_running
  } catch (err) {
    console.error('[App] Failed to fetch system status:', err)
    isSystemRunning.value = false
  }
}

function startStatusPolling() {
  if (statusPollTimer) return
  console.warn('[App] WebSocket disconnected, falling back to HTTP polling')
  statusPollTimer = setInterval(fetchSystemStatus, STATUS_POLL_INTERVAL)
}

function stopStatusPolling() {
  if (statusPollTimer) {
    clearInterval(statusPollTimer)
    statusPollTimer = null
    console.info('[App] HTTP polling stopped (WebSocket connected)')
  }
}

// 监听 WebSocket 连接状态，决定是否启用降级轮询
watch(() => events.isConnected.value, (connected) => {
  if (!connected) {
    startStatusPolling()
  } else {
    stopStatusPolling()
  }
}, { immediate: false })

async function startSystem() {
  try {
    await api.post('/system/start')
    toast({ type: 'info', title: 'Starting...', message: 'Scheduler is starting up' })
    // WebSocket 会自动推送状态更新，不需要轮询
    // 仅在 WebSocket 未连接时手动刷新
    if (!events.isConnected.value) {
      setTimeout(fetchSystemStatus, 500)
    }
  } catch (e) {
    toast({ type: 'error', title: 'Failed to start engine', message: e.message })
  }
}

async function stopSystem() {
  try {
    await api.post('/system/stop')
    toast({ type: 'info', title: 'Stopping...', message: 'Scheduler is shutting down' })
    // WebSocket 会自动推送状态更新，不需要轮询
    // 仅在 WebSocket 未连接时手动刷新
    if (!events.isConnected.value) {
      setTimeout(fetchSystemStatus, 500)
    }
  } catch (e) {
    toast({ type: 'error', title: 'Failed to stop engine', message: e.message })
  }
}

onMounted(() => {
  // 初始加载时获取一次系统状态（防止 WebSocket 未立即连接）
  fetchSystemStatus()
})

onUnmounted(() => {
  stopStatusPolling()
})

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    stopStatusPolling()
  })
}
</script>

<style scoped>
.app :deep(header.titlebar) {
  position: relative;
  z-index: 1000;
}
</style>


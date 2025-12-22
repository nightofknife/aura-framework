<!-- === App.vue (REST API 版本) === -->
<template>
  <div class="app">
    <!-- 动态背景 -->
    <DynamicBackground v-if="bgEnabled" />

    <!-- 自定义窗口标题栏 -->
    <Titlebar />

    <!-- 顶部工具栏 -->
    <ProTopbar
        :is-connected="logsConnected"
        :is-system-running="isSystemRunning"
        env="dev"
        @start="startSystem"
        @stop="stopSystem"
    />

    <!-- 侧边栏 -->
    <ProSidebar :active="route" @navigate="route=$event" :items="sidebarItems"/>

    <!-- 页面内容 -->
    <main class="main">
      <component :is="activeView"/>
    </main>

    <!-- 弹出通知 -->
    <ToastHost/>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import axios from 'axios'

// 组件
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
import SettingsView from './pages/SettingsView.vue'

// Composables
import { useToasts } from './composables/useToasts.js'
import { useAuraSockets } from './composables/useAuraSockets.js'
import { useStagingRunner } from './composables/useStagingRunner.js'
import { useTheme } from './composables/useTheme.js'
import { getGuiConfig } from './config.js'

// 初始化主题 & 单例 Runner
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
    task_editor: TaskWorkspaceView,
    settings: SettingsView,
  };
  return views[route.value] || PlansView;
})

const sidebarItems = cfg?.navigation?.items || [
  { key: 'dashboard', label: '仪表盘', icon: 'dashboard' },
  { key: 'execute', label: '执行台', icon: 'execute' },
  { key: 'runs', label: '运行中', icon: 'runs' },
  { key: 'plans', label: '方案/任务', icon: 'plans' },
  { key: 'task_editor', label: '任务编辑', icon: 'task_editor' },
  { key: 'settings', label: '设置', icon: 'settings' },
]

// ? 从 useAuraSockets 获取 logs 通道（用于显示连接状态）
const { logs } = useAuraSockets()
const logsConnected = computed(() => logs.isConnected.value)
const bgEnabled = computed(() => cfg?.background?.dynamic_enabled !== false)

// App.vue 自身维护的全局状态
const isSystemRunning = ref(false)
const api = axios.create({
  baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: cfg?.api?.timeout_ms || 5000,
})

let statusPollTimer = null
const STATUS_POLL_INTERVAL = cfg?.api?.status_poll_ms || 2000 // 2秒轮询一次系统状态

// --- API 调用 ---
async function fetchSystemStatus() {
  try {
    const { data } = await api.get('/system/status')
    const newStatus = !!data.is_running

    // 只在状态真正改变时才显示 toast
    if (isSystemRunning.value !== newStatus) {
      isSystemRunning.value = newStatus
      if (newStatus) {
        toast({ type: 'success', title: 'Scheduler Started', message: 'System is now running' })
      } else {
        toast({ type: 'info', title: 'Scheduler Stopped', message: 'System is idle' })
      }
    }
  } catch (err) {
    console.error('[App] Failed to fetch system status:', err)
    isSystemRunning.value = false
  }
}

async function startSystem() {
  try {
    await api.post('/system/start')
    toast({ type: 'info', title: 'Starting...', message: 'Scheduler is starting up' })
    // 立即轮询一次状态
    setTimeout(fetchSystemStatus, 500)
  } catch(e) {
    toast({ type: 'error', title: 'Failed to start engine', message: e.message })
  }
}

async function stopSystem() {
  try {
    await api.post('/system/stop')
    toast({ type: 'info', title: 'Stopping...', message: 'Scheduler is shutting down' })
    // 立即轮询一次状态
    setTimeout(fetchSystemStatus, 500)
  } catch(e) {
    toast({ type: 'error', title: 'Failed to stop engine', message: e.message })
  }
}

// --- 启动/停止轮询 ---
function startStatusPolling() {
  if (statusPollTimer) return
  statusPollTimer = setInterval(fetchSystemStatus, STATUS_POLL_INTERVAL)
}

function stopStatusPolling() {
  if (statusPollTimer) {
    clearInterval(statusPollTimer)
    statusPollTimer = null
  }
}

// --- 生命周期 ---
onMounted(() => {
  fetchSystemStatus() // 首次加载
  startStatusPolling() // 开始轮询
})

onUnmounted(() => {
  stopStatusPolling()
})

// ? 热更新清理（可选）
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    stopStatusPolling()
  })
}
</script>

<style scoped>
/* 样式保持不变 */
.app :deep(header.titlebar){
  position: relative;
  z-index: 1000;
}
</style>

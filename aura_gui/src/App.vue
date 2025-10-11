<!-- === App.vue === -->
<template>
  <div class="app">
    <!-- 动态背景 -->
    <DynamicBackground />

    <!-- 顶部工具栏 -->
    <ProTopbar
        :is-connected="isConnected"
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
import { ref, computed, onMounted, watch } from 'vue';
import axios from 'axios';

// 新增组件
import DynamicBackground from './components/DynamicBackground.vue';

// 现有组件
import ProTopbar from './components/ProTopbar.vue';
import ProSidebar from './components/ProSidebar.vue';
import ToastHost from './components/ToastHost.vue';
import DashboardView from './pages/DashboardView.vue';
import PlansView from './pages/PlansView.vue';
import RunsView from './pages/RunsView.vue';
import ExecuteView from './pages/ExecuteView.vue';

// Composables
import { useToasts } from './composables/useToasts.js';
import { useAuraSocket } from './composables/useAuraSocket.js';
import { useRuns } from './composables/useRuns.js';
import { useQueueStore } from './composables/useQueueStore.js';
import { useStagingRunner } from './composables/useStagingRunner.js';
import { useTheme } from './composables/useTheme.js'; // 引入主题管理

// 初始化主题
useTheme();
// 单例初始化，页面切换仍然保活
useStagingRunner();

const { push: toast } = useToasts();
const route = ref('execute'); // 默认改为 execute
const activeView = computed(() => {
  if (route.value === 'dashboard') return DashboardView;
  if (route.value === 'runs') return RunsView;
  if (route.value === 'execute') return ExecuteView;
  return PlansView;
});

const sidebarItems = [
  { key: 'dashboard', label: 'Dashboard', icon: '📊' },
  { key: 'execute', label: 'Execute', icon: '⚡️' }, // 图标更新
  { key: 'runs', label: 'Runs', icon: '🏃' },
  { key: 'plans', label: 'Plans', icon: '🗂️' },
  { key: 'settings', label: 'Settings', icon: '⚙️' },
];

const { isConnected, lastMessage } = useAuraSocket();
const { ingest: ingestRunEvt } = useRuns();
const { ingest: ingestQueueEvt } = useQueueStore();

const isSystemRunning = ref(false);
const api = axios.create({ baseURL: 'http://127.0.0.1:8000/api', timeout: 5000 });

async function fetchSystemStatus() {
  try {
    const { data } = await api.get('/system/status');
    isSystemRunning.value = !!data.is_running;
  } catch {
    isSystemRunning.value = false;
  }
}

async function startSystem() {
  try {
    await api.post('/system/start');
    toast({ type: 'success', title: 'Engine started' });
  } catch {
    toast({ type: 'error', title: 'Failed to start engine' });
  }
}

async function stopSystem() {
  try {
    await api.post('/system/stop');
    toast({ type: 'success', title: 'Engine stopped' });
  } catch {
    toast({ type: 'error', title: 'Failed to stop engine' });
  }
}

onMounted(fetchSystemStatus);

watch(lastMessage, evt => {
  if (!evt) return;
  if (evt.name === 'scheduler.started') {
    isSystemRunning.value = true;
    toast({ type: 'success', title: 'Scheduler started' });
  }
  if (evt.name === 'scheduler.stopped') {
    isSystemRunning.value = false;
    toast({ type: 'info', title: 'Scheduler stopped' });
  }
  if (evt.name === 'task.finished') {
    const ok = (evt.payload?.final_status || '').toUpperCase() === 'SUCCESS';
    toast({
      type: ok ? 'success' : 'error',
      title: ok ? 'Task succeeded' : 'Task failed',
      message: `${evt.payload?.plan_name || ''} / ${evt.payload?.task_name || ''}`,
      timeout: 5000
    });
  }
  ingestRunEvt(evt);
  ingestQueueEvt(evt);
});
</script>

<!-- === END App.vue === -->

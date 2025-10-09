<!-- src/App.vue -->
<template>
  <div id="app-container">
    <header>
      <h1>Aura Control Panel</h1>
    </header>

    <div class="system-controls-wrapper">
      <SystemControls
        :is-running="isSystemRunning"
        @start="startSystem"
        @stop="stopSystem"
      />
    </div>

    <div class="main-layout">
      <div class="plan-column">
        <PlanList
          :selected-plan="selectedPlan"
          @plan-selected="handlePlanSelection"
        />
      </div>
      <div class="task-column">
        <TaskList
          v-if="selectedPlan"
          :plan-name="selectedPlan"
          :tasks="tasks"
          :loading="tasksLoading"
          :error="tasksError"
          @open-run-modal="handleOpenModal"
        />
        <div v-else class="placeholder">
          Select a plan from the left to see its tasks.
        </div>
      </div>
    </div>

    <RunTaskModal
      :show="isModalVisible"
      :task="taskToRun"
      @close="handleCloseModal"
      @run="handleRunTask"
    />

    <!-- 新增：运行监控与日志 -->
    <section class="runs-wrapper">
      <RunMonitor
        :active="activeRuns"
        :recent="recentRuns"
        @open-log="openLogById"
      />
    </section>
    <LogViewer
      :show="logViewerVisible"
      :run="selectedRunForLogs"
      @close="logViewerVisible=false"
    />

    <footer class="debug-panel" v-if="lastMessage">
      <h3>Last Real-time Event:</h3>
      <pre>{{ lastMessage }}</pre>
    </footer>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, computed } from 'vue';
import axios from 'axios';

import PlanList from './components/PlanList.vue';
import TaskList from './components/TaskList.vue';
import RunTaskModal from './components/RunTaskModal.vue';
import SystemControls from './components/SystemControls.vue';

import RunMonitor from './components/RunMonitor.vue';
import LogViewer from './components/LogViewer.vue';

import { useAuraSocket } from './composables/useAuraSocket.js';
import { useRuns } from './composables/useRuns.js';

const { isConnected, lastMessage } = useAuraSocket();
const { activeRuns, recentRuns, runsById, ingest } = useRuns();

const isSystemRunning = ref(false);

const selectedPlan = ref(null);
const tasks = ref([]);
const tasksLoading = ref(false);
const tasksError = ref(null);

const isModalVisible = ref(false);
const taskToRun = ref(null);

// 日志查看
const logViewerVisible = ref(false);
const selectedRunId = ref(null);
const selectedRunForLogs = computed(() =>
  selectedRunId.value ? runsById.value[selectedRunId.value] : null
);


function openLogById(id){
  selectedRunId.value = id;
  logViewerVisible.value = true;
}

const apiClient = axios.create({
  baseURL: 'http://127.0.0.1:8000/api',
  timeout: 5000,
});

const fetchSystemStatus = async () => {
  try {
    const { data } = await apiClient.get('/system/status');
    isSystemRunning.value = data.is_running;
  } catch {
    isSystemRunning.value = false;
  }
};

const startSystem = async () => {
  try {
    await apiClient.post('/system/start');
  } catch (e) {
    console.error(e);
    alert('Error: Could not start the system.');
  }
};

const stopSystem = async () => {
  try {
    await apiClient.post('/system/stop');
  } catch (e) {
    console.error(e);
    alert('Error: Could not stop the system.');
  }
};

onMounted(() => {
  fetchSystemStatus();
});

// 利用实时事件：更新系统状态 + 推进运行与日志
watch(lastMessage, (msg) => {
  if (!msg) return;

  // 1) 系统启停
  const eventName = msg?.payload?.name ?? msg?.name;
  if (eventName === 'scheduler.started') isSystemRunning.value = true;
  if (eventName === 'scheduler.stopped') isSystemRunning.value = false;

  // 2) 运行/日志
  ingest(msg);
});

// 任务列表逻辑（不变）
const fetchTasksForPlan = async (planName) => {
  tasksLoading.value = true;
  tasksError.value = null;
  tasks.value = [];
  try {
    const { data } = await apiClient.get(`/plans/${planName}/tasks`);
    tasks.value = data;
  } catch (err) {
    console.error(`Failed to fetch tasks for ${planName}:`, err);
    tasksError.value = `Failed to load tasks for ${planName}.`;
  } finally {
    tasksLoading.value = false;
  }
};

const handlePlanSelection = (planName) => {
  selectedPlan.value = planName;
  fetchTasksForPlan(planName);
};

const handleOpenModal = (task) => {
  taskToRun.value = task;
  isModalVisible.value = true;
};

const handleCloseModal = () => {
  isModalVisible.value = false;
  taskToRun.value = null;
};

const handleRunTask = async (inputsData) => {
  if (!taskToRun.value) return;

  const payload = {
    plan_name: selectedPlan.value,
    task_name: taskToRun.value.task_name_in_plan,
    inputs: inputsData,
  };

  try {
    const { data } = await apiClient.post('/tasks/run', payload);
    console.log('Task run successfully:', data.message);
    alert(`Success: ${data.message}`);
  } catch (error) {
    console.error('Failed to run task:', error?.response?.data?.detail || error.message);
    alert(`Error: ${error?.response?.data?.detail || 'An unknown error occurred.'}`);
  } finally {
    handleCloseModal();
  }
};
</script>

<style>
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background-color: #f0f2f5;
  color: #333;
}
#app-container { padding: 20px; }
header { text-align: center; margin-bottom: 20px; }
header h1 { color: #444; font-size: 2em; margin: 0; }

.system-controls-wrapper {
  max-width: 1200px;
  margin: 0 auto 20px auto;
}
.main-layout {
  display: flex; gap: 20px; max-width: 1200px; margin: 0 auto 20px auto;
}
.plan-column { flex: 1; max-width: 400px; }
.task-column { flex: 2; }
.placeholder {
  display: flex; align-items: center; justify-content: center; height: 200px;
  background-color: #fff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); color: #aaa;
}

.runs-wrapper {
  max-width: 1200px; margin: 0 auto; margin-top: 20px;
}
.debug-panel {
  max-width: 1200px; margin: 40px auto; padding: 15px;
  background-color: #2d2d2d; color: #f0f0f0; border-radius: 8px;
}
.debug-panel pre {
  white-space: pre-wrap; word-wrap: break-word;
  font-family: 'Courier New', Courier, monospace; font-size: 0.85em;
}
</style>

<!-- src/App.vue -->
<template>
  <div id="app-container">
    <header>
      <h1>Aura Control Panel</h1>
    </header>

    <!-- 新增：系统控制组件被放在顶部最显眼的位置 -->
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

    <footer class="debug-panel" v-if="lastMessage">
      <h3>Last Real-time Event:</h3>
      <pre>{{ lastMessage }}</pre>
    </footer>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue';
import axios from 'axios';
import PlanList from './components/PlanList.vue';
import TaskList from './components/TaskList.vue';
import RunTaskModal from './components/RunTaskModal.vue';
import SystemControls from './components/SystemControls.vue'; // 导入新组件
import { useAuraSocket } from './composables/useAuraSocket.js';

// isConnected 仍然有用，可以用来判断WebSocket连接本身
const { isConnected, lastMessage } = useAuraSocket();

// --- 新增：系统运行状态 ---
const isSystemRunning = ref(false);

const selectedPlan = ref(null);
const tasks = ref([]);
const tasksLoading = ref(false);
const tasksError = ref(null);
const isModalVisible = ref(false);
const taskToRun = ref(null);

const apiClient = axios.create({
  baseURL: 'http://127.0.0.1:8000/api',
  timeout: 5000,
});

// --- 新增：获取系统初始状态的函数 ---
const fetchSystemStatus = async () => {
  try {
    const response = await apiClient.get('/system/status');
    isSystemRunning.value = response.data.is_running;
  } catch (error) {
    console.error('Failed to fetch system status:', error);
    isSystemRunning.value = false; // 出错时假定为停止状态
  }
};

// --- 新增：调用API启动系统的函数 ---
const startSystem = async () => {
  try {
    await apiClient.post('/system/start');
    // 注意：我们不在这里直接设置 isSystemRunning = true
    // 我们依赖WebSocket的实时事件来更新状态，这是更可靠的做法
  } catch (error) {
    console.error('Failed to start system:', error);
    alert('Error: Could not start the system.');
  }
};

// --- 新增：调用API停止系统的函数 ---
const stopSystem = async () => {
  try {
    await apiClient.post('/system/stop');
  } catch (error)
 {
    console.error('Failed to stop system:', error);
    alert('Error: Could not stop the system.');
  }
};

// onMounted: 应用加载时，获取一次系统状态
onMounted(() => {
  fetchSystemStatus();
});

// --- 新增：使用 watch 监听实时事件来更新状态 ---
watch(lastMessage, (newMessage) => {
  // 1. 检查外层信封，确保它是一个 "event" 类型的消息
  if (newMessage && newMessage.type === 'event' && newMessage.payload) {

    // 2. 拆开信封，拿出里面的事件内容
    const event = newMessage.payload;

    // 3. 检查里面的事件内容是否有 'name' 属性
    if (event && event.name) {
      const eventName = event.name;
      if (eventName === 'scheduler.started') {
        isSystemRunning.value = true;
      } else if (eventName === 'scheduler.stopped') {
        isSystemRunning.value = false;
      }
    }
  }
});


// --- 以下是之前的函数，保持不变 ---

const fetchTasksForPlan = async (planName) => {
  tasksLoading.value = true;
  tasksError.value = null;
  tasks.value = [];
  try {
    const response = await apiClient.get(`/plans/${planName}/tasks`);
    tasks.value = response.data;
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
    const response = await apiClient.post('/tasks/run', payload);
    console.log('Task run successfully:', response.data.message);
    alert(`Success: ${response.data.message}`);
  } catch (error) {
    console.error('Failed to run task:', error.response?.data?.detail || error.message);
    alert(`Error: ${error.response?.data?.detail || 'An unknown error occurred.'}`);
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
  #app-container {
    padding: 20px;
  }
  header {
    text-align: center;
    margin-bottom: 20px;
  }
  header h1 {
    color: #444;
    font-size: 2em;
    margin: 0;
  }
  .system-controls-wrapper {
    max-width: 1200px;
    margin: 0 auto 20px auto;
  }
  .main-layout {
    display: flex;
    gap: 20px;
    max-width: 1200px;
    margin: 0 auto;
  }
  .plan-column {
    flex: 1;
    max-width: 400px;
  }
  .task-column {
    flex: 2;
  }
  .placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    background-color: #fff;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    color: #aaa;
  }
  .debug-panel {
    max-width: 1200px;
    margin: 40px auto;
    padding: 15px;
    background-color: #2d2d2d;
    color: #f0f0f0;
    border-radius: 8px;
  }
  .debug-panel pre {
    white-space: pre-wrap;
    word-wrap: break-word;
    font-family: 'Courier New', Courier, monospace;
    font-size: 0.85em;
  }
</style>

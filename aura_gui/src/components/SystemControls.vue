<!-- src/components/SystemControls.vue -->
<template>
  <div class="controls-container">
    <div class="status-display">
      <span>System Status:</span>
      <strong :class="statusClass">{{ statusText }}</strong>
    </div>
    <div class="button-group">
      <button @click="onStart" :disabled="isRunning" class="btn btn-start">
        Start Engine
      </button>
      <button @click="onStop" :disabled="!isRunning" class="btn btn-stop">
        Stop Engine
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';

// 这个组件非常简单，它只负责显示状态和通知父组件用户的意图
const props = defineProps({
  isRunning: Boolean,
});

const emit = defineEmits(['start', 'stop']);

// computed属性会根据它的依赖项自动更新
const statusText = computed(() => (props.isRunning ? 'Running' : 'Stopped'));
const statusClass = computed(() => (props.isRunning ? 'status-running' : 'status-stopped'));

const onStart = () => {
  emit('start');
};

const onStop = () => {
  emit('stop');
};
</script>

<style scoped>
.controls-container {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px 20px;
  background-color: #fff;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
  margin-bottom: 20px;
}
.status-display {
  font-size: 1.1em;
}
.status-display span {
  color: #555;
}
.status-display strong {
  margin-left: 10px;
  padding: 4px 8px;
  border-radius: 4px;
  color: white;
}
.status-running {
  background-color: #28a745;
}
.status-stopped {
  background-color: #dc3545;
}
.btn {
  padding: 10px 20px;
  border: none;
  border-radius: 5px;
  cursor: pointer;
  font-weight: bold;
  font-size: 1em;
  transition: background-color 0.2s, opacity 0.2s;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-start {
  background-color: #28a745;
  color: white;
  margin-right: 10px;
}
.btn-start:not(:disabled):hover {
  background-color: #218838;
}
.btn-stop {
  background-color: #dc3545;
  color: white;
}
.btn-stop:not(:disabled):hover {
  background-color: #c82333;
}
</style>

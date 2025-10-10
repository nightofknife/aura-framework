<template>
  <div class="sys-controls">
    <div class="sys-status">
      <span class="item-title">System Status</span>
      <span class="status-pill" :class="isRunning ? 'status-success' : 'status-error'">
        {{ isRunning ? 'Running' : 'Stopped' }}
      </span>
    </div>
    <div class="sys-actions">
      <button @click="$emit('start')" :disabled="isRunning" class="btn btn-primary">Start</button>
      <button @click="$emit('stop')" :disabled="!isRunning" class="btn btn-danger">Stop</button>
    </div>
  </div>
</template>

<script setup>
defineProps({isRunning: Boolean});
</script>

<style scoped>
.sys-controls {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.sys-status {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sys-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.item-title {
  font-weight: 700;
  color: var(--text-700);
}
</style>

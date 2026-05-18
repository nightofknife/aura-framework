<template>
  <header class="topbar">
    <div class="topbar__title">
      <strong>{{ routeLabel }}</strong>
      <span>本地运行控制台</span>
    </div>

    <div class="topbar__status">
      <span class="pill" :class="isConnected ? 'pill-green' : 'pill-red'">
        {{ isConnected ? '后端在线' : '后端离线' }}
      </span>
      <span class="pill" :class="isSystemRunning ? 'pill-running' : 'pill-gray'">
        {{ isSystemRunning ? '调度运行中' : '调度已停止' }}
      </span>
    </div>
  </header>
</template>

<script setup>
defineProps({
  routeLabel: { type: String, default: '执行台' },
  isConnected: Boolean,
  isSystemRunning: Boolean,
})
</script>

<style scoped>
.topbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  min-width: 0;
  padding: 0 20px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-app);
}

.topbar__title {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.topbar__title strong {
  color: var(--text-primary);
  font-size: 16px;
  font-weight: 650;
}

.topbar__title span {
  color: var(--text-muted);
  font-size: 12px;
}

.topbar__status {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}
</style>

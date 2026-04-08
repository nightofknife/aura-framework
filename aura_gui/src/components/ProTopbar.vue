<template>
  <header class="topbar">
    <div class="topbar__plate">
      <span class="topbar__kicker">Current Surface</span>
      <strong class="topbar__title">{{ routeLabel }}</strong>
      <span class="topbar__subtitle">Minimal platform contract: plans, dispatch, queue, runs.</span>
    </div>

    <div class="topbar__status">
      <span class="pill" :class="isConnected ? 'pill-green' : 'pill-red'">
        {{ isConnected ? 'backend online' : 'backend offline' }}
      </span>
      <span class="pill" :class="isSystemRunning ? 'pill-running' : 'pill-gray'">
        {{ isSystemRunning ? 'scheduler live' : 'scheduler stopped' }}
      </span>
    </div>
  </header>
</template>

<script setup>
defineProps({
  routeLabel: { type: String, default: 'Execute' },
  isConnected: Boolean,
  isSystemRunning: Boolean,
})
</script>

<style scoped>
.topbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: center;
  padding: 18px 28px 14px 0;
}

.topbar__plate {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
  padding: 14px 16px 12px;
  border: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(58, 67, 71, 0.92), rgba(39, 47, 50, 0.92));
  box-shadow: var(--shadow-plate), var(--shadow-inset);
}

.topbar__kicker {
  color: var(--paper);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
}

.topbar__title {
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 38px;
  letter-spacing: 0.08em;
  line-height: 0.88;
  text-transform: uppercase;
}

.topbar__subtitle {
  color: var(--text-soft);
  font-size: 12px;
}

.topbar__status {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
  align-items: center;
}
</style>

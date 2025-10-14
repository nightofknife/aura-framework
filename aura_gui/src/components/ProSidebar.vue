<!-- === src/components/ProSidebar.vue (with Logo) === -->
<template>
  <aside class="sidebar">
    <div class="logo-area">
      <strong class="logo">Aura Orchestrator</strong>
    </div>
    <nav class="nav">
      <a
          v-for="i in items"
          :key="i.key"
          href="#"
          class="item"
          :class="{ active: i.key === active }"
          @click.prevent="$emit('navigate', i.key)"
      >
        <span class="icon">{{ i.icon }}</span>
        <span class="label">{{ i.label }}</span>
        <div class="glow-indicator"></div>
      </a>
    </nav>
  </aside>
</template>

<script setup>
// script内容不变
defineProps({
  active: { type: String, default: 'dashboard' },
  items: {
    type: Array,
    default: () => [
      { key: 'dashboard', label: 'Dashboard', icon: '📊' },
      { key: 'execute', label: 'Execute', icon: '⚡️' },
      { key: 'runs', label: 'Runs', icon: '🏃' },
      { key: 'plans', label: 'Plans', icon: '🗂️' },
      { key: 'settings', label: 'Settings', icon: '⚙️' },
    ]
  }
});
defineEmits(['navigate']);
</script>

<style scoped>
.logo-area {
  height: 60px; /* Match topbar height */
  display: flex;
  align-items: center;
  padding: 0 14px;
  border-bottom: 1px solid var(--border-frosted);
  margin: -12px -12px 12px -12px; /* Absorb parent padding */
}
.logo { font-size: 16px; color: var(--text-primary); }
/* 其他样式不变 */
.nav { display: flex; flex-direction: column; gap: 8px; }
.item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-weight: 600;
  text-decoration: none;
  position: relative;
  overflow: hidden;
  transition: all var(--dur) var(--ease);
}
.item:hover {
  background: rgba(128, 128, 128, 0.1);
  color: var(--text-primary);
}
.item.active {
  color: var(--text-primary);
  background: rgba(88, 101, 242, 0.1);
}
.icon { font-size: 18px; }
.label { line-height: 1; }

/* 辉光流动效果 */
.glow-indicator {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--primary-accent);
  box-shadow: 0 0 8px var(--glow-accent), 0 0 16px var(--glow-accent);
  transform: translateX(-100%);
  transition: transform var(--dur) var(--ease);
}
.item.active .glow-indicator {
  transform: translateX(0);
}
</style>
<!-- === END src/components/ProSidebar.vue (with Logo) === -->

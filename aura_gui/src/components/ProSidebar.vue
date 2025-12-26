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
        <span class="icon" aria-hidden="true">
          <svg v-if="i.icon === 'dashboard'" viewBox="0 0 24 24" class="icon-svg" fill="none" stroke="currentColor" stroke-width="1.6">
            <rect x="3" y="3" width="8" height="8" rx="2" />
            <rect x="13" y="3" width="8" height="5" rx="2" />
            <rect x="13" y="10" width="8" height="11" rx="2" />
            <rect x="3" y="13" width="8" height="8" rx="2" />
          </svg>
          <svg v-else-if="i.icon === 'execute'" viewBox="0 0 24 24" class="icon-svg" fill="currentColor">
            <path d="M8 5l11 7-11 7z" />
          </svg>
          <svg v-else-if="i.icon === 'runs'" viewBox="0 0 24 24" class="icon-svg" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="8" />
            <path d="M12 8v4l3 2" />
          </svg>
          <svg v-else-if="i.icon === 'plans'" viewBox="0 0 24 24" class="icon-svg" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
          </svg>
          <svg v-else-if="i.icon === 'automation'" viewBox="0 0 24 24" class="icon-svg" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="5" width="18" height="16" rx="2" />
            <path d="M8 3v4M16 3v4M3 9h18" />
            <path d="M8.5 14.5l2 2 5-5" />
          </svg>
          <svg v-else-if="i.icon === 'task_editor'" viewBox="0 0 24 24" class="icon-svg" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="6" cy="6" r="2" />
            <circle cx="18" cy="6" r="2" />
            <circle cx="12" cy="18" r="2" />
            <path d="M8 7.5l4 8M16 7.5l-4 8M8 6h8" />
          </svg>
          <svg v-else-if="i.icon === 'settings'" viewBox="0 0 24 24" class="icon-svg" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 6h16" />
            <path d="M4 12h16" />
            <path d="M4 18h16" />
            <circle cx="9" cy="6" r="2" />
            <circle cx="15" cy="12" r="2" />
            <circle cx="7" cy="18" r="2" />
          </svg>
          <span v-else>{{ i.icon }}</span>
        </span>
        <span class="label">{{ i.label }}</span>
        <div class="glow-indicator"></div>
      </a>
    </nav>
  </aside>
</template>

<script setup>
// script鍐呭涓嶅彉
defineProps({
  active: { type: String, default: 'dashboard' },
  items: {
    type: Array,
    default: () => [
      { key: 'dashboard', label: '仪表盘', icon: 'dashboard' },
      { key: 'execute', label: '执行台', icon: 'execute' },
      { key: 'runs', label: '运行中', icon: 'runs' },
      { key: 'plans', label: '方案/任务', icon: 'plans' },
      { key: 'automation', label: '自动化', icon: 'automation' },
      { key: 'task_editor', label: '任务编辑', icon: 'task_editor' },
      { key: 'settings', label: '设置', icon: 'settings' },
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
/* 鍏朵粬鏍峰紡涓嶅彉 */
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
.icon {
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
}
.icon-svg {
  width: 18px;
  height: 18px;
  display: block;
}
.label { line-height: 1; }

/* 杈夊厜娴佸姩鏁堟灉 */
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




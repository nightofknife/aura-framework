<template>
  <aside class="sidebar">
    <div class="sidebar__brand">
      <strong>Aura</strong>
      <span>桌面自动化工作台</span>
    </div>

    <nav class="sidebar__nav" aria-label="主导航">
      <button
        v-for="item in items"
        :key="item.key"
        class="sidebar__item"
        :class="{ 'is-active': item.key === active }"
        @click="$emit('navigate', item.key)"
      >
        <component :is="iconFor(item.icon)" class="icon" />
        <span>{{ item.label }}</span>
      </button>
    </nav>
  </aside>
</template>

<script setup>
import { Cpu, History, Library, Play, Settings } from 'lucide-vue-next'

defineProps({
  active: { type: String, default: 'execute' },
  items: { type: Array, default: () => [] },
})

defineEmits(['navigate'])

const icons = {
  play: Play,
  execute: Play,
  library: Library,
  tasks: Library,
  history: History,
  runs: History,
  cpu: Cpu,
  capabilities: Cpu,
  settings: Settings,
}

function iconFor(name) {
  return icons[name] || Play
}
</script>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 16px 12px;
  border-right: 1px solid var(--border-subtle);
  background: var(--bg-sidebar);
}

.sidebar__brand {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 4px 8px 10px;
}

.sidebar__brand strong {
  color: var(--text-primary);
  font-size: 16px;
  font-weight: 700;
}

.sidebar__brand span {
  color: var(--text-muted);
  font-size: 12px;
}

.sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.sidebar__item {
  display: flex;
  min-height: 38px;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  border-left: 3px solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
}

.sidebar__item:hover {
  background: var(--bg-surface);
  color: var(--text-primary);
}

.sidebar__item.is-active {
  border-left-color: var(--accent);
  background: var(--accent-soft);
  color: var(--text-primary);
}

.sidebar__item.is-active .icon {
  color: var(--accent-hover);
}
</style>

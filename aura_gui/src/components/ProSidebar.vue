<template>
  <aside class="sidebar">
    <div class="sidebar__brand">
      <span class="sidebar__tag">Aura Dispatch Desk</span>
      <div class="sidebar__serial">ORCH-01</div>
      <strong class="sidebar__logo">EXPEDITION</strong>
      <p class="sidebar__copy">Industrial task table for brief selection, local arrangement, and scheduler handoff.</p>
    </div>

    <nav class="sidebar__nav">
      <button
        v-for="item in items"
        :key="item.key"
        class="sidebar__item"
        :class="{ 'is-active': item.key === active }"
        @click="$emit('navigate', item.key)"
      >
        <span class="sidebar__index">{{ order[item.key] || '00' }}</span>
        <span class="sidebar__meta">
          <span class="sidebar__label">{{ item.label }}</span>
          <span class="sidebar__hint">{{ hints[item.key] || 'Section' }}</span>
        </span>
      </button>
    </nav>

    <div class="sidebar__footer">
      <span class="section-tag">Desktop Only</span>
      <p>No mobile layout. This surface is meant to feel like a fixed work table.</p>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  active: { type: String, default: 'execute' },
  items: { type: Array, default: () => [] },
})

defineEmits(['navigate'])

const order = {
  execute: '01',
  runs: '02',
  plans: '03',
  settings: '04',
}

const hints = {
  execute: 'Dispatch table',
  runs: 'Route record',
  plans: 'Task folio',
  settings: 'Platform envelope',
}
</script>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 18px 18px 22px 22px;
  border-right: 1px solid rgba(224, 214, 186, 0.08);
  background: linear-gradient(180deg, rgba(31, 38, 41, 0.88), rgba(23, 29, 31, 0.72));
}

.sidebar__brand {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 18px 16px 16px;
  border: 1px solid var(--line);
  background:
    linear-gradient(180deg, rgba(58, 67, 71, 0.94), rgba(40, 48, 51, 0.94));
  box-shadow: var(--shadow-plate), var(--shadow-inset);
}

.sidebar__tag,
.sidebar__serial {
  color: var(--paper);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
}

.sidebar__serial {
  color: var(--ember-2);
}

.sidebar__logo {
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 52px;
  letter-spacing: 0.08em;
  line-height: 0.88;
  text-transform: uppercase;
}

.sidebar__copy,
.sidebar__footer p {
  margin: 0;
  color: var(--text-soft);
  font-size: 13px;
  line-height: 1.65;
}

.sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sidebar__item {
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid rgba(224, 214, 186, 0.09);
  background: linear-gradient(180deg, rgba(53, 61, 65, 0.92), rgba(35, 43, 46, 0.92));
  color: var(--text-main);
  text-align: left;
}

.sidebar__item:hover {
  border-color: rgba(224, 214, 186, 0.18);
}

.sidebar__item.is-active {
  border-color: rgba(199, 104, 63, 0.24);
  background:
    linear-gradient(90deg, rgba(199, 104, 63, 0.14), transparent 28%),
    linear-gradient(180deg, rgba(61, 69, 73, 0.96), rgba(39, 47, 50, 0.96));
}

.sidebar__index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  border: 1px solid rgba(224, 214, 186, 0.12);
  background: rgba(22, 27, 29, 0.44);
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 24px;
  letter-spacing: 0.08em;
}

.sidebar__meta {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.sidebar__label {
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 28px;
  letter-spacing: 0.08em;
  line-height: 0.88;
  text-transform: uppercase;
}

.sidebar__hint {
  color: var(--text-soft);
  font-size: 12px;
}

.sidebar__footer {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
</style>

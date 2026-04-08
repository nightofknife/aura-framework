<template>
  <div class="runs-list-shell">
    <RecycleScroller
      :items="runs"
      :item-size="itemSize"
      key-field="key"
      class="runs-list"
      :style="{ height: maxHeight || '70vh' }"
      v-slot="{ item }"
    >
      <article class="run-ticket" @click="$emit('row-click', item)">
        <div class="run-ticket__serial">{{ shortCid(item.cid || item.id) }}</div>

        <div class="run-ticket__body">
          <div class="run-ticket__head">
            <div>
              <strong class="run-ticket__title">{{ item.plan_name || '-' }}</strong>
              <span class="run-ticket__task">{{ item.task_name || item.task_ref || '-' }}</span>
            </div>
            <span class="pill" :class="statusClass(item.status)">{{ item.status || 'queued' }}</span>
          </div>

          <div class="run-ticket__track">
            <span class="run-ticket__track-line"></span>
            <span class="run-ticket__track-fill" :class="statusClass(item.status)"></span>
          </div>

          <div class="run-ticket__meta">
            <span v-if="item.startedAt">Start {{ formatTime(item.startedAt) }}</span>
            <span v-if="item.finishedAt">Finish {{ formatTime(item.finishedAt) }}</span>
            <span v-if="item.elapsed != null">Duration {{ formatElapsed(item.elapsed) }}</span>
          </div>
        </div>
      </article>
    </RecycleScroller>

    <div v-if="runs.length === 0" class="empty-state">No run records match the current filter.</div>
  </div>
</template>

<script setup>
import { RecycleScroller } from 'vue-virtual-scroller'

defineProps({
  runs: { type: Array, required: true },
  maxHeight: { type: String, default: '70vh' },
  itemSize: { type: Number, default: 124 },
})

defineEmits(['row-click'])

function statusClass(status) {
  const value = (status || 'queued').toLowerCase()
  if (value === 'running') return 'pill-running'
  if (value === 'success') return 'pill-green'
  if (value === 'failed') return 'pill-red'
  if (value === 'cancelled') return 'pill-gray'
  return 'pill-queued'
}

function formatTime(value) {
  const date = value instanceof Date ? value : new Date(value)
  return date.toLocaleString()
}

function formatElapsed(ms) {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const min = Math.floor(ms / 60000)
  const sec = Math.floor((ms % 60000) / 1000)
  return `${min}m ${sec}s`
}

function shortCid(value) {
  if (!value) return '----'
  return String(value).slice(0, 8)
}
</script>

<style scoped>
.runs-list-shell {
  position: relative;
}

.runs-list {
  overflow: auto;
  border: 1px solid rgba(224, 214, 186, 0.08);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.008), transparent 10%),
    linear-gradient(180deg, rgba(56, 64, 68, 0.92), rgba(37, 45, 48, 0.92));
  box-shadow: var(--shadow-inset);
}

.run-ticket {
  display: grid;
  grid-template-columns: 100px minmax(0, 1fr);
  gap: 14px;
  min-height: 124px;
  padding: 16px;
  border-bottom: 1px solid rgba(224, 214, 186, 0.08);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease);
}

.run-ticket:hover {
  background: rgba(201, 187, 149, 0.04);
}

.run-ticket__serial {
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(224, 214, 186, 0.12);
  background:
    linear-gradient(180deg, rgba(199, 104, 63, 0.2), transparent 32%),
    rgba(31, 38, 41, 0.68);
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 28px;
  letter-spacing: 0.08em;
}

.run-ticket__body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.run-ticket__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: start;
}

.run-ticket__title {
  display: block;
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 32px;
  letter-spacing: 0.08em;
  line-height: 0.9;
  text-transform: uppercase;
}

.run-ticket__task {
  color: var(--text-soft);
  font-family: var(--font-mono);
  font-size: 11px;
}

.run-ticket__track {
  position: relative;
  height: 12px;
  border: 1px solid rgba(224, 214, 186, 0.08);
  background: rgba(20, 25, 27, 0.44);
}

.run-ticket__track-line,
.run-ticket__track-fill {
  position: absolute;
  inset: 0;
}

.run-ticket__track-line {
  background: linear-gradient(90deg, rgba(201, 187, 149, 0.08), rgba(201, 187, 149, 0.24), rgba(201, 187, 149, 0.08));
}

.run-ticket__track-fill.pill-running {
  background: rgba(139, 162, 110, 0.24);
}

.run-ticket__track-fill.pill-green {
  background: rgba(156, 181, 141, 0.24);
}

.run-ticket__track-fill.pill-red {
  background: rgba(198, 113, 99, 0.24);
}

.run-ticket__track-fill.pill-gray {
  background: rgba(143, 143, 134, 0.2);
}

.run-ticket__track-fill.pill-queued {
  background: rgba(201, 157, 84, 0.22);
}

.run-ticket__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  color: var(--text-soft);
  font-size: 12px;
}
</style>

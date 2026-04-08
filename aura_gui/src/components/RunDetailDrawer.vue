<template>
  <div v-if="open" class="archive-mask" @click.self="$emit('close')">
    <aside class="archive-board">
      <header class="archive-board__head">
        <div>
          <span class="archive-board__kicker">Execution Dossier</span>
          <strong class="archive-board__title">{{ run?.task_name || run?.task_ref || '-' }}</strong>
        </div>
        <button class="btn btn-ghost btn-sm" @click="$emit('close')">Close</button>
      </header>

      <div class="archive-board__tabs">
        <button class="archive-board__tab" :class="{ 'is-active': tab === 'timeline' }" @click="tab = 'timeline'">Timeline</button>
        <button class="archive-board__tab" :class="{ 'is-active': tab === 'payload' }" @click="tab = 'payload'">Payload</button>
        <button class="archive-board__tab" :class="{ 'is-active': tab === 'error' }" @click="tab = 'error'">Incident</button>
      </div>

      <div class="archive-board__body">
        <template v-if="run">
          <section v-if="tab === 'timeline'" class="stack">
            <div class="stat-strip">
              <div class="stat-chip">
                <span class="stat-label">status</span>
                <span class="pill" :class="statusClass(run.status)">{{ run.status || 'queued' }}</span>
              </div>
              <div class="stat-chip">
                <span class="stat-label">started</span>
                <span class="stat-value">{{ compactTime(run.started_at || run.startedAt) }}</span>
              </div>
              <div class="stat-chip">
                <span class="stat-label">finished</span>
                <span class="stat-value">{{ compactTime(run.finished_at || run.finishedAt) }}</span>
              </div>
              <div class="stat-chip">
                <span class="stat-label">duration</span>
                <span class="stat-value">{{ duration(run.started_at || run.startedAt, run.finished_at || run.finishedAt, run.duration_ms) }}</span>
              </div>
            </div>

            <div class="timeline-sheet">
              <div v-if="run.nodes?.length" class="timeline-sheet__list">
                <div v-for="(node, index) in run.nodes" :key="index" class="timeline-sheet__row">
                  <div class="timeline-sheet__label">{{ node.node_id || node.id || `step-${index + 1}` }}</div>
                  <div class="timeline-sheet__track">
                    <span class="timeline-sheet__bar" :class="statusClass(node.status || run.status)" :style="barStyle(node)"></span>
                  </div>
                  <div class="timeline-sheet__time">{{ nodeDuration(node) }}</div>
                </div>
              </div>
              <div v-else class="empty-state">No timeline nodes were returned for this run.</div>
            </div>
          </section>

          <section v-else-if="tab === 'payload'" class="stack">
            <div class="payload-grid">
              <div class="payload-card">
                <span class="label">Plan</span>
                <div>{{ run.plan_name || '-' }}</div>
              </div>
              <div class="payload-card">
                <span class="label">Task</span>
                <code>{{ run.task_ref || run.task_name || '-' }}</code>
              </div>
              <div class="payload-card">
                <span class="label">CID</span>
                <code>{{ run.cid || '-' }}</code>
              </div>
              <div class="payload-card">
                <span class="label">Trace</span>
                <code>{{ run.trace_id || run.trace_label || '-' }}</code>
              </div>
            </div>

            <div v-if="run.user_data !== undefined" class="stack">
              <span class="label">User Data</span>
              <pre class="json">{{ pretty(run.user_data) }}</pre>
            </div>

            <div v-if="run.framework_data !== undefined" class="stack">
              <span class="label">Framework Data</span>
              <pre class="json">{{ pretty(run.framework_data) }}</pre>
            </div>
          </section>

          <section v-else class="stack">
            <div v-if="run.error" class="incident-note">
              <span class="incident-note__label">Incident</span>
              <pre class="json">{{ pretty(run.error) }}</pre>
            </div>
            <div v-else class="empty-state">This run did not report an incident payload.</div>
          </section>
        </template>

        <div v-else class="empty-state">No run selected.</div>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  open: Boolean,
  run: Object,
})

defineEmits(['close'])

const tab = ref('timeline')

watch(() => props.open, (value) => {
  if (value) tab.value = 'timeline'
})

function statusClass(status) {
  const value = (status || 'queued').toLowerCase()
  if (value === 'running') return 'pill-running'
  if (value === 'success') return 'pill-green'
  if (value === 'failed') return 'pill-red'
  if (value === 'cancelled') return 'pill-gray'
  return 'pill-queued'
}

function compactTime(value) {
  if (!value) return '--'
  const ms = value > 1e12 ? value : value * 1000
  return new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function duration(start, end, fallback) {
  if (fallback != null) return formatMs(fallback)
  if (!start || !end) return '--'
  const startMs = start > 1e12 ? start : start * 1000
  const endMs = end > 1e12 ? end : end * 1000
  return formatMs(Math.max(endMs - startMs, 0))
}

function formatMs(ms) {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const min = Math.floor(ms / 60000)
  const sec = Math.floor((ms % 60000) / 1000)
  return `${min}m ${sec}s`
}

function nodeDuration(node) {
  const start = node.startMs || node.started_at || 0
  const end = node.endMs || node.finished_at || Date.now()
  return formatMs(Math.max(end - start, 0))
}

function barStyle(node) {
  const progress = node.progress != null ? Math.max(8, Math.min(100, node.progress)) : node.endMs ? 100 : 60
  return { width: `${progress}%` }
}

function pretty(value) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}
</script>

<style scoped>
.archive-mask {
  position: fixed;
  inset: 0;
  z-index: 95;
  display: flex;
  justify-content: flex-end;
  background: rgba(0, 0, 0, 0.38);
  backdrop-filter: blur(2px);
}

.archive-board {
  width: 720px;
  max-width: 94vw;
  display: flex;
  flex-direction: column;
  border-left: 1px solid rgba(224, 214, 186, 0.1);
  background:
    linear-gradient(180deg, rgba(74, 82, 86, 0.96), rgba(46, 55, 58, 0.98));
  box-shadow: var(--shadow-soft), var(--shadow-inset);
}

.archive-board__head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: start;
  padding: 20px 22px 14px;
  border-bottom: 1px solid rgba(224, 214, 186, 0.08);
}

.archive-board__kicker {
  display: block;
  color: var(--paper);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.archive-board__title {
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 34px;
  letter-spacing: 0.08em;
  line-height: 0.9;
  text-transform: uppercase;
}

.archive-board__tabs {
  display: flex;
  gap: 8px;
  padding: 12px 22px 0;
}

.archive-board__tab {
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid rgba(224, 214, 186, 0.1);
  background: rgba(31, 38, 41, 0.42);
  color: var(--text-soft);
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.archive-board__tab.is-active {
  background: rgba(201, 187, 149, 0.1);
  color: var(--paper-2);
}

.archive-board__body {
  flex: 1;
  overflow: auto;
  padding: 16px 22px 24px;
}

.timeline-sheet,
.payload-card,
.incident-note {
  border: 1px solid rgba(224, 214, 186, 0.1);
  background: rgba(27, 33, 35, 0.42);
}

.timeline-sheet {
  padding: 14px;
}

.timeline-sheet__list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.timeline-sheet__row {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr) 80px;
  gap: 12px;
  align-items: center;
}

.timeline-sheet__label,
.timeline-sheet__time {
  font-family: var(--font-mono);
  font-size: 11px;
}

.timeline-sheet__track {
  height: 12px;
  border: 1px solid rgba(224, 214, 186, 0.08);
  background: rgba(18, 22, 24, 0.36);
}

.timeline-sheet__bar {
  display: block;
  height: 100%;
  min-width: 8%;
  background: rgba(201, 157, 84, 0.22);
}

.payload-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.payload-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
}

.incident-note {
  padding: 12px 14px;
}

.incident-note__label {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  padding: 0 8px;
  margin-bottom: 10px;
  border: 1px solid rgba(198, 113, 99, 0.2);
  background: rgba(198, 113, 99, 0.12);
  color: #e8c1bb;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}
</style>

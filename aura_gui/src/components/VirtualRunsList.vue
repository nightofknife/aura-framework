<!-- 虚拟滚动的运行记录列表组件 -->
<template>
  <div class="virtual-runs-list-container">
    <RecycleScroller
      :items="runs"
      :item-size="itemSize"
      key-field="cid"
      class="virtual-runs-list"
      :style="{ height: maxHeight || '70vh' }"
      v-slot="{ item }"
    >
      <div
        class="run-row"
        @click="$emit('row-click', item)"
        :class="{ 'run-row-clickable': true }"
      >
        <div class="run-status">
          <span class="pill" :class="getStatusClass(item.status)">
            {{ formatStatus(item.status) }}
          </span>
        </div>
        <div class="run-info">
          <div class="run-header">
            <span class="run-plan">{{ item.plan_name || '-' }}</span>
            <span class="run-separator">/</span>
            <span class="run-task">{{ item.task_name || '-' }}</span>
          </div>
          <div class="run-meta">
            <span class="meta-item" v-if="item.startedAt">
              <span class="meta-label">开始:</span>
              {{ formatTime(item.startedAt) }}
            </span>
            <span class="meta-item" v-if="item.finishedAt">
              <span class="meta-label">结束:</span>
              {{ formatTime(item.finishedAt) }}
            </span>
            <span class="meta-item" v-if="item.elapsed">
              <span class="meta-label">耗时:</span>
              {{ formatElapsed(item.elapsed) }}
            </span>
          </div>
        </div>
      </div>
    </RecycleScroller>

    <div v-if="runs.length === 0" class="empty-state">
      <div class="empty-icon">📭</div>
      <div class="empty-text">暂无运行记录</div>
    </div>
  </div>
</template>

<script setup>
import { RecycleScroller } from 'vue-virtual-scroller'

const props = defineProps({
  runs: {
    type: Array,
    required: true
  },
  maxHeight: {
    type: String,
    default: '70vh'
  },
  itemSize: {
    type: Number,
    default: 88
  }
})

defineEmits(['row-click'])

function getStatusClass(status) {
  const s = (status || 'queued').toLowerCase()
  if (s === 'running') return 'pill-blue'
  if (s === 'success') return 'pill-green'
  if (s === 'error' || s === 'failed') return 'pill-red'
  return 'pill-gray'
}

function formatStatus(status) {
  const s = status == null ? '' : String(status)
  return s ? s.toUpperCase() : '—'
}

function formatTime(timestamp) {
  if (!timestamp) return '-'
  const date = timestamp instanceof Date ? timestamp : new Date(timestamp)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

function formatElapsed(ms) {
  if (ms == null) return '-'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const min = Math.floor(ms / 60000)
  const sec = Math.floor((ms % 60000) / 1000)
  return `${min}m ${sec}s`
}
</script>

<style scoped>
.virtual-runs-list-container {
  position: relative;
  height: 100%;
}

.virtual-runs-list {
  overflow-y: auto;
  background: var(--bg-2, #1a1a1a);
  border: 1px solid var(--border, #333);
  border-radius: 8px;
}

.run-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px;
  border-bottom: 1px solid var(--border, #333);
  transition: background 0.2s;
}

.run-row-clickable {
  cursor: pointer;
}

.run-row-clickable:hover {
  background: var(--hover-bg, rgba(255, 255, 255, 0.05));
}

.run-row:last-child {
  border-bottom: none;
}

.run-status {
  flex-shrink: 0;
  width: 100px;
}

.pill {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  text-align: center;
  letter-spacing: 0.5px;
}

.pill-blue {
  background: var(--blue-light, rgba(59, 130, 246, 0.2));
  color: var(--blue, #3b82f6);
}

.pill-green {
  background: var(--green-light, rgba(34, 197, 94, 0.2));
  color: var(--green, #22c55e);
}

.pill-red {
  background: var(--red-light, rgba(239, 68, 68, 0.2));
  color: var(--red, #ef4444);
}

.pill-gray {
  background: var(--gray-light, rgba(156, 163, 175, 0.2));
  color: var(--gray, #9ca3af);
}

.run-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.run-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  line-height: 1.4;
}

.run-plan {
  font-weight: 500;
  color: var(--text-1, #e5e5e5);
}

.run-separator {
  color: var(--text-3, #777);
  font-weight: 300;
}

.run-task {
  font-weight: 400;
  color: var(--text-2, #b3b3b3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 12px;
  color: var(--text-3, #777);
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.meta-label {
  font-weight: 500;
  color: var(--text-3, #888);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 50vh;
  color: var(--text-3, #777);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-text {
  font-size: 14px;
}
</style>

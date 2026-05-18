<template>
  <Teleport to="body">
    <div v-if="open" class="drawer-mask" @click.self="$emit('close')">
      <aside class="drawer" role="dialog" aria-modal="true" aria-label="运行详情">
        <header class="drawer__head">
          <div>
            <strong>{{ run?.taskRef || run?.title || '运行详情' }}</strong>
            <span>{{ run?.planName || '-' }} · {{ run?.shortCid || '-' }}</span>
          </div>
          <button class="btn btn-ghost btn-sm" @click="$emit('close')">关闭</button>
        </header>

        <div class="drawer__tabs tabs">
          <button
            v-for="item in tabs"
            :key="item.key"
            class="tab"
            :class="{ 'is-active': tab === item.key }"
            @click="tab = item.key"
          >
            {{ item.label }}
          </button>
        </div>

        <div class="drawer__body">
          <section v-if="!run" class="empty-state">未选择运行记录。</section>

          <section v-else-if="tab === 'overview'" class="stack">
            <div class="meta-grid">
              <div class="meta-card">
                <span>状态</span>
                <span class="pill" :class="statusClass(run.status)">{{ statusLabel(run.status) }}</span>
              </div>
              <div class="meta-card">
                <span>开始</span>
                <code>{{ formatTime(run.startedAtMs) }}</code>
              </div>
              <div class="meta-card">
                <span>结束</span>
                <code>{{ formatTime(run.finishedAtMs) }}</code>
              </div>
              <div class="meta-card">
                <span>耗时</span>
                <code>{{ formatDuration(run.durationMs) }}</code>
              </div>
            </div>

            <div class="panel">
              <div class="panel-body stack">
                <div class="kv"><span>Plan</span><code>{{ run.planName || '-' }}</code></div>
                <div class="kv"><span>Task</span><code>{{ run.taskRef || '-' }}</code></div>
                <div class="kv"><span>CID</span><code>{{ run.cid || '-' }}</code></div>
                <div class="kv"><span>Trace</span><code>{{ run.traceLabel || run.traceId || '-' }}</code></div>
              </div>
            </div>

            <div v-if="run.errorSummary" class="notice notice-danger">{{ run.errorSummary }}</div>
          </section>

          <section v-else-if="tab === 'timeline'" class="stack">
            <div v-if="run.nodes?.length" class="timeline">
              <div v-for="(node, index) in run.nodes" :key="node.node_id || node.id || index" class="timeline-row">
                <span class="timeline-dot" :class="statusDotClass(node.status || run.status)"></span>
                <div>
                  <strong>{{ node.node_id || node.id || `步骤 ${index + 1}` }}</strong>
                  <p>{{ node.action || node.action_name || '-' }}</p>
                </div>
                <code>{{ formatDuration(node.duration_ms) }}</code>
              </div>
            </div>
            <div v-else class="empty-state">该运行没有返回步骤时间线。</div>
          </section>

          <section v-else-if="tab === 'actions'" class="stack">
            <div v-if="run.actionResults?.length" class="record-list">
              <article v-for="(item, index) in run.actionResults" :key="item.node_id || index" class="record-card">
                <div class="record-card__head">
                  <strong>{{ item.action || '-' }}</strong>
                  <span class="pill" :class="item.ok === false ? 'pill-red' : 'pill-green'">
                    {{ item.ok === false ? '失败' : '成功' }}
                  </span>
                </div>
                <div class="kv"><span>节点</span><code>{{ item.node_id || '-' }}</code></div>
                <div class="kv"><span>后端</span><code>{{ item.backend || '-' }}</code></div>
                <div v-if="item.message" class="hint">{{ item.message }}</div>
              </article>
            </div>
            <div v-else class="empty-state">没有 action result 数据。</div>
          </section>

          <section v-else-if="tab === 'evidence'" class="stack">
            <div v-if="evidenceGroups.length" class="record-list">
              <article v-for="group in evidenceGroups" :key="group.name" class="record-card">
                <div class="record-card__head">
                  <strong>{{ group.label }}</strong>
                  <span class="pill pill-gray">{{ group.items.length }}</span>
                </div>
                <p v-for="(item, index) in group.items.slice(0, 6)" :key="index" class="hint">
                  {{ item.path || item.file_path || item.uri || JSON.stringify(item) }}
                </p>
              </article>
            </div>
            <div v-else class="empty-state">没有 evidence manifest 数据。</div>
          </section>

          <section v-else class="stack">
            <div v-if="artifactError" class="notice notice-danger">{{ artifactError }}</div>
            <div v-if="artifacts.debugReport" class="stack">
              <span class="label">Debug Report</span>
              <pre class="json">{{ pretty(artifacts.debugReport) }}</pre>
            </div>
            <div v-if="artifacts.locators.length" class="stack">
              <span class="label">Locators</span>
              <pre class="json">{{ pretty(artifacts.locators) }}</pre>
            </div>
            <div class="stack">
              <span class="label">Raw Run</span>
              <pre class="json">{{ pretty(run.raw || run) }}</pre>
            </div>
          </section>
        </div>
      </aside>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { getRunDebugArtifacts } from '../api/runs.js'

const props = defineProps({
  open: Boolean,
  run: Object,
})

defineEmits(['close'])

const tab = ref('overview')
const artifactError = ref('')
const artifacts = reactive({
  debugReport: null,
  locators: [],
  evidenceManifest: null,
})

const tabs = [
  { key: 'overview', label: '概览' },
  { key: 'timeline', label: '时间线' },
  { key: 'actions', label: '动作' },
  { key: 'evidence', label: '证据' },
  { key: 'debug', label: '调试' },
]

const evidenceLabels = {
  captures: '截图',
  locators: '定位器',
  ocr: 'OCR',
  yolo: 'YOLO',
  window: '窗口',
  backend: '后端',
  other: '其他',
}

const evidenceGroups = computed(() => {
  const manifest = artifacts.evidenceManifest || {}
  const groups = Object.keys(evidenceLabels).map((name) => ({
    name,
    label: evidenceLabels[name],
    items: Array.isArray(manifest[name]) ? manifest[name] : [],
  }))

  if (props.run?.evidence?.length) {
    groups.push({ name: 'run-evidence', label: '运行证据', items: props.run.evidence })
  }

  return groups.filter((group) => group.items.length)
})

watch(() => [props.open, props.run?.cid], async ([open, cid]) => {
  tab.value = 'overview'
  artifactError.value = ''
  artifacts.debugReport = null
  artifacts.locators = []
  artifacts.evidenceManifest = null
  if (!open || !cid) return
  try {
    const loaded = await getRunDebugArtifacts(cid)
    artifacts.debugReport = loaded.debugReport
    artifacts.locators = loaded.locators
    artifacts.evidenceManifest = loaded.evidenceManifest
  } catch (error) {
    artifactError.value = error?.message || '调试数据加载失败。'
  }
})

function statusClass(status) {
  const value = String(status || '').toLowerCase()
  if (value === 'success') return 'pill-green'
  if (value === 'failed') return 'pill-red'
  if (value === 'running') return 'pill-running'
  if (value === 'cancelled') return 'pill-gray'
  return 'pill-queued'
}

function statusDotClass(status) {
  const value = String(status || '').toLowerCase()
  if (value === 'success') return 'dot-success'
  if (value === 'failed') return 'dot-failed'
  if (value === 'running') return 'dot-running'
  if (value === 'cancelled') return 'dot-muted'
  return 'dot-queued'
}

function statusLabel(status) {
  const labels = {
    queued: '排队',
    running: '运行中',
    success: '成功',
    failed: '失败',
    cancelled: '已取消',
    unknown: '未知',
  }
  return labels[status] || status || '未知'
}

function formatTime(ms) {
  if (!ms) return '--'
  return new Date(ms).toLocaleString('zh-CN')
}

function formatDuration(ms) {
  if (ms === null || ms === undefined || Number.isNaN(Number(ms))) return '--'
  const value = Number(ms)
  if (value < 1000) return `${Math.round(value)}ms`
  if (value < 60000) return `${(value / 1000).toFixed(1)}s`
  return `${Math.floor(value / 60000)}m ${Math.floor((value % 60000) / 1000)}s`
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
.drawer-mask {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  justify-content: flex-end;
  background: rgba(0, 0, 0, 0.36);
}

.drawer {
  display: flex;
  width: 720px;
  max-width: 94vw;
  height: 100vh;
  flex-direction: column;
  border-left: 1px solid var(--border-subtle);
  background: var(--bg-surface);
  box-shadow: var(--shadow-elevated);
}

.drawer__head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  padding: 16px;
  border-bottom: 1px solid var(--border-subtle);
}

.drawer__head div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.drawer__head strong {
  color: var(--text-primary);
  font-size: 16px;
}

.drawer__head span {
  color: var(--text-muted);
  font-size: 12px;
}

.drawer__tabs {
  margin: 12px 16px 0;
  align-self: flex-start;
}

.drawer__body {
  flex: 1;
  overflow: auto;
  padding: 16px;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.meta-card,
.record-card {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-surface-2);
}

.meta-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
}

.meta-card span:first-child {
  color: var(--text-muted);
  font-size: 12px;
}

.kv {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  min-width: 0;
}

.kv span {
  color: var(--text-secondary);
}

.notice {
  padding: 10px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-field);
  color: var(--text-secondary);
}

.notice-danger {
  border-color: rgba(239, 91, 91, 0.34);
  background: var(--danger-soft);
  color: #ffb4b4;
}

.timeline {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.timeline-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-surface-2);
}

.timeline-row p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.timeline-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--warning);
}

.dot-success {
  background: var(--success);
}

.dot-failed {
  background: var(--danger);
}

.dot-running {
  background: var(--info);
}

.dot-muted {
  background: var(--text-muted);
}

.record-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.record-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
}

.record-card__head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

@media (max-width: 760px) {
  .meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>

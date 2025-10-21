<!-- src/components/RunDetailDrawer.vue -->
<template>
  <div class="drawer-mask" v-if="open" @click.self="$emit('close')">
    <div class="drawer">
      <div class="drawer-header">
        <strong>Run • {{ run?.task_name || '—' }}</strong>
        <button class="btn btn-ghost btn-sm" @click="$emit('close')">Close</button>
      </div>
      <div class="tabs" style="padding:8px 12px 0;">
        <button class="tab" :class="{active:tab==='timeline'}" @click="tab='timeline'">Timeline</button>
        <button class="tab" :class="{active:tab==='logs'}" @click="tab='logs'">Logs</button>
        <button class="tab" :class="{active:tab==='params'}" @click="tab='params'">Params</button>
        <button class="tab" :class="{active:tab==='errors'}" @click="tab='errors'">Errors</button>
      </div>
      <div class="drawer-body">
        <div v-if="!run" style="color:var(--text-3);">No selection.</div>

        <!-- Timeline -->
        <div v-else-if="tab==='timeline'" class="tl">
          <div class="tl-legend">
            <span>Status: <b :class="'pill '+statusClass(run.status)">{{ (run.status || '—').toUpperCase() }}</b></span>
            <span>Started: {{ fmt(run.started_at || run.startedAt) }}</span>
            <span>Finished: {{ fmt(run.finished_at || run.finishedAt) }}</span>
            <span>Duration: {{ duration(run.started_at || run.startedAt, run.finished_at || run.finishedAt) }}</span>
          </div>
          <div class="tl-rows">
            <div class="tl-row" v-for="(n,idx) in (run.nodes||[])" :key="idx">
              <div class="tl-label">{{ n.node_id || n.id || ('step ' + (idx + 1)) }}</div>
              <div class="tl-bars">
                <div class="tl-bar" :class="n.status || 'running'" :style="barStyle(n)"></div>
              </div>
              <div class="tl-time">{{ nodeDur(n) }}</div>
            </div>
            <div v-if="!run.nodes?.length" style="color:var(--text-3);">No timeline data.</div>
          </div>
        </div>

        <!-- Logs -->
        <div v-else-if="tab==='logs'">
          <LogStream :logs="logs"/>
        </div>

        <!-- Params -->
        <div v-else-if="tab==='params'" style="display:grid; gap:12px;">
          <div><b>Plan:</b> {{ run.plan_name }}</div>
          <div><b>Task:</b> {{ run.task_name }}</div>
          <div><b>Run ID (CID):</b> <code>{{ run.cid || run.id }}</code></div>
          <div>
            <div style="color:var(--text-3); font-size:12px;">Inputs</div>
            <pre class="json">{{ pretty(run.inputs || {}) }}</pre>
          </div>
          <div v-if="run.outputs">
            <div style="color:var(--text-3); font-size:12px;">Outputs</div>
            <pre class="json">{{ pretty(run.outputs) }}</pre>
          </div>
        </div>

        <!-- Errors -->
        <div v-else-if="tab==='errors'">
          <div v-if="errorLines.length===0" style="color:var(--text-3);">No errors.</div>
          <div v-else class="err">
            <div class="log" v-for="(l,i) in errorLines" :key="i">
              <div class="ts">{{ fmt(l.ts) }}</div>
              <div class="text">{{ l.message }}</div>
            </div>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { useAuraSockets } from '../composables/useAuraSockets.js';
import LogStream from './LogStream.vue';

const props = defineProps({
  open: Boolean,
  run: Object,
});
defineEmits(['close']);

const tab = ref('timeline');
const localLogs = ref([]);

watch(() => props.open, v => {
  if (v) {
    tab.value = 'timeline';
    localLogs.value = []; // 清空旧日志
  }
});

// ✅ 获取日志 WebSocket
const { logs: logSocket } = useAuraSockets();

// ✅ 监听日志消息，只过滤当前 run 的日志
watch(() => logSocket.lastMessage.value, (msg) => {
  if (!props.open || !msg || msg.type !== 'log') return;

  const logEntry = msg.payload;
  if (!logEntry) return;

  // 从日志条目中获取 run_id 或 cid
  const logRunId = logEntry.extra?.run_id || logEntry.extra?.cid;
  if (!logRunId) return;

  // 检查这条日志是否属于当前正在查看的 run
  const currentRunId = props.run?.cid || props.run?.id;
  if (logRunId !== currentRunId) return;

  // 追加到本地日志列表
  localLogs.value.push({
    ts: logEntry.created ? logEntry.created * 1000 : Date.now(),
    level: (logEntry.level || 'INFO').toLowerCase(),
    message: logEntry.message,
  });
});

// ✅ 合并后端历史日志和实时日志
const logs = computed(() => {
  const historical = Array.isArray(props.run?.logs) ? props.run.logs : [];
  return [...historical, ...localLogs.value];
});

// --- 格式化函数 ---
function toMs(v) {
  return (v && v > 1e12) ? v : (v ? Math.floor(v * 1000) : null);
}

function pad(n) {
  return String(n).padStart(2, '0');
}

function fmt(ts) {
  if (!ts) return '—';
  const ms = ts > 1e12 ? ts : ts * 1000;
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function duration(a, b) {
  if (!a || !b) return '—';
  const startMs = a > 1e12 ? a : a * 1000;
  const endMs = b > 1e12 ? b : b * 1000;
  const ms = endMs - startMs;
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h ? `${h}h ${m}m ${sec}s` : (m ? `${m}m ${sec}s` : `${sec}s`);
}

function statusClass(s) {
  const v = (s || 'queued').toLowerCase();
  if (v === 'running') return 'pill-blue';
  if (v === 'success') return 'pill-green';
  if (v === 'error' || v === 'failed') return 'pill-red';
  return 'pill-gray';
}

function pretty(o) {
  try {
    return JSON.stringify(o, null, 2);
  } catch {
    return String(o);
  }
}

function nodeDur(n) {
  const a = n.startMs || 0;
  const b = n.endMs || Date.now();
  const ms = Math.max(0, b - a);
  const s = Math.floor(ms / 1000);
  return s >= 1 ? `${s}s` : `${ms}ms`;
}

function barStyle(n) {
  const p = n.progress != null ? Math.max(0, Math.min(100, n.progress)) : (n.endMs && n.startMs ? 100 : 60);
  return { left: '0%', width: `${p}%` };
}

const errorLines = computed(() => logs.value.filter(l => (l.level || 'info').toLowerCase() === 'error'));
</script>

<style scoped>
.drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 2000;
  display: flex;
  justify-content: flex-end;
}

.drawer {
  width: 600px;
  max-width: 90vw;
  background: var(--bg-panel);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.drawer-header {
  padding: 16px;
  border-bottom: 1px solid var(--border-frosted);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--border-frosted);
}

.tab {
  padding: 8px 16px;
  background: transparent;
  border: none;
  cursor: pointer;
  color: var(--text-secondary);
  transition: all 0.2s;
}

.tab.active {
  color: var(--primary-accent);
  border-bottom: 2px solid var(--primary-accent);
}

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.json {
  background: rgba(0, 0, 0, 0.05);
  border-radius: 8px;
  padding: 10px;
  overflow: auto;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12px;
}

.tl-legend {
  display: flex;
  gap: 16px;
  padding: 12px;
  background: rgba(0, 0, 0, 0.03);
  border-radius: 8px;
  margin-bottom: 12px;
}

.tl-rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tl-row {
  display: grid;
  grid-template-columns: 150px 1fr 80px;
  gap: 12px;
  align-items: center;
}

.tl-label {
  font-weight: 600;
  color: var(--text-primary);
}

.tl-bars {
  position: relative;
  height: 24px;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 4px;
  overflow: hidden;
}

.tl-bar {
  position: absolute;
  height: 100%;
  background: var(--primary-accent);
  transition: width 0.3s ease;
}

.tl-bar.success {
  background: var(--green-400);
}

.tl-bar.error {
  background: var(--red-400);
}

.tl-time {
  text-align: right;
  color: var(--text-secondary);
  font-size: 12px;
}

.err .log {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--border-frosted);
}

.err .log:last-child {
  border-bottom: none;
}

.ts {
  color: var(--text-tertiary);
  font-family: ui-monospace, Menlo, monospace;
  font-size: 11px;
}
</style>

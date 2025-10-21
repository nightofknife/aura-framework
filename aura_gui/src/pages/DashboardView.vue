<!-- === src/pages/DashboardView.vue === -->
<template>
  <div class="panel glass glass-thick glass-refract glass-shimmer">
    <div class="panel-header">
      <strong>Dashboard</strong>
      <div style="color:var(--text-3); font-size:13px;">Current engine &amp; queue health</div>
    </div>

    <div class="panel-body">
      <!-- KPI -->
      <div class="kpi">
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">Active Runs</div>
          <div class="num">{{ activeCount }}</div>
        </div>
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">Today Throughput</div>
          <div class="num">{{ todayCount }}</div>
        </div>
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">Success Rate (24h)</div>
          <div class="num">{{ successRate24h }}</div>
        </div>
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">P95 Duration (24h)</div>
          <div class="num">{{ p95Duration }}</div>
        </div>
      </div>

      <div class="kpi" style="margin-top:12px;">
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">Queue Ready</div>
          <div class="num">{{ overview?.ready_length ?? '—' }}</div>
        </div>
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">Queue Delayed</div>
          <div class="num">{{ overview?.delayed_length ?? '—' }}</div>
        </div>
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">Avg Wait (est)</div>
          <div class="num">{{ avgWait }}</div>
        </div>
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">Engine</div>
          <div class="num">
            <span class="dot" :class="isEngineHealthy ? 'ok':'bad'"></span>
          </div>
        </div>
      </div>

      <!-- Recent Activity -->
      <div class="panel glass glass-thick glass-refract glass-shimmer" style="margin-top:12px;">
        <div class="panel-header">
          <strong>Recent Activity</strong>
          <div style="color:var(--text-3); font-size:12px;">Last {{ recentShown.length }} runs</div>
        </div>
        <div class="panel-body" style="padding:0;">
          <div class="table-wrap" style="max-height:46vh;">
            <table>
              <thead>
              <tr>
                <th>Status</th>
                <th>Plan</th>
                <th>Task</th>
                <th>Started</th>
                <th>Finished</th>
                <th>Duration</th>
              </tr>
              </thead>
              <tbody>
              <tr v-for="r in recentShown" :key="r.cid || r.id">
                <td><span class="pill" :class="statusClass(r.status)">{{ safeUpper(r.status) }}</span></td>
                <td>{{ r.plan_name || r.plan || '—' }}</td>
                <td>{{ r.task_name || r.task || '—' }}</td>
                <td>{{ fmt(r.started_at || r.startedAt) }}</td>
                <td>{{ fmt(r.finished_at || r.finishedAt) }}</td>
                <td>{{ duration(r.started_at || r.startedAt, r.finished_at || r.finishedAt) }}</td>
              </tr>
              <tr v-if="!recentShown.length">
                <td :colspan="6" style="color:var(--text-3);">No recent runs.</td>
              </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Trends -->
      <div class="panel glass glass-thick glass-refract glass-shimmer" style="margin-top:12px;">
        <div class="panel-header">
          <strong>Trends (24h)</strong>
          <div style="color:var(--text-3); font-size:12px;">Placeholder — hook your chart lib later</div>
        </div>
        <div class="panel-body">
          <div
              style="height:160px; border:1px dashed var(--border-frosted); border-radius:12px; display:flex; align-items:center; justify-content:center; color:var(--text-3);">
            Add charts here when ready
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue';
import axios from 'axios';
import { useAuraSockets } from '../composables/useAuraSockets.js';
import { useRuns } from '../composables/useRuns.js';
import { useQueueStore } from '../composables/useQueueStore.js';

// --- 配置 ---
const API_BASE = 'http://127.0.0.1:18098/api';
const api = axios.create({ baseURL: API_BASE, timeout: 5000 });

// --- 获取响应式数据源 ---
const { logs } = useAuraSockets(); // ✅ 改用 logs 通道
const { activeRuns, recentRuns, setRuns } = useRuns();
const { overview, fetchOverview } = useQueueStore();

// --- 本地状态 ---
const isEngineHealthy = ref(false); // 引擎健康状态
let pollTimer = null;
const POLL_INTERVAL = 3000; // 3秒轮询一次

// --- 数据获取逻辑 ---
async function fetchActiveRuns() {
  try {
    const { data } = await api.get('/runs/active');
    setRuns(data || []);
    isEngineHealthy.value = true; // 请求成功，说明引擎在线
  } catch (err) {
    console.error('[Dashboard] Failed to fetch active runs:', err);
    isEngineHealthy.value = false; // 请求失败，引擎可能离线
  }
}

async function fetchAllData() {
  await Promise.all([
    fetchActiveRuns(),
    fetchOverview()
  ]);
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(fetchAllData, POLL_INTERVAL);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

// --- 计算属性 ---
const activeCount = computed(() => activeRuns.value.length);

const todayCount = computed(() => {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  return recentRuns.value.filter(r => {
    const ts = r.finished_at || r.finishedAt;
    return ts && ts >= start.getTime();
  }).length;
});

const successRate24h = computed(() => {
  const since = Date.now() - 24 * 3600 * 1000;
  const win = recentRuns.value.filter(r => {
    const ts = r.finished_at || r.finishedAt;
    return ts && ts >= since;
  });
  if (!win.length) return '—';
  const ok = win.filter(r => String(r.status).toLowerCase() === 'success').length;
  return Math.round(ok * 100 / win.length) + '%';
});

const p95Duration = computed(() => {
  const since = Date.now() - 24 * 3600 * 1000;
  const durs = recentRuns.value
      .filter(r => {
        const start = r.started_at || r.startedAt;
        const end = r.finished_at || r.finishedAt;
        return start && end && end >= since;
      })
      .map(r => {
        const start = r.started_at || r.startedAt;
        const end = r.finished_at || r.finishedAt;
        return end - start;
      })
      .sort((a, b) => a - b);
  if (!durs.length) return '—';
  const idx = Math.min(durs.length - 1, Math.floor(durs.length * 0.95));
  return humanMs(durs[idx]);
});

const avgWait = computed(() => {
  if (!overview.value || overview.value.avg_wait_sec == null) return '—';
  return humanMs(overview.value.avg_wait_sec * 1000);
});

const recentShown = computed(() => recentRuns.value.slice(0, 30));

// --- 生命周期 ---
onMounted(() => {
  fetchAllData(); // 首次加载
  startPolling(); // 开始轮询
});

onUnmounted(() => {
  stopPolling();
});

// ✅ 热更新清理（可选）
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    stopPolling();
  });
}

// --- 格式化函数 ---
function statusClass(s) {
  s = (s || 'queued').toLowerCase();
  if (s === 'running') return 'pill-blue';
  if (s === 'success') return 'pill-green';
  if (s === 'error' || s === 'failed') return 'pill-red';
  return 'pill-gray';
}

function safeUpper(s) {
  return s ? String(s).toUpperCase() : 'QUEUED';
}

function pad(n){ return String(n).padStart(2,'0'); }

function fmt(ts){
  if(!ts) return '—';
  const ms = ts > 1e12 ? ts : ts * 1000; // 兼容秒和毫秒
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function duration(a, b){
  if(!a || !b) return '—';
  const startMs = a > 1e12 ? a : a * 1000;
  const endMs = b > 1e12 ? b : b * 1000;
  return humanMs(endMs - startMs);
}

function humanMs(ms){
  if (ms == null || ms < 0) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m ${sec}s`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}
</script>

<style scoped>
.kpi {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}
.card {
  padding: 14px;
  border-radius: var(--radius-lg);
}
.card .title {
  color: var(--text-secondary);
  font-size: 12px;
}
.card .num {
  font-size: 24px;
  font-weight: 700;
  margin-top: 4px;
}
.dot {
  display: inline-block;
  width: 1em;
  height: 1em;
  border-radius: 50%;
  transition: background-color 0.3s ease;
}
.dot.ok {
  background-color: var(--green-400);
  box-shadow: 0 0 8px var(--green-400);
}
.dot.bad {
  background-color: var(--red-400);
  box-shadow: 0 0 8px var(--red-400);
}
.table-wrap {
  overflow-y: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th, td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border-frosted);
  font-size: 13px;
}
thead th {
  position: sticky;
  top: 0;
  background: var(--bg-panel-header);
  backdrop-filter: blur(4px);
  font-size: 12px;
  color: var(--text-secondary);
}
.pill {
  padding: 2px 8px;
  border-radius: 99px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}
.pill-blue { background-color: rgba(59, 130, 246, 0.2); color: #60a5fa; }
.pill-green { background-color: rgba(34, 197, 94, 0.2); color: #4ade80; }
.pill-red { background-color: rgba(239, 68, 68, 0.2); color: #f87171; }
.pill-gray { background-color: rgba(156, 163, 175, 0.2); color: #9ca3af; }
</style>

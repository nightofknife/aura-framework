<!-- 仪表盘（中文） -->
<template>
  <div class="panel glass glass-thick glass-refract glass-shimmer">
    <div class="panel-header">
      <strong>仪表盘</strong>
      <div style="color:var(--text-3); font-size:13px;">引擎与队列健康概览</div>
    </div>

    <div class="panel-body">
      <!-- 顶部工具栏 -->
      <div class="toolbar glass glass-thin">
        <div class="hot-reload">
          <span class="pill" :class="hotReloadStatus.enabled ? 'pill-green' : 'pill-gray'">
            热重载 {{ hotReloadStatus.enabled ? '开启' : '关闭' }}
          </span>
          <button class="btn btn-sm" :disabled="hotReloadBusy" @click="toggleHotReload()">
            {{ hotReloadStatus.enabled ? '关闭' : '开启' }}
          </button>
          <span class="muted" v-if="hotReloadMessage">{{ hotReloadMessage }}</span>
        </div>
        <div class="ws-state">
          <span class="hint">健康</span>
          <span class="pill" :class="health?.ready ? 'pill-green' : 'pill-red'">{{ healthStatusText }}</span>
          <span class="hint">事件 WS</span><span class="dot" :class="eventsConnected ? 'ok':'bad'"></span>
          <span class="hint">日志 WS</span><span class="dot" :class="logsConnected ? 'ok':'bad'"></span>
        </div>
      </div>

      <!-- 核心指标 -->
      <div class="kpi">
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">运行中任务</div><div class="num">{{ runningTasks }}</div>
        </div>
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">待执行队列</div><div class="num">{{ queueReady }}</div>
        </div>
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">延迟队列</div><div class="num">{{ queueDelayed }}</div>
        </div>
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">即时成功率</div><div class="num">{{ successRateLive }}</div>
        </div>
      </div>

      <div class="kpi" style="margin-top:12px;">
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">已完成 / 成功</div><div class="num">{{ tasksFinished }} / {{ tasksSuccess }}</div>
        </div>
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">节点平均耗时</div><div class="num">{{ nodeAvgDuration }}</div>
        </div>
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">平均等待(估算)</div><div class="num">{{ avgWait }}</div>
        </div>
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">引擎</div>
          <div class="num"><span class="dot" :class="isEngineHealthy ? 'ok':'bad'"></span></div>
          <div style="color:var(--text-3); font-size:11px; margin-top:2px;">{{ metricsUpdatedAt }}</div>
        </div>
      </div>

      <!-- 最近运行 -->
      <div class="panel glass glass-thick glass-refract glass-shimmer" style="margin-top:12px;">
        <div class="panel-header">
          <strong>最近运行</strong>
          <div style="color:var(--text-3); font-size:12px;">最近 {{ recentShown.length }} 条</div>
        </div>
        <div class="panel-body" style="padding:0;">
          <div class="table-wrap" style="max-height:46vh;">
            <table>
              <thead><tr><th>状态</th><th>计划</th><th>任务</th><th>开始</th><th>结束</th><th>耗时</th></tr></thead>
              <tbody>
              <tr v-for="r in recentShown" :key="r.cid || r.id">
                <td><span class="pill" :class="statusClass(r.status)">{{ safeUpper(r.status) }}</span></td>
                <td>{{ r.plan_name || r.plan || "—" }}</td>
                <td>{{ r.task_name || r.task || "—" }}</td>
                <td>{{ fmt(r.started_at || r.startedAt) }}</td>
                <td>{{ fmt(r.finished_at || r.finishedAt) }}</td>
                <td>{{ duration(r.started_at || r.startedAt, r.finished_at || r.finishedAt) }}</td>
              </tr>
              <tr v-if="!recentShown.length">
                <td :colspan="6" style="color:var(--text-3);">暂无运行记录</td>
              </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="grid-two" style="margin-top:12px;">
        <!-- 历史列表 -->
        <div class="panel glass glass-thick glass-refract glass-shimmer">
          <div class="panel-header">
            <strong>历史记录</strong>
            <div style="color:var(--text-3); font-size:12px;">已持久化 {{ historyRuns.length }} 条</div>
          </div>
          <div class="panel-body" style="padding:12px;">
            <div class="filters">
              <input v-model="historyFilters.plan" type="text" placeholder="计划名" />
              <input v-model="historyFilters.task" type="text" placeholder="任务名" />
              <select v-model="historyFilters.status">
                <option value="">全部状态</option>
                <option value="success">成功</option>
                <option value="error">错误</option>
                <option value="failed">失败</option>
                <option value="timeout">超时</option>
                <option value="cancelled">取消</option>
              </select>
              <button class="btn btn-sm" :disabled="historyLoading" @click="fetchHistory()">筛选</button>
              <button class="btn btn-sm ghost" :disabled="historyLoading" @click="resetHistoryFilters()">重置</button>
            </div>
            <div class="table-wrap" style="max-height:32vh;">
              <table>
                <thead><tr><th>状态</th><th>计划</th><th>任务</th><th>开始</th><th>结束</th><th>耗时</th></tr></thead>
                <tbody>
                <tr v-for="r in historyRuns" :key="r.cid || r.id">
                  <td><span class="pill" :class="statusClass(r.status)">{{ safeUpper(r.status) }}</span></td>
                  <td>{{ r.plan_name || r.plan || '—' }}</td>
                  <td>{{ r.task_name || r.task || '—' }}</td>
                  <td>{{ fmt(r.started_at || r.startedAt) }}</td>
                  <td>{{ fmt(r.finished_at || r.finishedAt) }}</td>
                  <td>{{ duration(r.started_at || r.startedAt, r.finished_at || r.finishedAt) }}</td>
                </tr>
                <tr v-if="!historyRuns.length && !historyLoading">
                  <td :colspan="6" style="color:var(--text-3);">暂无历史记录</td>
                </tr>
                <tr v-if="historyLoading">
                  <td :colspan="6" style="color:var(--text-3);">加载中...</td>
                </tr>
                </tbody>
              </table>
            </div>
            <div v-if="historyError" class="error-text">{{ historyError }}</div>
          </div>
        </div>

        <!-- 实时日志 + 最近日志 -->
        <div class="panel glass glass-thick glass-refract glass-shimmer">
          <div class="panel-header">
            <strong>实时日志</strong>
            <div style="color:var(--text-3); font-size:12px;">实时流 & 拉取最近日志</div>
          </div>
          <div class="panel-body">
            <div class="log-head">
              <span class="pill" :class="logsConnected ? 'pill-green' : 'pill-gray'">{{ logsConnected ? '实时' : '未连接' }}</span>
              <span class="muted" v-if="logsError">{{ logsError }}</span>
              <div style="display:flex; gap:6px; margin-left:auto;">
                <input v-model="logKeyword" class="input" placeholder="关键字过滤" style="width:140px;"/>
                <select v-model="logLevel" class="input" style="width:110px;">
                  <option value="warning">warning</option><option value="info">info</option><option value="error">error</option><option value="debug">debug</option>
                </select>
                <button class="btn btn-sm" @click="fetchRecentLogs()">查看最近日志</button>
              </div>
            </div>
            <div class="log-box">
              <div v-if="recentLogLines.length" class="muted" style="margin-bottom:6px;">最新日志 ({{ recentLogLines.length }} 行)</div>
              <div v-for="(line, idx) in recentLogLines" :key="'hist-'+idx" class="log-line">
                <span class="msg">{{ line }}</span>
              </div>
              <div v-for="(log, idx) in logEntries" :key="'live-'+idx" class="log-line">
                <span class="ts">{{ fmtTime(log.ts) }}</span>
                <span class="lvl" :class="log.level || 'INFO'">{{ (log.level || 'INFO').toUpperCase() }}</span>
                <span class="msg">{{ log.text }}</span>
              </div>
              <div v-if="!logEntries.length && !recentLogLines.length" class="muted">等待日志事件...</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 趋势占位 -->
      <div class="panel glass glass-thick glass-refract glass-shimmer" style="margin-top:12px;">
        <div class="panel-header">
          <strong>趋势 (24h)</strong>
          <div style="color:var(--text-3); font-size:12px;">占位：后续可接入图表</div>
        </div>
        <div class="panel-body">
          <div style="height:160px; border:1px dashed var(--border-frosted); border-radius:12px; display:flex; align-items:center; justify-content:center; color:var(--text-3);">
            可在此接入图表
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue';
import axios from 'axios';
import { getGuiConfig } from '../config.js';
import { useAuraSockets } from '../composables/useAuraSockets.js';
import { useRuns } from '../composables/useRuns.js';
import { useQueueStore } from '../composables/useQueueStore.js';

const cfg = getGuiConfig();
const API_BASE = cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1';
const api = axios.create({ baseURL: API_BASE, timeout: cfg?.api?.timeout_ms || 5000 });
const LOG_DISPLAY_LEVEL = (cfg?.logs?.display_level || 'info').toLowerCase();

const { logs, events } = useAuraSockets();
const { activeRuns, recentRuns, setRuns } = useRuns();
const { overview, fetchOverview } = useQueueStore();
const metrics = ref(null);
const health = ref(null);

const logsEnabled = cfg?.ws?.logs_enabled ?? false;
const historyRuns = ref([]);
const historyFilters = reactive({ plan: '', task: '', status: '' });
const historyLoading = ref(false);
const historyError = ref('');
const HISTORY_LIMIT = 80;

const logEntries = ref([]);
const recentLogLines = ref([]);
const logKeyword = ref('');
const logLevel = ref('warning');
const MAX_LOGS = 200;

const hotReloadStatus = ref({ enabled: false });
const hotReloadBusy = ref(false);
const hotReloadMessage = ref('');

const isEngineHealthy = ref(false);
let pollTimer = null;
let metricsTimer = null;
const POLL_INTERVAL = 3000;
const METRICS_POLL_INTERVAL = 5000;

async function fetchActiveRuns() {
  try {
    const { data } = await api.get('/runs/active');
    setRuns(data || []);
    isEngineHealthy.value = true;
  } catch (err) {
    console.error('[Dashboard] Failed to fetch active runs:', err);
    isEngineHealthy.value = false;
  }
}

async function fetchMetrics() {
  try {
    const { data } = await api.get('/system/metrics');
    metrics.value = data || {};
    isEngineHealthy.value = true;
  } catch (err) {
    console.error('[Dashboard] Failed to fetch metrics:', err);
  }
}

async function fetchHealth() {
  try {
    const { data } = await api.get('/system/health');
    health.value = data || {};
  } catch (err) {
    console.error('[Dashboard] Failed to fetch health:', err);
  }
}

async function fetchAllData() {
  await Promise.all([fetchActiveRuns(), fetchOverview(), fetchMetrics(), fetchHealth()]);
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(fetchAllData, POLL_INTERVAL);
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}
function startMetricsPoll() {
  if (metricsTimer) return;
  metricsTimer = setInterval(fetchMetrics, METRICS_POLL_INTERVAL);
}
function stopMetricsPoll() {
  if (metricsTimer) { clearInterval(metricsTimer); metricsTimer = null; }
}

async function fetchHistory() {
  historyLoading.value = true; historyError.value = '';
  const params = { limit: HISTORY_LIMIT };
  if (historyFilters.plan?.trim()) params.plan_name = historyFilters.plan.trim();
  if (historyFilters.task?.trim()) params.task_name = historyFilters.task.trim();
  if (historyFilters.status) params.status = historyFilters.status;
  try {
    const { data } = await api.get('/runs/history', { params });
    historyRuns.value = data?.runs || [];
  } catch (err) {
    historyError.value = err?.response?.data?.detail || err?.message || '加载失败';
  } finally {
    historyLoading.value = false;
  }
}
function resetHistoryFilters() {
  historyFilters.plan = ''; historyFilters.task = ''; historyFilters.status = '';
  fetchHistory();
}
function pushHistoryFromEvent(payload) {
  if (!payload) return;
  const start = payload.start_time || payload.started_at || payload.startedAt;
  const end = payload.end_time || payload.finished_at || payload.finishedAt;
  const entry = {
    cid: payload.cid || payload.id,
    plan_name: payload.plan_name || payload.plan,
    task_name: payload.task_name || payload.task,
    started_at: start ? (start > 1e12 ? start : start * 1000) : undefined,
    finished_at: end ? (end > 1e12 ? end : end * 1000) : undefined,
    status: (payload.final_status || payload.status) || 'unknown',
  };
  if (!entry.cid && !entry.plan_name && !entry.task_name) return;
  historyRuns.value.unshift(entry);
  if (historyRuns.value.length > HISTORY_LIMIT) historyRuns.value.pop();
}

const activeCount = computed(() => activeRuns.value.length);
const runningTasks = computed(() => metrics.value?.running_tasks ?? metrics.value?.tasks_running ?? activeCount.value);
const logsConnected = computed(() => logs?.isConnected?.value);
const eventsConnected = computed(() => events?.isConnected?.value);
const logsError = computed(() => logs?.error?.value || '');
const healthStatusText = computed(() => {
  if (!health.value) return '未知';
  return health.value.ready ? '正常' : '异常';
});

const tasksFinished = computed(() => metrics.value?.tasks_finished ?? 0);
const tasksSuccess = computed(() => metrics.value?.tasks_success ?? 0);
const successRateLive = computed(() => {
  const total = tasksFinished.value;
  if (!total) return '—';
  return Math.round((tasksSuccess.value * 100) / total) + '%';
});
const queueReady = computed(() => metrics.value?.queue_ready ?? overview.value?.ready_length ?? '—');
const queueDelayed = computed(() => metrics.value?.queue_delayed ?? overview.value?.delayed_length ?? '—');
const nodeAvgDuration = computed(() => metrics.value?.nodes_duration_ms_avg != null ? humanMs(metrics.value.nodes_duration_ms_avg) : '—');
const avgWait = computed(() => overview.value?.avg_wait_sec != null ? humanMs(overview.value.avg_wait_sec * 1000) : '—');
const recentShown = computed(() => recentRuns.value.slice(0, 30));
const metricsUpdatedAt = computed(() => {
  const ts = metrics.value?.updated_at;
  if (!ts) return '—';
  const ms = ts > 1e12 ? ts : ts * 1000;
  const d = new Date(ms);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
});

onMounted(() => {
  fetchAllData();
  fetchHistory();
  fetchHotReloadStatus();
  startPolling();
  startMetricsPoll();

  watch(() => events?.lastMessage?.value, (msg) => {
    if (!msg) return;
    const type = msg.type || msg.name;
    if (type === 'metrics.update') {
      metrics.value = msg.payload || msg.data || msg;
      isEngineHealthy.value = true;
    }
    if (type === 'task.finished') pushHistoryFromEvent(msg.payload);
    if (!logsEnabled) {
      let summary = '';
      try { summary = msg.payload ? `[${type}] ${JSON.stringify(msg.payload)}` : JSON.stringify(msg); }
      catch { summary = `[${type}] (payload 无法序列化)`; }
      pushLog(summary);
    }
  }, { immediate: true });

  watch(() => logs?.lastMessage?.value, (msg) => {
    if (!msg) return;
    pushLog(msg.payload ?? msg);
  }, { immediate: true });
});

onUnmounted(() => { stopPolling(); stopMetricsPoll(); });
if (import.meta.hot) { import.meta.hot.dispose(() => { stopPolling(); stopMetricsPoll(); }); }

function statusClass(s) {
  s = (s || 'queued').toLowerCase();
  if (s === 'running') return 'pill-blue';
  if (s === 'success') return 'pill-green';
  if (s === 'error' || s === 'failed') return 'pill-red';
  return 'pill-gray';
}
function safeUpper(s) { return s ? String(s).toUpperCase() : 'QUEUED'; }
function pad(n){ return String(n).padStart(2,'0'); }
function levelValue(lvl){ const map = { trace:5, debug:10, info:20, warning:30, warn:30, error:40, critical:50, fatal:50 }; return map[String(lvl||'').toLowerCase()] ?? 20; }
function fmtTime(ts){ if(!ts) return "--:--:--"; const d = new Date(ts); return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; }
function fmt(ts){ if(!ts) return '—'; const ms = ts > 1e12 ? ts : ts * 1000; const d = new Date(ms); return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`; }
function duration(a,b){ if(!a||!b) return '—'; const startMs=a>1e12?a:a*1000; const endMs=b>1e12?b:b*1000; return humanMs(endMs-startMs); }
function humanMs(ms){ if(ms==null||ms<0) return '—'; if(ms<1000) return `${Math.round(ms)}ms`; const s=Math.floor(ms/1000); const h=Math.floor(s/3600); const m=Math.floor((s%3600)/60); const sec=s%60; if(h>0) return `${h}h ${m}m ${sec}s`; if(m>0) return `${m}m ${sec}s`; return `${sec}s`; }

async function fetchRecentLogs(){
  try {
    const params = { limit: 500, level: logLevel.value };
    if (logKeyword.value) params.keyword = logKeyword.value;
    const { data } = await api.get('/system/logs', { params });
    recentLogLines.value = data?.lines || [];
  } catch (err) {
    recentLogLines.value = [err?.response?.data?.detail || err?.message || '拉取日志失败'];
  }
}

function pushLog(payload) {
  if (!payload) return;
  const ts = Date.now();
  let text = '';
  let level = '';
  if (typeof payload === 'string') text = payload;
  else if (typeof payload === 'object') {
    level = (payload.levelname || payload.level || payload.levelno || '').toString();
    text = payload.message || payload.msg || payload.text || JSON.stringify(payload);
  } else text = String(payload);
  level = (level || 'INFO').toString().toLowerCase();
  if (levelValue(level) < levelValue(LOG_DISPLAY_LEVEL)) return;
  logEntries.value.unshift({ ts, text, level });
  if (logEntries.value.length > MAX_LOGS) logEntries.value.pop();
}

async function fetchHotReloadStatus() {
  try {
    const { data } = await api.get('/system/hot_reload/status');
    hotReloadStatus.value = data || { enabled: false };
  } catch (err) {
    hotReloadMessage.value = err?.response?.data?.detail || err?.message || '获取热重载状态失败';
  }
}
async function toggleHotReload() {
  if (hotReloadBusy.value) return;
  hotReloadBusy.value = true;
  try {
    const path = hotReloadStatus.value?.enabled ? '/system/hot_reload/disable' : '/system/hot_reload/enable';
    const { data } = await api.post(path);
    hotReloadMessage.value = data?.message || '已更新';
    await fetchHotReloadStatus();
  } catch (err) {
    hotReloadMessage.value = err?.response?.data?.detail || err?.message || '热重载操作失败';
  } finally {
    hotReloadBusy.value = false;
  }
}
</script>

<style scoped>
.kpi { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:12px; }
.card { padding: 14px; border-radius: var(--radius-lg); }
.card .title { color: var(--text-secondary); font-size: 12px; }
.card .num { font-size: 24px; font-weight: 700; margin-top: 4px; }
.dot { display:inline-block; width:1em; height:1em; border-radius:50%; transition: background-color 0.3s ease; }
.dot.ok { background-color: var(--green-400); box-shadow: 0 0 8px var(--green-400); }
.dot.bad { background-color: var(--red-400); box-shadow: 0 0 8px var(--red-400); }
.table-wrap { overflow-y: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border-frosted); font-size: 13px; }
thead th { position: sticky; top: 0; background: var(--bg-panel-header); backdrop-filter: blur(4px); font-size: 12px; color: var(--text-secondary); }
.pill { padding: 2px 8px; border-radius: 99px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
.pill-blue { background-color: rgba(59,130,246,0.2); color: #60a5fa; }
.pill-green { background-color: rgba(34,197,94,0.2); color: #4ade80; }
.pill-red { background-color: rgba(239,68,68,0.2); color: #f87171; }
.pill-gray { background-color: rgba(156,163,175,0.2); color: #9ca3af; }
.toolbar { display:flex; justify-content: space-between; align-items:center; padding:10px 12px; border-radius: var(--radius-lg); margin-bottom:12px; }
.hot-reload { display:flex; align-items:center; gap:8px; flex-wrap: wrap; }
.ws-state { display:flex; align-items:center; gap:6px; color: var(--text-3); font-size: 12px; }
.grid-two { display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap:12px; }
.filters { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:8px; }
.filters input, .filters select { padding:6px 8px; border-radius:8px; border:1px solid var(--border-frosted); background: var(--bg-panel); color: var(--text-primary); }
.btn { padding:6px 10px; border-radius:8px; border:1px solid var(--border-frosted); background: var(--accent); color:#fff; cursor:pointer; }
.btn-sm { font-size:12px; }
.btn.ghost { background: transparent; color: var(--text-primary); }
.log-head { display:flex; align-items:center; gap:10px; margin-bottom:8px; }
.log-box { height: 32vh; border:1px solid var(--border-frosted); border-radius:12px; background: var(--bg-panel); padding:8px 10px; overflow-y:auto; font-family: monospace; font-size:12px; }
.log-line { display:flex; gap:8px; align-items:flex-start; padding:4px 0; border-bottom:1px solid var(--border-frosted); }
.log-line:last-child { border-bottom: none; }
.log-line .ts { color: var(--text-3); width: 64px; flex-shrink: 0; }
.log-line .lvl { color: var(--text-secondary); width: 64px; font-weight: 700; flex-shrink: 0; }
.log-line .msg { color: var(--text-primary); word-break: break-all; }
.error-text { color: var(--red-400); margin-top: 8px; font-size: 12px; }
.muted { color: var(--text-3); font-size: 12px; }
</style>

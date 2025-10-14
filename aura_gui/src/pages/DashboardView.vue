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
          <div class="num">{{ overview?.ready ?? '—' }}</div>
        </div>
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">Queue Delayed</div>
          <div class="num">{{ overview?.delayed ?? '—' }}</div>
        </div>
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">Avg Wait (est)</div>
          <div class="num">{{ avgWait }}</div>
        </div>
        <div class="card glass glass-thin glass-shimmer" v-tilt>
          <div class="title">Engine</div>
          <div class="num"><span class="dot" :class="isConnected ? 'ok':'bad'"></span></div>
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
              <tr v-for="r in recentShown" :key="r.id">
                <td><span class="pill" :class="statusClass(r.status)">{{ r.status.toUpperCase() }}</span></td>
                <td>{{ r.plan || '—' }}</td>
                <td>{{ r.task || '—' }}</td>
                <td>{{ fmt(r.startedAt) }}</td>
                <td>{{ fmt(r.finishedAt) }}</td>
                <td>{{ duration(r.startedAt, r.finishedAt) }}</td>
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
import {computed, onMounted} from 'vue';
import {useAuraSocket} from '../composables/useAuraSocket.js';
import {useRuns} from '../composables/useRuns.js';
import {useQueueStore} from '../composables/useQueueStore.js';

const {isConnected} = useAuraSocket();
const {activeRuns, recentRuns} = useRuns();
const {overview, fetchOverview} = useQueueStore();

onMounted(() => { fetchOverview?.(); });

const activeCount = computed(() => activeRuns.value.length);
const todayCount = computed(() => {
  const start = new Date(); start.setHours(0, 0, 0, 0);
  return recentRuns.value.filter(r => r.finishedAt && r.finishedAt >= start.getTime()).length;
});
const successRate24h = computed(() => {
  const since = Date.now() - 24 * 3600 * 1000;
  const win = recentRuns.value.filter(r => (r.finishedAt || 0) >= since);
  if (!win.length) return '—';
  const ok = win.filter(r => String(r.status).toLowerCase() === 'success').length;
  return Math.round(ok * 100 / win.length) + '%';
});
const p95Duration = computed(() => {
  const since = Date.now() - 24 * 3600 * 1000;
  const durs = recentRuns.value
      .filter(r => r.startedAt && r.finishedAt && r.finishedAt >= since)
      .map(r => r.finishedAt - r.startedAt)
      .sort((a, b) => a - b);
  if (!durs.length) return '—';
  const idx = Math.min(durs.length - 1, Math.floor(durs.length * 0.95));
  return humanMs(durs[idx]);
});
const avgWait = computed(() => '—');

const recentShown = computed(() => recentRuns.value.slice(0, 30));

function statusClass(s) {
  s = (s || 'queued').toLowerCase();
  if (s === 'running') return 'pill-blue';
  if (s === 'success') return 'pill-green';
  if (s === 'error' || s === 'failed') return 'pill-red';
  return 'pill-gray';
}
function pad(n){ return String(n).padStart(2,'0'); }
function fmt(ts){ if(!ts) return '—'; const d=new Date(ts); return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`; }
function duration(a,b){ if(!a||!b) return '—'; return humanMs(b-a); }
function humanMs(ms){ const s=Math.floor(ms/1000), h=Math.floor(s/3600), m=Math.floor((s%3600)/60), sec=s%60; return h?`${h}h ${m}m ${sec}s`:(m?`${m}m ${sec}s`:`${sec}s`); }
</script>

<style scoped>
.kpi {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}
.card { padding: 14px; border-radius: var(--radius-lg); }
.card .title { color: var(--text-secondary); font-size: 12px; }
.card .num { font-size: 24px; font-weight: 700; margin-top: 4px; }
</style>

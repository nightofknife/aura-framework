<!-- src/pages/RunsView.vue -->
<template>
  <div class="panel">
    <div class="panel-header">
      <strong>Runs</strong>
      <div style="color:var(--text-3); font-size:13px;">Filter and inspect task runs</div>
    </div>
    <div class="panel-body" style="display:flex; flex-direction:column; gap:12px;">
      <ProFilterBar
          v-model="filters"
          :status-options="['running','success','error','queued']"
          :plan-options="planOptions"
          @reset="onReset"
      />
      <ProDataTable
          :columns="columns"
          :rows="rowsView"
          row-key="id"
          :maxHeight="'70vh'"
          :sort-default="{key:'startedAt',dir:'desc'}"
          @row-click="openRun"
      >
        <template #col-status="{ row }">
          <span class="pill" :class="statusClass(row.status)">{{ safeUpper(row.status) }}</span>
        </template>
        <template #actions="{ row }">
          <button class="btn btn-outline" @click.stop="openRun(row)">Open</button>
        </template>
      </ProDataTable>
    </div>
  </div>

  <RunDetailDrawer :open="drawerOpen" :run="current" @close="drawerOpen=false"/>
</template>

<script setup>
import {computed, ref, watch} from 'vue';
import ProFilterBar from '../components/ProFilterBar.vue';
import ProDataTable from '../components/ProDataTable.vue';
import RunDetailDrawer from '../components/RunDetailDrawer.vue';
import {useRuns} from '../composables/useRuns.js';
import {useAuraSocket} from '../composables/useAuraSocket.js';

const {activeRuns, recentRuns, runsById} = useRuns();
const {lastMessage} = useAuraSocket();

const columns = [
  {key: 'status', label: 'Status', width: '110px'},
  {key: 'plan', label: 'Plan', sortable: true, width: '180px'},
  {key: 'task', label: 'Task', sortable: true},
  {key: 'startedAt', label: 'Started', sortable: true, width: '180px'},
  {key: 'finishedAt', label: 'Finished', sortable: true, width: '180px'},
  {key: 'elapsed', label: 'Duration', sortable: true, width: '110px'},
];

const filters = ref({query: '', status: '', plan: ''});
const planOptions = computed(() => {
  const set = new Set([...activeRuns.value, ...recentRuns.value].map(r => r.plan).filter(Boolean));
  return [...set];
});

const rows = computed(() => {
  const all = [...activeRuns.value, ...recentRuns.value];
  return all.map(r => ({
    id: r.id, plan: r.plan, task: r.task, status: r.status,
    startedAt: r.startedAt ? new Date(r.startedAt) : null,
    finishedAt: r.finishedAt ? new Date(r.finishedAt) : null,
    elapsed: r.startedAt && r.finishedAt ? r.finishedAt - r.startedAt : (r.startedAt ? Date.now() - r.startedAt : null),
  }));
});

const rowsView = computed(() => {
  let list = rows.value;
  const q = (filters.value.query || '').toLowerCase();
  if (q) list = list.filter(r => (r.plan || '').toLowerCase().includes(q) || (r.task || '').toLowerCase().includes(q) || (r.id || '').toLowerCase().includes(q));
  if (filters.value.status) list = list.filter(r => r.status === filters.value.status);
  if (filters.value.plan) list = list.filter(r => r.plan === filters.value.plan);
  return list;
});

function onReset() { /* noop */ }

function statusClass(s) {
  const v = (s || 'queued').toLowerCase();
  if (v === 'running') return 'pill-blue';
  if (v === 'success') return 'pill-green';
  if (v === 'error' || v === 'failed') return 'pill-red';
  return 'pill-gray';
}
function pad(n) { return String(n).padStart(2, '0'); }
function fmt(ts) { if (!ts) return '—'; const d = new Date(ts); return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; }
function duration(a, b) { if (!a || !b) return '—'; const ms = b - a; const s = Math.floor(ms / 1000), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60; return h ? `${h}h ${m}m ${sec}s` : (m ? `${m}m ${sec}s` : `${sec}s`); }
function safeUpper(s) { const t = (s == null ? '' : String(s)); return t ? t.toUpperCase() : '—'; }

const drawerOpen = ref(false);
const current = ref(null);
function openRun(row) {
  const r = runsById.value[row.id] || row;
  current.value = r;
  drawerOpen.value = true;
}

// （可选）如果有 log.append 事件但 run 不存在，延迟创建容器以承接日志
watch(lastMessage, evt => {
  if (!evt || (evt.name||'').toLowerCase()!=='log.append') return;
  const p = evt.payload || {};
  if (!p.run_id) return;
  if (!runsById.value[p.run_id]) {
    runsById.value[p.run_id] = { id: p.run_id, plan: p.plan_name, task: p.task_name, status: 'running', startedAt: null, finishedAt: null, logs: [], timeline: {nodes: []} };
  }
});
</script>

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
          :row-key="row => row.cid || row.id"
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
import { computed, ref } from 'vue';
import ProFilterBar from '../components/ProFilterBar.vue';
import ProDataTable from '../components/ProDataTable.vue';
import RunDetailDrawer from '../components/RunDetailDrawer.vue';
import { useRuns } from '../composables/useRuns.js';

const { activeRuns, recentRuns, runsById } = useRuns();

const columns = [
  { key: 'status', label: 'Status', width: '110px' },
  { key: 'plan_name', label: 'Plan', sortable: true, width: '180px' },
  { key: 'task_name', label: 'Task', sortable: true },
  { key: 'startedAt', label: 'Started', sortable: true, width: '180px' },
  { key: 'finishedAt', label: 'Finished', sortable: true, width: '180px' },
  { key: 'elapsed', label: 'Duration', sortable: true, width: '110px' },
];

const filters = ref({ query: '', status: '', plan: '' });

const planOptions = computed(() => {
  const set = new Set([...activeRuns.value, ...recentRuns.value].map(r => r.plan_name).filter(Boolean));
  return [...set];
});

const rows = computed(() => {
  const all = [...activeRuns.value, ...recentRuns.value];
  return all.map(r => ({
    id: r.id,
    cid: r.cid,
    plan_name: r.plan_name,
    task_name: r.task_name,
    status: r.status,
    startedAt: r.started_at || r.startedAt ? new Date(r.started_at || r.startedAt) : null,
    finishedAt: r.finished_at || r.finishedAt ? new Date(r.finished_at || r.finishedAt) : null,
    elapsed: (() => {
      const start = r.started_at || r.startedAt;
      const end = r.finished_at || r.finishedAt;
      if (start && end) return end - start;
      if (start) return Date.now() - start;
      return null;
    })(),
  }));
});

const rowsView = computed(() => {
  let list = rows.value;
  const q = (filters.value.query || '').toLowerCase();
  if (q) {
    list = list.filter(r =>
        (r.plan_name || '').toLowerCase().includes(q) ||
        (r.task_name || '').toLowerCase().includes(q) ||
        (r.cid || r.id || '').toLowerCase().includes(q)
    );
  }
  if (filters.value.status) list = list.filter(r => r.status === filters.value.status);
  if (filters.value.plan) list = list.filter(r => r.plan_name === filters.value.plan);
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

function safeUpper(s) {
  const t = (s == null ? '' : String(s));
  return t ? t.toUpperCase() : '—';
}

const drawerOpen = ref(false);
const current = ref(null);

function openRun(row) {
  const runId = row.cid || row.id;
  const r = runsById.value[runId] || row;
  current.value = r;
  drawerOpen.value = true;
}
</script>

<style scoped>
.panel {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.panel-body {
  flex: 1;
  overflow: hidden;
}
</style>

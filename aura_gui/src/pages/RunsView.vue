<!-- 运行记录（点击行加载 /run/{id}/detail 展示抽屉） -->
<template>
  <div class="panel">
    <div class="panel-header">
      <strong>运行记录</strong>
      <div style="color:var(--text-3); font-size:13px;">筛选并查看任务运行详情</div>
    </div>
    <div class="panel-body" style="display:flex; flex-direction:column; gap:12px;">
      <ProFilterBar
          v-model="filters"
          :status-options="['running','success','error','queued']"
          :plan-options="planOptions"
          @reset="onReset"
      />

      <!-- 使用虚拟滚动列表替代 ProDataTable -->
      <VirtualRunsList
          :runs="rowsView"
          :max-height="'70vh'"
          @row-click="openRun"
      />

      <div v-if="detailError" class="error">{{ detailError }}</div>
    </div>
  </div>

  <RunDetailDrawer :open="drawerOpen" :run="current" @close="drawerOpen=false"/>
</template>

<script setup>
import { computed, ref } from 'vue';
import axios from 'axios';
import { getGuiConfig } from '../config.js';
import ProFilterBar from '../components/ProFilterBar.vue';
import VirtualRunsList from '../components/VirtualRunsList.vue';
import RunDetailDrawer from '../components/RunDetailDrawer.vue';
import { useRuns } from '../composables/useRuns.js';

const { activeRuns, recentRuns, runsById } = useRuns();
const cfg = getGuiConfig();
const api = axios.create({ baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1', timeout: cfg?.api?.timeout_ms || 5000 });

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

const drawerOpen = ref(false);
const current = ref(null);
const detailError = ref('');

async function openRun(row) {
  detailError.value = '';
  const runId = row.cid || row.id;
  const r = runsById.value[runId] || row;
  try {
    const { data } = await api.get(`/run/${runId}/detail`);
    const merged = { ...r, ...(data?.run || {}), nodes: data?.timeline || [], logs: data?.logs || [] };
    current.value = merged;
    drawerOpen.value = true;
  } catch (err) {
    detailError.value = err?.response?.data?.detail || err?.message || '获取详情失败';
  }
}
</script>

<style scoped>
.panel { height: 100%; display: flex; flex-direction: column; }
.panel-body { flex: 1; overflow: hidden; }
.error { color: var(--red-400); font-size: 12px; }
</style>

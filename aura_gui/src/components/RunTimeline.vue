<template>
  <div class="tl">
    <div class="tl-legend">
      <span>Timeline</span>
      <span style="margin-left:auto; font-size:12px;">{{ rangeText }}</span>
    </div>
    <div class="tl-rows" v-if="nodes && nodes.length">
      <div v-for="n in viewNodes" :key="n.node_id" class="tl-row">
        <div class="tl-label" :title="n.node_id">{{ n.node_id }}</div>
        <div class="tl-bars">
          <div
              class="tl-bar"
              :class="barClass(n)"
              :style="barStyle(n)"
              :title="barTitle(n)"
          ></div>
        </div>
        <div class="tl-time">{{ fmtDur(n) }}</div>
      </div>
    </div>
    <div v-else style="color:var(--text-3); font-size:13px;">No node spans yet.</div>
  </div>
</template>

<script setup>
import {computed} from 'vue';

// 期望 run 里有： { startedAt, finishedAt, status, timeline?: { nodes:[ {node_id, startMs, endMs?, status} ] } }
const props = defineProps({run: {type: Object, required: true}});

// 归一化 nodes
const nodes = computed(() => {
  const arr = props.run?.timeline?.nodes || [];
  return arr.map(x => ({
    node_id: x.node_id || x.id || 'node',
    startMs: normMs(x.startMs ?? x.start ?? x.start_time),
    endMs: x.endMs != null ? normMs(x.endMs) : (x.end != null ? normMs(x.end) : null),
    status: (x.status || 'running').toLowerCase(),
    progress: x.progress ?? null,
  }));
});

function normMs(v) {
  if (v == null) return null;
  // 后端可能是秒(float)，也可能就是 ms
  return v > 1e12 ? v : Math.floor(v * 1000);
}

const minTs = computed(() => {
  let t = props.run?.startedAt || Infinity;
  nodes.value.forEach(n => {
    if (n.startMs != null) t = Math.min(t, n.startMs);
  });
  return t === Infinity ? Date.now() - 10_000 : t;
});
const maxTs = computed(() => {
  let t = props.run?.finishedAt || 0;
  nodes.value.forEach(n => {
    t = Math.max(t, n.endMs ?? Date.now());
  });
  return Math.max(t, Date.now());
});

const span = computed(() => Math.max(1, maxTs.value - minTs.value));
const rangeText = computed(() => {
  const dur = span.value;
  const s = Math.floor(dur / 1000);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}h ${m}m ${sec}s` : (m ? `${m}m ${sec}s` : `${sec}s`);
});

const viewNodes = computed(() => {
  // 保持原序；若需要可按开始时间排序
  return nodes.value;
});

function pct(x) {
  return Math.max(0, Math.min(100, (x / span.value) * 100));
}

function barStyle(n) {
  const left = pct((n.startMs - minTs.value));
  const end = (n.endMs ?? Date.now()) - minTs.value;
  const width = pct(end);
  return {left: left + '%', width: Math.max(1, width - left) + '%'};
}

function barClass(n) {
  if (!n.endMs) return 'running';
  if (n.status === 'success') return 'success';
  if (n.status === 'error' || n.status === 'failed' || n.status === 'failure') return 'error';
  return 'running';
}

function fmtDur(n) {
  const to = n.endMs ?? Date.now();
  const ms = Math.max(0, to - n.startMs);
  const s = Math.floor(ms / 1000), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}h ${m}m ${sec}s` : (m ? `${m}m ${sec}s` : `${sec}s`);
}

function barTitle(n) {
  const status = n.status?.toUpperCase?.() || (n.endMs ? 'DONE' : 'RUNNING');
  return `${n.node_id} • ${status} • ${fmtDur(n)}`;
}
</script>

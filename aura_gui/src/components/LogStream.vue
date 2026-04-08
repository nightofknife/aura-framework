<!-- src/components/LogStream.vue -->
<template>
  <div class="log-wrap">
    <div class="toolbar">
      <select class="select" v-model="level">
        <option value="">All</option>
        <option>info</option>
        <option>warn</option>
        <option>error</option>
      </select>
      <input class="input" v-model="query" placeholder="Filter text…">
      <label class="chk"><input type="checkbox" v-model="autoscroll"> Auto-scroll</label>
      <button class="btn btn-ghost btn-sm" @click="download">Download</button>
    </div>
    <div class="lines" ref="scroller">
      <div v-for="(l, i) in filtered" :key="i" class="line">
        <span class="ts">{{ fmt(l.ts) }}</span>
        <span class="lvl" :class="(l.level||'info').toLowerCase()">{{ (l.level||'info').toUpperCase() }}</span>
        <span class="msg" v-html="hi(l.message)"></span>
      </div>
      <div v-if="filtered.length===0" class="empty">No log lines yet…</div>
    </div>
  </div>
</template>

<script setup>
import {computed, ref, watch, nextTick} from 'vue';

const props = defineProps({
  logs: { type: Array, default: () => [] },
});
const level = ref('');
const query = ref('');
const autoscroll = ref(true);
const scroller = ref(null);

const filtered = computed(() => {
  const lv = level.value.toLowerCase();
  const q = query.value.trim().toLowerCase();
  return (props.logs || []).filter(l => {
    const okLv = !lv || (String(l.level||'info').toLowerCase()===lv);
    const okQ = !q || (String(l.message||'').toLowerCase().includes(q));
    return okLv && okQ;
  });
});

watch(() => props.logs?.length, async () => {
  if (!autoscroll.value) return;
  await nextTick();
  const el = scroller.value;
  if (el) el.scrollTop = el.scrollHeight + 9999;
});

function pad(n){ return String(n).padStart(2,'0'); }
function fmt(ts){
  const d = ts ? new Date(ts) : new Date();
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
function esc(s){ return String(s).replace(/[&<>]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[m])); }
function hi(s){
  const q = query.value.trim();
  if (!q) return esc(s);
  return esc(s).replace(new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'), 'gi'), m => `<mark>${m}</mark>`);
}
function download(){
  const text = (props.logs||[]).map(l => `[${fmt(l.ts)}] ${(l.level||'info').toUpperCase()} ${l.message}`).join('\n');
  const blob = new Blob([text], {type:'text/plain;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = `logs-${Date.now()}.txt`; a.click();
  URL.revokeObjectURL(url);
}
</script>

<style scoped>
.log-wrap{ display:flex; flex-direction:column; gap:8px; min-height: 240px; }
.toolbar{ display:flex; gap:8px; align-items:center; }
.chk{ font-size:12px; color: var(--text-3); display:flex; gap:6px; align-items:center; }
.lines{ border:1px solid var(--border); border-radius: var(--radius); background:#fff; padding:8px 10px; overflow:auto; max-height: 46vh; }
.line{ display:flex; gap:10px; padding:4px 0; border-bottom:1px dashed #eee; }
.line:last-child{ border-bottom:none; }
.ts{ width:56px; color:#999; font-family: ui-monospace, Menlo, monospace; }
.lvl{ font-size:.75em; font-weight:700; padding:1px 6px; border-radius:999px; color:#fff; background:#6b7280; align-self:center;}
.lvl.warn{ background:#d97706; }
.lvl.error{ background:#dc2626; }
.msg{ white-space: pre-wrap; word-break: break-word; }
.empty{ color:#999; text-align:center; padding:14px 0; }
</style>

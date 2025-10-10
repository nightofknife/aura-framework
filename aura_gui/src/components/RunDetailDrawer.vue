<!-- src/components/RunDetailDrawer.vue -->
<template>
  <div class="drawer-mask" v-if="open" @click.self="$emit('close')">
    <div class="drawer">
      <div class="drawer-header">
        <strong>Run • {{ run?.task || '—' }}</strong>
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
            <span>Status: <b :class="'pill '+statusClass(run.status)">{{ (run.status||'—').toUpperCase() }}</b></span>
            <span>Started: {{ fmt(run.startedAt) }}</span>
            <span>Finished: {{ fmt(run.finishedAt) }}</span>
            <span>Duration: {{ duration(run.startedAt, run.finishedAt) }}</span>
          </div>
          <div class="tl-rows">
            <div class="tl-row" v-for="(n,idx) in (run.timeline?.nodes||[])" :key="idx">
              <div class="tl-label">{{ n.node_id || n.id || ('step '+(idx+1)) }}</div>
              <div class="tl-bars">
                <div class="tl-bar" :class="n.status || 'running'" :style="barStyle(n)"></div>
              </div>
              <div class="tl-time">{{ nodeDur(n) }}</div>
            </div>
            <div v-if="!run.timeline || !run.timeline.nodes || !run.timeline.nodes.length" style="color:var(--text-3);">No timeline data.</div>
          </div>
        </div>

        <!-- Logs -->
        <div v-else-if="tab==='logs'">
          <LogStream :logs="logs"/>
        </div>

        <!-- Params -->
        <div v-else-if="tab==='params'" style="display:grid; gap:12px;">
          <div><b>Plan:</b> {{ run.plan }}</div>
          <div><b>Task:</b> {{ run.task }}</div>
          <div><b>Run ID:</b> <code>{{ run.id }}</code></div>
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
import {computed, ref, watch} from 'vue';
import {useAuraSocket} from '../composables/useAuraSocket.js';
import {useRuns} from '../composables/useRuns.js';
import LogStream from './LogStream.vue';

const props = defineProps({
  open: Boolean,
  run: Object,
});
const emit = defineEmits(['close']);

const tab = ref('timeline');
watch(() => props.open, v => { if (v) tab.value = 'timeline'; });

// —— Logs：从全局 runs store 中取，如果收到 log.append 则写回去 —— //
const { lastMessage } = useAuraSocket();
const { runsById } = useRuns();

const logs = computed(() => {
  const r = props.run ? runsById.value[props.run.id] || props.run : null;
  return Array.isArray(r?.logs) ? r.logs : [];
});

watch(lastMessage, evt => {
  if (!props.open || !evt) return;
  if ((evt.name||'').toLowerCase() !== 'log.append') return;
  const p = evt.payload || {};
  // 1) run_id 直接匹配
  let target = p.run_id ? runsById.value[p.run_id] : null;
  // 2) 退化匹配：plan+task & running（兼容无 run_id）
  if (!target) {
    const cand = Object.values(runsById.value).find(r => r.status==='running' && r.plan===p.plan_name && r.task===p.task_name);
    if (cand) target = cand;
  }
  if (!target) return;

  if (!Array.isArray(target.logs)) target.logs = [];
  target.logs.push({
    ts: toMs(p.ts) || Date.now(),
    level: (p.level || 'info').toLowerCase(),
    message: String(p.text || p.message || ''),
  });
});

function toMs(v){ return (v && v>1e12) ? v : (v ? Math.floor(v*1000): null); }
function pad(n){ return String(n).padStart(2,'0'); }
function fmt(ts){ if (!ts) return '—'; const d=new Date(ts); return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; }
function duration(a,b){ if(!a||!b) return '—'; const ms=b-a; const s=Math.floor(ms/1000), h=Math.floor(s/3600), m=Math.floor((s%3600)/60), sec=s%60;
  return h?`${h}h ${m}m ${sec}s`: (m?`${m}m ${sec}s`:`${sec}s`); }
function statusClass(s){ const v=(s||'queued').toLowerCase(); if(v==='running')return 'pill-blue'; if(v==='success')return 'pill-green'; if(v==='error'||v==='failed')return 'pill-red'; return 'pill-gray'; }
function pretty(o){ try{ return JSON.stringify(o, null, 2);}catch{return String(o);} }

function nodeDur(n){
  const a = n.startMs || 0, b = n.endMs || Date.now();
  const ms = Math.max(0, b-a); const s=Math.floor(ms/1000);
  return s>=1 ? `${s}s` : `${ms}ms`;
}
function barStyle(n){
  // 简易：按 run 总时长近似定位（不依赖绝对时间轴）
  const w = 100; // full
  const p = n.progress != null ? Math.max(0, Math.min(100, n.progress)) : (n.endMs && n.startMs ? 100 : 60);
  return { left:'0%', width: `${p/100*w}%` };
}

const errorLines = computed(() => logs.value.filter(l => (l.level||'info').toLowerCase()==='error'));
</script>

<style scoped>
.json{ background:#0b102126; color:#111; border-radius:12px; padding:10px; overflow:auto; }
.err .log{ display:grid; grid-template-columns: 80px 1fr; gap:10px; padding:6px 0; border-bottom:1px dashed #eee; }
.err .log:last-child{ border-bottom:none; }
.ts{ color:#999; font-family: ui-monospace, Menlo, monospace; }
</style>

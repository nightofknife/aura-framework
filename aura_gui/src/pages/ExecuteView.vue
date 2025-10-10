<template>
  <div class="panel">
    <div class="panel-header" style="align-items:end;">
      <div>
        <strong>Execute</strong>
        <div style="color:var(--text-3); font-size:13px;">添加任务（方案展开选择）→ 排队 → 运行/暂停 → 观察</div>
      </div>
      <div class="toolbar">
        <button class="btn btn-primary hold-btn"
                @mousedown="onHoldStart('run')" @mouseup="onHoldEnd('run')" @mouseleave="onHoldCancel('run')"
                @touchstart.prevent="onHoldStart('run')" @touchend.prevent="onHoldEnd('run')">
          <div class="hold-progress" :style="{ width: hold.run+'%' }"></div>
          <span v-if="!autoMode">▶ Run</span><span v-else>⚡ Auto</span>
        </button>
        <button class="btn hold-btn"
                @mousedown="onHoldStart('pause')" @mouseup="onHoldEnd('pause')" @mouseleave="onHoldCancel('pause')"
                @touchstart.prevent="onHoldStart('pause')" @touchend.prevent="onHoldEnd('pause')">
          <div class="hold-progress" :style="{ width: hold.pause+'%' }"></div>
          ⏸ Pause
        </button>
        <span v-if="running" class="pill pill-blue">DISPATCHING…</span>
        <span v-else class="pill pill-gray">IDLE</span>
        <span v-if="autoMode" class="pill pill-green">AUTO</span>
      </div>
    </div>

    <!-- 添加任务：按计划（含搜索） + 收藏 -->
    <div class="panel-body" style="display:flex; flex-direction:column; gap:12px;">
      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px;">
        <!-- 方案：按计划（合并搜索；当前 plan 匹配优先；分组标题） -->
        <SchemePanel v-model:open="open.byPlan" title="按计划（含搜索）" description="优先展示当前 Plan 的匹配任务，其次展示其它 Plan 的匹配任务">
          <div style="display:flex; gap:8px; align-items:center; margin-bottom:8px;">
            <select class="select" v-model="ui.planSelected">
              <option disabled value="">选择 Plan…</option>
              <option v-for="p in plans" :key="p.name" :value="p.name">{{ p.name }}</option>
            </select>
            <input ref="searchEl" class="input" v-model="ui.query" placeholder="搜索任务…（标题/描述/plan/task）" @keydown.stop />
            <span class="hint">按 <kbd>/</kbd> 聚焦搜索</span>
          </div>

          <!-- 栅格 + 渐隐动效 -->
          <TransitionGroup name="fade" tag="div" class="grid">
            <!-- 分组标题（当前 Plan） -->
            <div v-if="showGroupHeaders" key="grp-in" class="grid-header">当前 Plan 的匹配</div>
            <TaskMiniCard
                v-for="t in grouped.inPlan" :key="t.__key"
                :title="t.title" :titleHtml="t.titleHtml"
                :description="t.desc" :descHtml="t.descHtml"
                :plan="t.plan"
                :starred="isFav(t.plan, t.task)"
                @toggle-fav="toggleFav(t.plan, t.task)"
                @select="openConfig(t.plan, t.task, t.meta)"
            />

            <!-- 分组标题（其它 Plan） -->
            <div v-if="showGroupHeaders && grouped.other.length" key="grp-out" class="grid-header">其他 Plan 的匹配</div>
            <TaskMiniCard
                v-for="t in grouped.other" :key="t.__key"
                :title="t.title" :titleHtml="t.titleHtml"
                :description="t.desc" :descHtml="t.descHtml"
                :plan="t.plan"
                :starred="isFav(t.plan, t.task)"
                @toggle-fav="toggleFav(t.plan, t.task)"
                @select="openConfig(t.plan, t.task, t.meta)"
            />

            <div v-if="!grouped.inPlan.length && !grouped.other.length" key="empty" class="empty">暂无匹配结果。</div>
          </TransitionGroup>
        </SchemePanel>

        <!-- 方案：收藏 -->
        <SchemePanel v-model:open="open.favs" title="收藏（Favorites）" description="常用任务打★后快速进入">
          <TransitionGroup name="fade" tag="div" class="grid">
            <TaskMiniCard
                v-for="t in favTasksView" :key="t.__key"
                :title="t.title" :titleHtml="highlight(t.title)"
                :description="t.desc" :descHtml="highlight(t.desc)"
                :plan="t.plan"
                :starred="true"
                @toggle-fav="toggleFav(t.plan, t.task)"
                @select="openConfig(t.plan, t.task, t.meta)"
            />
            <div v-if="!favTasksView.length" key="emptyfav" class="empty">还没有收藏任务。</div>
          </TransitionGroup>
        </SchemePanel>
      </div>

      <!-- 队列（默认简略，可展开详情；拖拽排序） -->
      <div class="panel" style="margin-top:4px;">
        <div class="panel-header">
          <strong>Staging ({{ stagingList.length }})</strong>
          <div style="display:flex; gap:8px; align-items:center;">
            <button class="btn btn-ghost" @click="expandAll(true)" :disabled="!stagingList.length">Expand all</button>
            <button class="btn btn-ghost" @click="expandAll(false)" :disabled="!stagingList.length">Collapse all</button>
            <button class="btn btn-ghost" @click="clearAll" :disabled="running || !stagingList.length">Clear</button>
          </div>
        </div>

        <div class="panel-body" style="padding:0;">
          <div class="table-wrap" style="max-height:52vh;">
            <table>
              <thead>
              <tr>
                <th style="width:36px;"></th>
                <th style="width:26px;"></th>
                <th>Plan / Task</th>
                <th>Inputs (preview)</th>
                <th style="width:90px;">Priority</th>
                <th style="width:1%;">Status</th>
                <th style="width:1%;">Actions</th>
              </tr>
              </thead>

              <tbody>
              <template v-for="it in stagingList" :key="it.id">
                <!-- 简略行：支持拖拽 -->
                <tr
                    :class="['row-draggable', dragOverId===it.id && 'row-drop-target']"
                    @dragover.prevent="onDragOver(it.id)"
                    @drop.prevent="onDrop(it.id)"
                    @dragleave="onDragLeave(it.id)"
                >
                  <td>
                    <button class="btn btn-ghost btn-sm" @click="toggleRow(it.id)">{{ expanded.has(it.id) ? '▾' : '▸' }}</button>
                  </td>
                  <td>
                    <button
                        class="drag-handle"
                        title="拖拽排序"
                        draggable="true"
                        @dragstart="onDragStart(it.id, $event)"
                        @dragend="onDragEnd"
                        aria-label="drag to reorder"
                    >⠿</button>
                  </td>
                  <td><strong>{{ it.plan_name }}</strong> / {{ it.task_name }}</td>
                  <td><code style="font-size:12px;">{{ previewInputs(it.inputs) }}</code></td>
                  <td>{{ it.priority ?? '—' }}</td>
                  <td>
                    <span class="pill" :class="statusPill(it.status)">{{ safeUpper(it.status || 'pending') }}</span>
                    <span v-if="it.toDispatch" class="pill pill-blue" style="margin-left:6px;">BATCH</span>
                  </td>
                  <td style="white-space:nowrap;">
                    <button class="btn btn-ghost" @click="moveUp(it)">↑</button>
                    <button class="btn btn-ghost" @click="moveDown(it)">↓</button>
                    <button class="btn" @click="remove(it)" :disabled="it.status==='running'">Del</button>
                  </td>
                </tr>

                <!-- 展开详情：滑动动画 -->
                <Transition name="expand">
                  <tr v-if="expanded.has(it.id)">
                    <td></td><td></td>
                    <td colspan="5">
                      <div class="detail">
                        <div class="kv"><span>Note</span><div>{{ it.note || '—' }}</div></div>
                        <div class="kv"><span>Inputs</span><pre class="json">{{ pretty(it.inputs) }}</pre></div>
                      </div>
                    </td>
                  </tr>
                </Transition>
              </template>

              <tr v-if="!stagingList.length">
                <td :colspan="7" style="color:var(--text-3);">队列为空，请先在上方方案中添加任务。</td>
              </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- 已完成（默认折叠） -->
      <details>
        <summary class="panel-header" style="list-style:none; cursor:pointer;">
          <strong>Completed ({{ historyList.length }})</strong>
          <div style="display:flex; gap:8px; align-items:center;">
            <input class="input" v-model="qHist" placeholder="Search… (plan/task/inputs)">
            <button class="btn btn-ghost" @click="clearHistory" :disabled="!historyList.length">Clear</button>
          </div>
        </summary>
        <div class="panel-body" style="padding:0;">
          <div class="table-wrap" style="max-height:38vh;">
            <table>
              <thead>
              <tr>
                <th style="width:36px;">#</th>
                <th>Plan</th>
                <th>Task</th>
                <th>Inputs</th>
                <th style="width:120px;">Finished</th>
                <th style="width:1%;">Actions</th>
              </tr>
              </thead>
              <tbody>
              <tr v-for="(h, idx) in filteredHistory" :key="h.id + ':' + h.finishedAt">
                <td style="color:var(--text-3);">{{ idx + 1 }}</td>
                <td>{{ h.plan_name }}</td>
                <td>{{ h.task_name }}</td>
                <td><code style="font-size:12px;">{{ JSON.stringify(h.inputs || {}) }}</code></td>
                <td>{{ fmt(h.finishedAt) }}</td>
                <td><button class="btn btn-ghost" @click="requeue(h)">Requeue</button></td>
              </tr>
              <tr v-if="!filteredHistory.length">
                <td :colspan="6" style="color:var(--text-3);">No completed tasks yet.</td>
              </tr>
              </tbody>
            </table>
          </div>
        </div>
      </details>
    </div>
  </div>

  <!-- 参数配置抽屉（仅添加时使用） -->
  <ProContextPanel :open="cfg.open" :title="cfg.title" @close="cfg.open=false">
    <div v-if="cfg.task">
      <div style="margin-bottom:10px; color:var(--text-3); font-size:12px;">{{ cfg.plan }} / {{ cfg.task }}</div>

      <div v-if="hasSchema" style="display:grid; gap:10px;">
        <div v-for="f in schemaFields" :key="f.key">
          <div style="font-size:12px; color:var(--text-3);">{{ f.label }}</div>
          <select class="select" v-if="f.type==='enum'" v-model="formModel[f.key]">
            <option v-for="opt in f.enum" :key="opt" :value="opt">{{ opt }}</option>
          </select>
          <input class="input" v-else-if="f.type==='string'" v-model="formModel[f.key]" :placeholder="f.placeholder || ''">
          <input class="input" v-else-if="f.type==='number'" type="number" v-model.number="formModel[f.key]">
          <label v-else-if="f.type==='boolean'" class="chk"><input type="checkbox" v-model="formModel[f.key]"> {{ f.onLabel || 'Enabled' }}</label>
          <div v-if="f.help" style="color:var(--text-3); font-size:12px; margin-top:4px;">{{ f.help }}</div>
        </div>
      </div>

      <div v-else>
        <div style="font-size:12px; color:var(--text-3);">Inputs (JSON)</div>
        <textarea class="input" v-model="cfg.inputsRaw" rows="10" style="width:100%; font-family: ui-monospace, Menlo, monospace;"></textarea>
        <div v-if="cfg.jsonError" style="color:var(--danger); font-size:12px; margin-top:4px;">{{ cfg.jsonError }}</div>
      </div>

      <details style="margin-top:12px;">
        <summary style="cursor:pointer; color:var(--text-2);"><b>Advanced</b> (priority & note)</summary>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:10px;">
          <div>
            <div style="font-size:12px; color:var(--text-3);">Priority (optional)</div>
            <input class="input" v-model.number="cfg.priority" type="number" placeholder="e.g. 5">
          </div>
          <div>
            <div style="font-size:12px; color:var(--text-3);">Note</div>
            <input class="input" v-model="cfg.note" placeholder="Optional note">
          </div>
        </div>
      </details>

      <div style="margin-top:12px; display:flex; gap:8px;">
        <button class="btn btn-primary" @click="confirmAdd" :disabled="!canAdd">Add to Queue</button>
        <button class="btn btn-ghost" @click="cfg.open=false">Cancel</button>
      </div>
    </div>
    <div v-else style="color:var(--text-3);">未选择任务。</div>
  </ProContextPanel>
</template>

<script setup>
import {computed, reactive, ref, onMounted, watch} from 'vue';
import axios from 'axios';
import SchemePanel from '../components/SchemePanel.vue';
import TaskMiniCard from '../components/TaskMiniCard.vue';
import ProContextPanel from '../components/ProContextPanel.vue';
import {useStagingQueue} from '../composables/useStagingQueue.js';
import {useStagingRunner} from '../composables/useStagingRunner.js';
import {useToasts} from '../composables/useToasts.js';

const {push: toast} = useToasts();
const api = axios.create({ baseURL:'http://127.0.0.1:8000/api', timeout:5000 });

// 运行控制（含长按切换）
const {running, autoMode, startBatch, pause, setAuto, forceStop} = useStagingRunner();
const hold = reactive({run: 0, pause: 0, _timer: null});
const HOLD_MS = 700;
function onHoldStart(target) {
  let t0 = Date.now();
  clearInterval(hold._timer);
  hold._timer = setInterval(() => {
    const p = Math.min(100, Math.round((Date.now() - t0) / HOLD_MS * 100));
    if (target === 'run') hold.run = p; else hold.pause = p;
    if (p >= 100) { clearInterval(hold._timer); if (target==='run'){ setAuto(!autoMode.value); toast({type:'success', title:`Auto mode ${autoMode.value?'ON':'OFF'}`}); } else { forceStop(); } }
  }, 16);
}
function onHoldEnd(target){ clearInterval(hold._timer); const p = target==='run'?hold.run:hold.pause; if (p<100){ target==='run'?startBatch():pause(); } hold.run=0; hold.pause=0; }
function onHoldCancel(){ clearInterval(hold._timer); hold.run=0; hold.pause=0; }

// Plans & Tasks
const plans = ref([]);
const allTasks = ref([]); // { __key, plan, task, title, desc, meta }
async function loadPlans(){
  try{ const {data} = await api.get('/plans'); plans.value = data || []; }
  catch {}
}
async function loadAllTasks(){
  const result = [];
  for (const p of plans.value) {
    try{
      const {data} = await api.get(`/plans/${p.name}/tasks`);
      (data||[]).forEach(t => {
        result.push({
          __key: `${p.name}::${t.task_name_in_plan || t.task_name}`,
          plan: p.name,
          task: t.task_name_in_plan || t.task_name,
          title: t.meta?.title || (t.task_name_in_plan || t.task_name),
          desc: t.meta?.description || '',
          meta: t.meta || {},
        });
      });
    } catch {}
  }
  allTasks.value = result;
}

// 方案状态 & 查询
const open = reactive({ byPlan: true, favs: false });
const ui = reactive({ planSelected: '', query: '' });

// 搜索 & 高亮
const searchEl = ref(null);
function focusSearch(){ searchEl.value?.focus?.(); }
function escHtml(s=''){ return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function highlight(s){
  const q = (ui.query||'').trim();
  if (!q) return escHtml(String(s||''));
  const rx = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'ig');
  return escHtml(String(s||'')).replace(rx, '<mark>$1</mark>');
}

// 组合/排序（收藏置顶 & 稳定排序）
const FAV_KEY = 'exec.favs';
const favSet = ref(new Set(JSON.parse(localStorage.getItem(FAV_KEY) || '[]')));
function isFav(plan, task){ return favSet.value.has(`${plan}::${task}`); }
function toggleFav(plan, task){
  const k = `${plan}::${task}`;
  if (favSet.value.has(k)) favSet.value.delete(k); else favSet.value.add(k);
  localStorage.setItem(FAV_KEY, JSON.stringify([...favSet.value]));
}
const grouped = computed(()=>{
  const ps = ui.planSelected || (plans.value[0]?.name || '');
  const q = (ui.query || '').trim().toLowerCase();
  const match = (t) => !q || (t.plan + t.task + t.title + t.desc).toLowerCase().includes(q);

  // 分组
  const inPlan = allTasks.value.filter(t => t.plan === ps && match(t));
  const other  = allTasks.value.filter(t => t.plan !== ps && match(t));

  // 收藏置顶 + 稳定排序（收藏优先，接着 title 升序，再 plan/task）
  const cmp = (a,b)=>{
    const af = isFav(a.plan,a.task), bf = isFav(b.plan,b.task);
    if (af !== bf) return af ? -1 : 1;
    const at = a.title.localeCompare(b.title);
    if (at) return at;
    const ap = a.plan.localeCompare(b.plan);
    if (ap) return ap;
    return a.task.localeCompare(b.task);
  };
  const inPlanSorted = [...inPlan].sort(cmp).map(t => ({...t, titleHtml: highlight(t.title), descHtml: highlight(t.desc)}));
  const otherSorted  = [...other].sort(cmp).map(t => ({...t, titleHtml: highlight(t.title), descHtml: highlight(t.desc)}));

  return { inPlan: inPlanSorted, other: otherSorted };
});
const showGroupHeaders = computed(()=> (ui.query||'').trim().length > 0);

// 收藏视图
const favTasksView = computed(()=>{
  const map = new Map(allTasks.value.map(t => [t.__key, t]));
  const list = [...favSet.value.values()].map(k => map.get(k)).filter(Boolean);
  return list
      .sort((a,b)=> a.title.localeCompare(b.title) || a.plan.localeCompare(b.plan) || a.task.localeCompare(b.task))
      .map(t => ({...t, titleHtml: highlight(t.title), descHtml: highlight(t.desc)}));
});

// 初始化
onMounted(async ()=>{
  await loadPlans();
  if (!ui.planSelected && plans.value.length) ui.planSelected = plans.value[0].name;
  await loadAllTasks();

  // 快捷键：/ 聚焦搜索
  window.addEventListener('keydown', onGlobalKey);
});
function onGlobalKey(e){
  if (e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey) { e.preventDefault(); focusSearch(); }
}

// 参数配置（仅添加时）
const cfg = reactive({ open:false, plan:'', task:'', title:'Configure Task', meta:null, inputsRaw:'{}', jsonError:'', priority:null, note:'' });
function openConfig(plan, task, meta){
  cfg.open = true; cfg.plan = plan; cfg.task = task; cfg.meta = meta || {};
  cfg.title = `Configure • ${task}`;
  if (hasSchema.value) {
    formModelReset();
    const def = cfg.meta?.defaults || {};
    for (const f of schemaFields.value) formModel[f.key] = def[f.key] ?? (f.type==='boolean'?false: (f.type==='number'?0:''));
  } else {
    const def = cfg.meta?.defaults || {};
    cfg.inputsRaw = JSON.stringify(def || {}, null, 2); cfg.jsonError = '';
  }
  cfg.priority = null; cfg.note = '';
}
const hasSchema = computed(()=> !!cfg.meta?.inputs_schema);
const formModel = reactive({});
function formModelReset(){ Object.keys(formModel).forEach(k => delete formModel[k]); }
const schemaFields = computed(()=>{
  const sch = cfg.meta?.inputs_schema;
  if (!sch || typeof sch !== 'object') return [];
  const props = sch.properties || {};
  const order = sch.uiOrder || Object.keys(props);
  return order.map(k => {
    const p = props[k] || {};
    if (Array.isArray(p.enum)) return { key:k, label:p.title || k, type:'enum', enum:p.enum, help:p.description || '' };
    if (p.type === 'boolean') return { key:k, label:p.title || k, type:'boolean', onLabel:p.onLabel || 'Enabled', help:p.description || '' };
    if (p.type === 'number' || p.type === 'integer') return { key:k, label:p.title || k, type:'number', help:p.description || '' };
    return { key:k, label:p.title || k, type:'string', placeholder:p.examples?.[0] || '', help:p.description || '' };
  });
});
watch(() => cfg.inputsRaw, v => {
  if (hasSchema.value) return;
  try { JSON.parse(v || '{}'); cfg.jsonError=''; } catch(e){ cfg.jsonError = 'Invalid JSON: ' + e.message; }
});
const canAdd = computed(()=> hasSchema.value ? true : !cfg.jsonError);
function buildInputs(){
  if (hasSchema.value) { const out={}; for (const f of schemaFields.value) out[f.key]=formModel[f.key]; return out; }
  try { return JSON.parse(cfg.inputsRaw || '{}'); } catch { return {}; }
}

// 本地队列
const staging = useStagingQueue();
const stagingList = computed(() => Array.isArray(staging.items?.value) ? staging.items.value : []);
const historyList = computed(() => Array.isArray(staging.history?.value) ? staging.history.value : []);
function confirmAdd(){
  const inputs = buildInputs();
  staging.addTask({ plan_name: cfg.plan, task_name: cfg.task, inputs, priority: cfg.priority ?? null, note: cfg.note || '' });
  toast({ type:'success', title:'Added to queue', message:`${cfg.plan} / ${cfg.task}` });
  cfg.open = false;
}

// 队列：展开/折叠 & 操作
const expanded = ref(new Set());
function toggleRow(id){ const s = new Set(expanded.value); s.has(id) ? s.delete(id) : s.add(id); expanded.value = s; }
function expandAll(v){ expanded.value = v ? new Set(stagingList.value.map(x => x.id)) : new Set(); }
function moveUp(it){ staging.move(it.id,-1); }
function moveDown(it){ staging.move(it.id,+1); }
function remove(it){ staging.removeTask(it.id); }
function clearAll(){ staging.clear(); }

// —— 拖拽排序（用现有 move 循环实现） —— //
const dragId = ref(null);
const dragOverId = ref(null);
function onDragStart(id, ev){ dragId.value = id; ev.dataTransfer?.setData('text/plain', String(id)); ev.dataTransfer?.setDragImage?.(new Image(), 0, 0); }
function onDragOver(id){ dragOverId.value = id; }
function onDragLeave(id){ if (dragOverId.value === id) dragOverId.value = null; }
function onDrop(targetId){
  const fromId = dragId.value; const toId = targetId;
  dragOverId.value = null; dragId.value = null;
  if (!fromId || !toId || fromId === toId) return;
  const list = stagingList.value;
  const from = list.findIndex(x => x.id === fromId);
  const to   = list.findIndex(x => x.id === toId);
  if (from < 0 || to < 0) return;

  // 用 move(id, delta) 循环到位（避免改动 composable）
  const dir = to > from ? +1 : -1;
  let cur = from;
  while (cur !== to) {
    staging.move(list[cur].id, dir);
    cur += dir;
  }
}
function onDragEnd(){ dragId.value = null; dragOverId.value = null; }

// Completed
const qHist = ref('');
const filteredHistory = computed(() => {
  const q = qHist.value.trim().toLowerCase();
  if (!q) return historyList.value;
  return historyList.value.filter(h => (`${h.plan_name} ${h.task_name} ${JSON.stringify(h.inputs||{})}`).toLowerCase().includes(q));
});
function requeue(h){
  staging.addTask({ plan_name:h.plan_name, task_name:h.task_name, inputs:h.inputs, priority:h.priority, note:h.note });
  toast({type:'success', title:'Requeued', message:`${h.plan_name} / ${h.task_name}`});
}
function clearHistory(){ staging.clearHistory(); }

// 通用
function previewInputs(obj){ try{ const s = JSON.stringify(obj||{}); return s.length>80 ? s.slice(0,80)+'…' : s; }catch{return '{}';} }
function pretty(o){ try{ return JSON.stringify(o, null, 2);} catch{ return String(o);} }
function safeUpper(s){ const t=(s==null?'':String(s)); return t ? t.toUpperCase() : '—'; }
function statusPill(s){ const v=(s||'pending').toLowerCase(); if(v==='running')return'pill-blue'; if(v==='dispatched'||v==='dispatching')return'pill-blue'; if(v==='success')return'pill-green'; if(v==='error')return'pill-red'; return'pill-gray'; }
function fmt(ts){ if(!ts) return '—'; const ms=ts>1e12?ts:Math.floor(ts*1000); const d=new Date(ms); const pad=n=>String(n).padStart(2,'0'); return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`; }
</script>

<style scoped>
.toolbar{ display:flex; gap:8px; align-items:center; }
.hint{ color:var(--text-3); font-size:12px; }
.hint kbd{ background:#eef2ff; padding:0 6px; border-radius:6px; }

.grid{ display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:10px; }
.grid-header{
  grid-column: 1 / -1;
  font-size:12px; color:var(--text-3);
  padding:4px 6px; background:#F9FAFB; border:1px dashed var(--border);
  border-radius:8px; margin-top:2px;
}
.empty{ color:var(--text-3); font-size:12px; padding:8px; grid-column:1 / -1; }

/* 队列拖拽 */
.drag-handle{
  width:24px; height:24px; border:none; background:transparent;
  cursor:grab; line-height:24px; text-align:center; border-radius:6px;
}
.drag-handle:active{ cursor:grabbing; }
.row-draggable{ transition: background-color .12s ease; }
.row-drop-target{ background: #FFF7ED; } /* 放置高亮（浅橙） */

/* 动画：卡片淡入 */
.fade-enter-active, .fade-leave-active{ transition: all .18s ease; }
.fade-enter-from, .fade-leave-to{ opacity: 0; transform: translateY(4px); }

/* 动画：详情展开 */
.expand-enter-active, .expand-leave-active{ transition: all .18s ease; }
.expand-enter-from, .expand-leave-to{ opacity: 0; transform: translateY(-4px); }

.detail{ display:grid; gap:10px; }
.kv{ display:grid; grid-template-columns: 120px 1fr; gap:10px; }
.json{ background:#0b102126; border-radius:10px; padding:10px; overflow:auto; }
.chk{ font-size:12px; color: var(--text-3); display:flex; gap:6px; align-items:center; }

/* mark 高亮（与卡片内一致） */
:deep(mark){
  background: #FFF4CC;
  padding: 0 2px;
  border-radius: 3px;
}
</style>

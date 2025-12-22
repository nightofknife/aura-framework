<template>
  <div class="execute-view">
    <div class="header-bar">
      <div>
      <strong class="view-title">执行台</strong>
      <div class="view-subtitle">选择任务 → 配置输入 → 前端排队 → 推送后端 → 运行/观察</div>
      </div>
      <div class="toolbar">
        <span class="pill" :class="engineRunning ? 'pill-blue' : ''">
          {{ engineRunning ? '运行中' : '未启动' }}
        </span>
        <span class="pill pill-green">后端队列</span>
      </div>
    </div>

    <!-- 任务浏览 -->
    <!-- 任务选择 -->
    <div class="content-grid">
      <SchemePanel v-model:open="open.byPlan" title="按计划" description="按 Plan 浏览可用任务">
        <div class="controls">
          <select class="select" v-model="ui.planSelected">
            <option disabled value="">选择 Plan…</option>
            <option v-for="p in plans" :key="p.name" :value="p.name">{{ p.name }}</option>
          </select>
          <input class="input" v-model="ui.query" placeholder="搜索任务…" />
        </div>
        <TransitionGroup name="fade" tag="div" class="task-grid">
          <TaskMiniCard
            v-for="t in filteredTasks" :key="t.__key" v-bind="t"
            @select="openConfig(t.plan, t.task, t.meta)" @toggle-fav="toggleFav(t.plan, t.task)"
          />
          <div v-if="!filteredTasks.length" key="empty" class="empty-state">暂无匹配任务</div>
        </TransitionGroup>
      </SchemePanel>

      <SchemePanel v-model:open="open.favs" title="收藏" description="快速访问常用任务">
        <TransitionGroup name="fade" tag="div" class="task-grid">
          <TaskMiniCard
            v-for="t in favTasksView" :key="t.__key" v-bind="t"
            @select="openConfig(t.plan, t.task, t.meta)" @toggle-fav="toggleFav(t.plan, t.task)"
          />
          <div v-if="!favTasksView.length" key="emptyfav" class="empty-state">还没有收藏任务</div>
        </TransitionGroup>
      </SchemePanel>
    </div>

    <!-- 队列区域 -->
    <div class="queue-grid">
      <!-- 左：GUI 队列 -->
      <div class="panel glass glass-thick">
        <div class="panel-header">
          <strong>GUI 队列（本地待推送）</strong>
          <div class="controls">
            <button class="btn btn-primary" @click="pushAllGui" :disabled="!guiItems.length">推送前端队列</button>
            <button class="btn btn-ghost" @click="clearGuiQueue">清空</button>
          </div>
        </div>
        <div class="panel-body table-wrap">
          <table>
            <thead>
            <tr>
              <th>#</th>
              <th>方案 / 任务</th>
              <th>重复</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
            </thead>
            <tbody>
            <tr v-for="(it, idx) in guiItems" :key="it.id">
              <td>{{ idx + 1 }}</td>
              <td><strong>{{ it.plan }}</strong> / {{ it.task }}</td>
              <td>{{ it.repeat || 1 }}</td>
              <td>
                <span class="pill" :class="guiStatusClass(it.status)">{{ guiStatusLabel(it.status) }}</span>
              </td>
              <td>
                <button class="btn btn-ghost" @click="pushToBackend(it)" :disabled="it.status==='pushing'">推送</button>
                <button class="btn btn-ghost" @click="moveGui(it.id, 'up')">↑</button>
                <button class="btn btn-ghost" @click="moveGui(it.id, 'down')">↓</button>
                <button class="btn btn-ghost" @click="removeGui(it.id)">Del</button>
              </td>
            </tr>
            <tr v-if="!guiItems.length">
              <td colspan="5" class="empty-state">前端队列为空</td>
            </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 右：后端队列 -->
      <div class="panel glass glass-thick">
        <div class="panel-header">
          <strong>后端队列 ({{ readyQueue.length + activeRuns.length }})</strong>
          <div class="controls">
            <button class="btn btn-ghost" @click="refreshQueue">刷新</button>
            <button class="btn btn-ghost" @click="clearQueue">清空</button>
          </div>
        </div>
        <div class="panel-body table-wrap">
          <table>
            <thead>
            <tr>
              <th>类型</th>
              <th>标识/CID</th>
              <th>方案 / 任务</th>
              <th>优先级/状态</th>
              <th>时间</th>
              <th>操作</th>
            </tr>
            </thead>
            <tbody>
            <tr v-for="it in readyQueue" :key="it.trace_id || it.cid">
              <td>排队中</td>
              <td>
                <div v-if="it.trace_label" class="trace-label">{{ it.trace_label }}</div>
                <code>{{ it.trace_id || it.cid }}</code>
              </td>
              <td><strong>{{ it.plan_name }}</strong> / {{ it.task_name }}</td>
              <td>{{ it.priority ?? '-' }}</td>
              <td>{{ fmtTime(it.enqueued_at) }}</td>
              <td>
                <button class="btn btn-ghost" @click="moveFront(it.cid)">置顶</button>
                <button class="btn btn-ghost" @click="removeQueue(it.cid)">删除</button>
              </td>
            </tr>
            <tr v-for="run in activeRuns" :key="run.trace_id || run.cid || run.task_name">
              <td>运行中</td>
              <td>
                <div v-if="run.trace_label" class="trace-label">{{ run.trace_label }}</div>
                <code>{{ run.trace_id || run.cid || '-' }}</code>
              </td>
              <td><strong>{{ run.plan_name }}</strong> / {{ run.task_name }}</td>
              <td>{{ run.status || '运行中' }}</td>
              <td>{{ fmtTimeMs(run.started_at) }}</td>
              <td>--</td>
            </tr>
            <tr v-if="!readyQueue.length && !activeRuns.length">
              <td colspan="6" class="empty-state">队列为空</td>
            </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 底部：历史任务 -->
    <div class="panel glass glass-thick">
      <div class="panel-header">
        <strong>历史任务</strong>
      </div>
      <div class="panel-body table-wrap">
        <table>
          <thead>
          <tr>
            <th>方案 / 任务</th>
            <th>状态</th>
            <th>时间</th>
          </tr>
          </thead>
          <tbody>
          <tr v-for="hist in filteredHistory" :key="hist.id">
            <td><strong>{{ hist.plan }}</strong> / {{ hist.task }}</td>
            <td>{{ hist.status }}</td>
            <td>{{ fmtTimeMs(hist.at) }}</td>
          </tr>
          <tr v-if="!pushHistory.length">
            <td colspan="3" class="empty-state">暂无历史记录</td>
          </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 右侧配置抽屉 -->
    <ProContextPanel :open="cfg.open" :title="cfg.title" @close="cfg.open=false">
      <div style="color:var(--text-secondary); font-size:12px;">
        {{ cfg.plan }} / {{ cfg.task }}
      </div>

      <div v-if="hasSchema" class="form-grid">
        <div v-for="f in schemaFields" :key="f.key" class="field">
          <div class="label">{{ f.label }}</div>
          <select class="select" v-if="f.type==='enum'" v-model="formModel[f.key]">
            <option v-for="opt in f.enum" :key="opt" :value="opt">{{ opt }}</option>
          </select>
          <input class="input" v-else-if="f.type==='number'" type="number" v-model.number="formModel[f.key]" />
          <label class="chk" v-else-if="f.type==='boolean'">
            <input type="checkbox" v-model="formModel[f.key]"> {{ f.label }}
          </label>
          <input class="input" v-else v-model="formModel[f.key]" />
        </div>
      </div>

      <div v-else class="json-input">
        <div class="label">Inputs (JSON)</div>
        <textarea v-model="cfg.inputsRaw" class="textarea"></textarea>
        <div v-if="cfg.jsonError" class="error">{{ cfg.jsonError }}</div>
      </div>

      <div class="field">
        <div class="label">Repeat</div>
        <input class="input" type="number" min="1" max="500" v-model.number="cfg.repeat">
      </div>

      <div style="display:flex; gap:8px;">
        <button class="btn btn-primary" @click="addToGuiQueue" :disabled="!canAdd">加入前端队列</button>
        <button class="btn btn-ghost" @click="cfg.open=false">取消</button>
      </div>
    </ProContextPanel>
  </div>
</template>

<script setup>
import {computed, reactive, ref, onMounted, onUnmounted} from 'vue';
import axios from 'axios';
import { getGuiConfig } from '../config.js';
import SchemePanel from '../components/SchemePanel.vue';
import TaskMiniCard from '../components/TaskMiniCard.vue';
import ProContextPanel from '../components/ProContextPanel.vue';
import {useToasts} from '../composables/useToasts.js';
import {useBackendQueue} from '../composables/useBackendQueue.js';
import {useGuiQueue} from '../composables/useGuiQueue.js';

const {push: toast} = useToasts();
const guiConfig = getGuiConfig();
const api = axios.create({
  baseURL: guiConfig?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: guiConfig?.api?.timeout_ms || 5000,
});

const engineRunning = ref(false);
const plans = ref([]);
const allTasks = ref([]);
const ui = reactive({planSelected: '', query: ''});

const open = reactive({byPlan: true, favs: true});

// 收藏
const FAV_KEY = 'exec.favs';
const favSet = ref(new Set(JSON.parse(localStorage.getItem(FAV_KEY) || '[]')));
function toggleFav(plan, task) {
  const k = `${plan}::${task}`;
  const next = new Set(favSet.value);
  next.has(k) ? next.delete(k) : next.add(k);
  favSet.value = next;
  localStorage.setItem(FAV_KEY, JSON.stringify([...next]));
}
const favTasksView = computed(() => {
  const map = new Map(allTasks.value.map(t => [t.__key, t]));
  const list = [...favSet.value.values()].map(k => map.get(k)).filter(Boolean);
  return list
      .sort((a, b) => a.title.localeCompare(b.title) || a.plan.localeCompare(b.plan) || a.task.localeCompare(b.task))
      .map(t => ({...t, titleHtml: t.title, descHtml: t.desc, starred: true}));
});

// 任务过滤
const filteredTasks = computed(() => {
  const ps = ui.planSelected || (plans.value[0]?.name || '');
  const q = (ui.query || '').trim().toLowerCase();
  const match = (t) => !q || (t.plan + t.task + t.title + t.desc).toLowerCase().includes(q);
  const inPlan = allTasks.value.filter(t => t.plan === ps && match(t));
  const other = allTasks.value.filter(t => t.plan !== ps && match(t));
  const cmp = (a, b) => {
    const af = favSet.value.has(`${a.plan}::${a.task}`);
    const bf = favSet.value.has(`${b.plan}::${b.task}`);
    if (af !== bf) return af ? -1 : 1;
    const at = a.title.localeCompare(b.title);
    if (at) return at;
    const ap = a.plan.localeCompare(b.plan);
    if (ap) return ap;
    return a.task.localeCompare(b.task);
  };
  return [...inPlan, ...other].sort(cmp).map(t => ({
    ...t,
    starred: favSet.value.has(`${t.plan}::${t.task}`),
    titleHtml: t.title,
    descHtml: t.desc,
  }));
});

async function loadPlans() {
  try {
    const {data} = await api.get('/plans');
    plans.value = data || [];
  } catch (e) {
    toast({type: 'error', title: 'Load plans failed', message: e.message});
  }
}

async function loadAllTasks() {
  const result = [];
  for (const p of plans.value) {
    try {
      const {data} = await api.get(`/plans/${p.name}/tasks`);
      (data || []).forEach(t => {
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

// 配置面板
const cfg = reactive({
  open: false,
  plan: '',
  task: '',
  title: 'Configure Task',
  meta: null,
  inputsRaw: '{}',
  jsonError: '',
  repeat: 1,
});
const formModel = reactive({});
const hasSchema = computed(() => !!cfg.meta?.inputs_schema);
const schemaFields = computed(() => {
  if (!cfg.meta?.inputs_schema) return [];
  return Object.entries(cfg.meta.inputs_schema).map(([key, def]) => ({
    key,
    label: def.title || key,
    type: def.enum ? 'enum' : def.type || 'string',
    enum: def.enum || [],
  }));
});

function formModelReset() {
  Object.keys(formModel).forEach(k => delete formModel[k]);
}

function openConfig(plan, task, meta) {
  cfg.open = true;
  cfg.plan = plan;
  cfg.task = task;
  cfg.meta = meta || {};
  cfg.title = `Configure · ${task}`;
  cfg.repeat = 1;
  cfg.jsonError = '';
  cfg.inputsRaw = JSON.stringify(buildDefaultInputs(meta), null, 2);
  if (hasSchema.value) {
    formModelReset();
    const def = cfg.meta?.defaults || {};
    for (const f of schemaFields.value) formModel[f.key] = def[f.key] ?? (f.type === 'boolean' ? false : (f.type === 'number' ? 0 : ''));
  }
}

function buildDefaultInputs(meta) {
  // 优先使用 schema/defaults，其次使用 inputs 列表中的 default
  if (meta?.defaults && typeof meta.defaults === 'object') return meta.defaults;
  if (Array.isArray(meta?.inputs)) {
    const obj = {};
    meta.inputs.forEach(inp => {
      if (inp?.name) obj[inp.name] = inp.default ?? '';
    });
    return obj;
  }
  return {};
}

const canAdd = computed(() => !!cfg.plan && !!cfg.task);

function buildInputs() {
  if (hasSchema.value) {
    return {...formModel};
  }
  try {
    cfg.jsonError = '';
    return JSON.parse(cfg.inputsRaw || '{}');
  } catch (e) {
    cfg.jsonError = e.message;
    return null;
  }
}

// 后端队列操作
const {readyQueue, fetchReady, remove: removeQueueApi, moveFront: moveFrontApi, clear: clearQueueApi, activeRuns, fetchActiveRuns} = useBackendQueue();
const {items: guiItems, add: addGui, update: updateGui, remove: removeGuiItem, clear: clearGui, move: moveGuiItem} = useGuiQueue();

const pushHistory = ref([]);
let pollTimer = null;
let activeSnapshot = new Map();
const pendingFinish = new Map();
const FINAL_STATUS_MAP = new Map([
  ['success', 'success'],
  ['succeeded', 'success'],
  ['ok', 'success'],
  ['error', 'error'],
  ['failed', 'error'],
  ['fail', 'error'],
  ['timeout', 'error'],
  ['cancelled', 'cancelled'],
  ['canceled', 'cancelled'],
  ['aborted', 'cancelled'],
  ['skipped', 'skipped'],
]);
const TRANSIENT_STATUSES = new Set(['running', 'starting', 'queued', 'pending', 'pushing', 'unknown']);
const filteredHistory = computed(() => {
  const excluded = new Set(['已推送', 'queued', '运行中', 'starting', 'unknown']);
  return pushHistory.value.filter(h => {
    if (!h.plan || !h.task || !h.status) return false;
    const s = String(h.status).toLowerCase();
    return !excluded.has(h.status) && !excluded.has(s) && !s.includes('starting');
  });
});

async function refreshQueue() {
  await fetchReady();
}
async function refreshRuns() {
  const prev = new Map(activeSnapshot);
  await fetchActiveRuns();
  // Identify finished runs and move to history
  activeSnapshot = new Map();
  for (const run of activeRuns.value) {
    const key = run.trace_id || run.cid || `${run.plan_name}/${run.task_name}`;
    activeSnapshot.set(key, run);
    prev.delete(key);
  }
  // Remaining items in prev need final status confirmation
  prev.forEach((run, key) => {
    if (!pendingFinish.has(key)) pendingFinish.set(key, run);
  });
  await resolvePendingFinished();
}

function normalizeFinalStatus(status) {
  if (!status) return null;
  const s = String(status).toLowerCase();
  return FINAL_STATUS_MAP.get(s) || null;
}

function isTransientStatus(status) {
  if (!status) return true;
  const s = String(status).toLowerCase();
  return TRANSIENT_STATUSES.has(s);
}

function pushHistoryEntry(run, status, finishedAt) {
  const key = run.trace_id || run.cid || `${run.plan_name}/${run.task_name}`;
  pushHistory.value = [
    {
      id: `hist_${key}_${Date.now()}`,
      plan: run.plan_name,
      task: run.task_name,
      status,
      at: finishedAt || run.finished_at || Date.now(),
    },
    ...pushHistory.value
  ].slice(0, 100);
}

async function resolvePendingFinished() {
  if (!pendingFinish.size) return;
  const pending = [...pendingFinish.entries()];
  const cids = pending.map(([, run]) => run.cid).filter(Boolean);
  const statusByCid = new Map();

  if (cids.length) {
    try {
      const {data} = await api.post('/tasks/status/batch', {cids});
      for (const item of data?.tasks || []) {
        if (item?.cid) statusByCid.set(item.cid, item);
      }
    } catch (e) {
      console.warn('[Execute] batch status failed', e);
    }
  }

  for (const [key, run] of pending) {
    const info = run.cid ? statusByCid.get(run.cid) : null;
    const rawStatus = info?.status || run.status;
    const finalStatus = normalizeFinalStatus(rawStatus);
    if (finalStatus) {
      pushHistoryEntry({
        ...run,
        plan_name: info?.plan_name || run.plan_name,
        task_name: info?.task_name || run.task_name,
        finished_at: info?.finished_at || run.finished_at,
      }, finalStatus, info?.finished_at);
      pendingFinish.delete(key);
      console.log('[Execute] run finished -> history:', key, info || run);
      continue;
    }
    if (rawStatus && String(rawStatus).toLowerCase() == 'not_found') {
      pendingFinish.delete(key);
      continue;
    }
    if (isTransientStatus(rawStatus)) {
      continue;
    }
    if (rawStatus) {
      pushHistoryEntry(run, rawStatus, info?.finished_at);
      pendingFinish.delete(key);
      console.log('[Execute] run finished -> history:', key, info || run);
    }
  }
}

async function removeQueue(cid) {
  await removeQueueApi(cid);
  await fetchReady();
}
async function moveFront(cid) {
  await moveFrontApi(cid);
  await fetchReady();
}
async function clearQueue() {
  await clearQueueApi();
  await fetchReady();
}

function addToGuiQueue() {
  const inputs = buildInputs();
  if (inputs === null) return;
  const repeat = Math.max(1, Math.min(500, cfg.repeat || 1));
  for (let i = 0; i < repeat; i++) {
    addGui({
      plan: cfg.plan,
      task: cfg.task,
      inputs,
      repeat: 1,
    });
  }
  cfg.open = false;
  toast({type: 'success', title: '已加入前端队列', message: `${cfg.plan} / ${cfg.task} ×${repeat}`});
}

async function pushToBackend(item) {
  const inputs = item.inputs || {};
  updateGui(item.id, {status: 'pushing'});
  try {
    const repeat = Math.max(1, item.repeat || 1);
    let cid = null;
    console.log('[Execute] pushing item:', item, 'repeat:', repeat);
    if (repeat > 1) {
      const tasks = Array.from({length: repeat}, () => ({
        plan_name: item.plan,
        task_name: item.task,
        inputs,
      }));
      const {data} = await api.post('/tasks/batch', {tasks});
      if (Array.isArray(data?.results) && data.results.length) {
        cid = data.results[0]?.cid || null;
      }
    } else {
      const {data} = await api.post('/tasks/run', {plan_name: item.plan, task_name: item.task, inputs});
      cid = data?.cid || null;
    }
    updateGui(item.id, {status: 'queued', lastCid: cid, pushedAt: Date.now()});
    // 推送成功后从 GUI 队列移除
    removeGuiItem(item.id);
    toast({type: 'success', title: '已推送', message: `${item.plan} / ${item.task}`});
    await fetchReady();
    await refreshRuns();
    console.log('[Execute] push success, cid:', cid);
  } catch (e) {
    updateGui(item.id, {status: 'pending'});
    toast({type: 'error', title: 'Push failed', message: e?.response?.data?.detail || e.message});
    console.error('[Execute] push failed', e);
  }
}

function removeGui(id) {
  removeGuiItem(id);
}

function moveGui(id, dir) {
  moveGuiItem(id, dir);
}

function clearGuiQueue() {
  clearGui();
}

async function pushAllGui() {
  // 复制当前列表，逐个推送
  const list = [...guiItems.value];
  for (const it of list) {
    await pushToBackend(it);
  }
}

function fmtTime(ts) {
  if (!ts) return '-';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString();
}

function fmtTimeMs(ts) {
  if (!ts) return '-';
  const d = new Date(typeof ts === 'number' && ts > 1e12 ? ts : ts * 1000);
  return d.toLocaleString();
}

function guiStatusLabel(st) {
  return st === 'pending' ? '待推送' : st === 'pushing' ? '推送中' : st === 'queued' ? '已推送' : st;
}
function guiStatusClass(st) {
  return st === 'queued' ? 'pill-green' : st === 'pushing' ? 'pill-blue' : '';
}

onMounted(async () => {
  await loadPlans();
  if (!ui.planSelected && plans.value.length) ui.planSelected = plans.value[0].name;
  await loadAllTasks();
  await fetchReady();
  await refreshRuns();
  try {
    const {data} = await api.get('/system/status');
    engineRunning.value = !!data?.is_running;
  } catch {}
  pollTimer = setInterval(async () => {
    await fetchReady();
    await refreshRuns();
  }, 2000);
});

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});
</script>

<style scoped>
.execute-view{display:flex;flex-direction:column;gap:16px;}
.header-bar{display:flex;justify-content:space-between;align-items:center;}
.view-title{font-size:22px;}
.view-subtitle{color:var(--text-3);font-size:12px;}
.toolbar{display:flex;gap:8px;align-items:center;}
.pill{padding:4px 10px;border-radius:999px;background:#eee;color:#555;font-size:12px;}
.pill-blue{background:#e0f2ff;color:#0369a1;}
.pill-green{background:#e0ffe8;color:#0f9d58;}
.content-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
.task-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin-top:10px;}
.empty-state{color:#999;text-align:center;padding:16px;}
.queue-panel table{width:100%;border-collapse:collapse;}
.queue-panel th,.queue-panel td{padding:8px;border-bottom:1px solid #eee;text-align:left;}
.queue-panel code{font-family:ui-monospace,Menlo,monospace;font-size:12px;}
.trace-label{font-size:11px;color:var(--text-3);line-height:1.2;}
.json-input .textarea{width:100%;height:160px;}
.form-grid{display:grid;grid-template-columns:1fr;gap:12px;margin:12px 0;}
.field .label{font-size:12px;color:var(--text-3);margin-bottom:4px;}
.error{color:#c00;font-size:12px;}
</style>

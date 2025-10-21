<template>
  <div class="execute-view">
    <div class="header-bar">
      <div>
        <strong class="view-title">Execute</strong>
        <div class="view-subtitle">添加任务 → 排队 → 运行/暂停 → 观察</div>
      </div>
      <div class="toolbar">
        <button
            class="btn btn-primary hold-btn"
            @mousedown="onHoldStart('run')" @mouseup="onHoldEnd('run')"
            :style="{ '--prog': (hold.run/100).toFixed(2) }"
        >
          ▶ Run
        </button>

        <button
            class="btn btn-ghost hold-btn"
            @mousedown="onHoldStart('pause')" @mouseup="onHoldEnd('pause')"
            :style="{ '--prog': (hold.pause/100).toFixed(2) }"
        >
          ⏸ Pause
        </button>

        <span v-if="running" class="pill pill-blue">DISPATCHING…</span>
        <span v-else class="pill">IDLE</span>
        <span v-if="autoMode" class="pill pill-green">AUTO</span>
      </div>
    </div>

    <div class="content-grid">
      <SchemePanel v-reveal v-model:open="open.byPlan" title="按计划（含搜索）"
                   description="优先展示当前 Plan 的匹配任务">
        <div class="controls">
          <select class="select" v-model="ui.planSelected">
            <option disabled value="">选择 Plan…</option>
            <option v-for="p in plans" :key="p.name" :value="p.name">{{ p.name }}</option>
          </select>
          <input ref="searchEl" class="input" v-model="ui.query" placeholder="搜索任务…" @keydown.stop/>
        </div>
        <TransitionGroup name="fade" tag="div" class="task-grid">
          <div v-if="showGroupHeaders" key="grp-in" class="grid-header">当前 Plan</div>
          <TaskMiniCard
              v-for="t in grouped.inPlan" :key="t.__key" v-bind="t"
              @select="openConfig(t.plan, t.task, t.meta)" @toggle-fav="toggleFav(t.plan, t.task)"
          />
          <div v-if="showGroupHeaders && grouped.other.length" key="grp-out" class="grid-header">其他 Plan</div>
          <TaskMiniCard
              v-for="t in grouped.other" :key="t.__key" v-bind="t"
              @select="openConfig(t.plan, t.task, t.meta)" @toggle-fav="toggleFav(t.plan, t.task)"
          />
          <div v-if="!grouped.inPlan.length && !grouped.other.length" key="empty" class="empty-state">暂无匹配结果。
          </div>
        </TransitionGroup>
      </SchemePanel>

      <SchemePanel v-reveal v-model:open="open.favs" title="收藏" description="常用任务快速进入">
        <TransitionGroup name="fade" tag="div" class="task-grid">
          <TaskMiniCard
              v-for="t in favTasksView" :key="t.__key" v-bind="t"
              @select="openConfig(t.plan, t.task, t.meta)" @toggle-fav="toggleFav(t.plan, t.task)"
          />
          <div v-if="!favTasksView.length" key="emptyfav" class="empty-state">还没有收藏任务。</div>
        </TransitionGroup>
      </SchemePanel>
    </div>

    <!-- 队列面板：接入拟物玻璃 -->
    <div class="panel queue-panel glass glass-thick glass-refract glass-shimmer">
      <div class="panel-header">
        <strong>Staging ({{ stagingList.length }})</strong>
        <div class="controls">
          <button class="btn btn-ghost" @click="expandAll(true)">Expand</button>
          <button class="btn btn-ghost" @click="expandAll(false)">Collapse</button>
          <button class="btn btn-ghost" @click="clearAll">Clear</button>
        </div>
      </div>
      <div class="panel-body table-wrap">
        <table>
          <thead>
          <tr>
            <th style="width:36px;"></th>
            <th style="width:26px;"></th>
            <th>Plan / Task</th>
            <th>Inputs</th>
            <th>Repeat</th> <!-- ✅ 改为 Repeat -->
            <th>Status</th>
            <th>Actions</th>
          </tr>
          </thead>
          <tbody>
          <template v-for="it in stagingList" :key="it.id">
            <tr :class="{ 'row-drop-target': dragOverId === it.id }" @dragover.prevent="onDragOver(it.id)"
                @drop.prevent="onDrop(it.id)" @dragleave="onDragLeave(it.id)">
              <td>
                <button class="btn btn-ghost" @click="toggleRow(it.id)">{{ expanded.has(it.id) ? '▾' : '▸' }}</button>
              </td>
              <td>
                <button class="drag-handle" draggable="true" @dragstart="onDragStart(it.id, $event)">⠿</button>
              </td>
              <td><strong>{{ it.plan_name }}</strong> / {{ it.task_name }}</td>
              <td><code>{{ previewInputs(it.inputs) }}</code></td>
              <td>
                <!-- ✅ 显示重复次数，支持就地编辑 -->
                <input
                    class="repeat-input"
                    type="number"
                    v-model.number="it.repeat"
                    min="1"
                    max="500"
                    @change="updateTask(it.id, { repeat: it.repeat })"
                >
              </td>
              <td><span class="pill" :class="statusPill(it.status)">{{ safeUpper(it.status || 'pending') }}</span></td>
              <td>
                <button class="btn btn-ghost" @click="remove(it)">Del</button>
              </td>
            </tr>
            <Transition name="expand">
              <tr v-if="expanded.has(it.id)">
                <td colspan="7">
                  <pre class="json">{{ pretty(it.inputs) }}</pre>
                </td>
              </tr>
            </Transition>
          </template>
          <tr v-if="!stagingList.length">
            <td colspan="7" class="empty-state">队列为空。</td>
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
          <input class="input" v-else-if="f.type==='string'" v-model="formModel[f.key]"
                 :placeholder="f.placeholder || ''">
          <input class="input" v-else-if="f.type==='number'" type="number" v-model.number="formModel[f.key]">
          <label v-else-if="f.type==='boolean'" class="chk">
            <input type="checkbox" v-model="formModel[f.key]"> {{ f.onLabel || 'Enabled' }}
          </label>
          <div v-if="f.help" class="help">{{ f.help }}</div>
        </div>
      </div>

      <div v-else class="field">
        <div class="label">Inputs (JSON)</div>
        <textarea class="input" v-model="cfg.inputsRaw" rows="10"
                  style="width:100%; font-family: ui-monospace, Menlo, monospace;"></textarea>
        <div v-if="cfg.jsonError" class="error">{{ cfg.jsonError }}</div>
      </div>

      <!-- ✅ 新增：重复执行配置 -->
      <details class="adv" open>
        <summary><b>Repeat Execution</b></summary>
        <div class="adv-grid">
          <div class="field">
            <div class="label">Repeat Count</div>
            <input
                class="input"
                v-model.number="cfg.repeat"
                type="number"
                min="1"
                max="500"
                placeholder="1"
            >
            <div class="help">Execute this task N times (1-500)</div>
          </div>
        </div>
      </details>

      <details class="adv">
        <summary><b>Advanced</b> (note only)</summary>
        <div class="adv-grid">
          <div class="field">
            <div class="label">Note</div>
            <input class="input" v-model="cfg.note" placeholder="Optional note">
          </div>
        </div>
      </details>

      <div style="display:flex; gap:8px;">
        <button class="btn btn-primary" @click="confirmAdd" :disabled="!canAdd">Add to Queue</button>
        <button class="btn btn-ghost" @click="cfg.open=false">Cancel</button>
      </div>
    </ProContextPanel>
  </div>
</template>

<script setup>
import {computed, reactive, ref, onMounted, watch, onUnmounted} from 'vue';
import axios from 'axios';
import SchemePanel from '../components/SchemePanel.vue';
import TaskMiniCard from '../components/TaskMiniCard.vue';
import ProContextPanel from '../components/ProContextPanel.vue';
import {useStagingQueue} from '../composables/useStagingQueue.js';
import {useStagingRunner} from '../composables/useStagingRunner.js';
import {useToasts} from '../composables/useToasts.js';

onMounted(() => window.addEventListener('keydown', onGlobalKey))
onUnmounted(() => window.removeEventListener('keydown', onGlobalKey))

const {push: toast} = useToasts();
const api = axios.create({baseURL: 'http://127.0.0.1:18098/api', timeout: 5000});

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

    if (p >= 100) {
      clearInterval(hold._timer);

      if (target === 'run') {
        const next = !autoMode.value;
        setAuto(next);
        if (next) {
          if (!running.value && stagingList.value.length > 0) {
            startBatch();
          }
        }
      } else {
        forceStop();
      }
    }
  }, 16);
}

function onHoldEnd(target) {
  clearInterval(hold._timer);
  const p = target === 'run' ? hold.run : hold.pause;

  if (target === 'run') {
    if (p < 100) {
      const wasAuto = autoMode.value;
      if (!wasAuto) setAuto(true);

      startBatch();

      // ✅ 修改：只在队列完全清空且没有任务在派发时才还原
      if (!wasAuto) {
        const stopWatch = watch(
            [stagingList, running],
            ([list, run]) => {
              // ✅ 检查：队列为空 且 没有任务在运行
              const allPending = list.every(it => it.status === 'pending');
              const isEmpty = list.length === 0;

              if (isEmpty && !run) {
                setAuto(wasAuto);
                stopWatch();
              }
            }
        );
      }
    }
  } else {
    if (p < 100) pause();
  }

  hold.run = 0;
  hold.pause = 0;
}


// Plans & Tasks
const plans = ref([]);
const allTasks = ref([]);

async function loadPlans() {
  try {
    const {data} = await api.get('/plans');
    plans.value = data || [];
  } catch {
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
    } catch {
    }
  }
  allTasks.value = result;
}

const open = reactive({byPlan: true, favs: false});
const ui = reactive({planSelected: '', query: ''});

const searchEl = ref(null);

function focusSearch() {
  searchEl.value?.focus?.();
}

function escHtml(s = '') {
  return s.replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

function highlight(s) {
  const q = (ui.query || '').trim();
  if (!q) return escHtml(String(s || ''));
  const rx = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'ig');
  return escHtml(String(s || '')).replace(rx, '<mark>$1</mark>');
}

const FAV_KEY = 'exec.favs';
const favSet = ref(new Set(JSON.parse(localStorage.getItem(FAV_KEY) || '[]')));

function isFav(plan, task) {
  return favSet.value.has(`${plan}::${task}`);
}

function toggleFav(plan, task) {
  const k = `${plan}::${task}`;
  const next = new Set(favSet.value);
  next.has(k) ? next.delete(k) : next.add(k);
  favSet.value = next;
  localStorage.setItem(FAV_KEY, JSON.stringify([...next]));
}

const grouped = computed(() => {
  const ps = ui.planSelected || (plans.value[0]?.name || '');
  const q = (ui.query || '').trim().toLowerCase();
  const match = (t) => !q || (t.plan + t.task + t.title + t.desc).toLowerCase().includes(q);

  const inPlan = allTasks.value.filter(t => t.plan === ps && match(t));
  const other = allTasks.value.filter(t => t.plan !== ps && match(t));

  const cmp = (a, b) => {
    const af = isFav(a.plan, a.task), bf = isFav(b.plan, b.task);
    if (af !== bf) return af ? -1 : 1;
    const at = a.title.localeCompare(b.title);
    if (at) return at;
    const ap = a.plan.localeCompare(b.plan);
    if (ap) return ap;
    return a.task.localeCompare(b.task);
  };
  const deco = arr => arr.map(t => ({
    ...t,
    titleHtml: highlight(t.title),
    descHtml: highlight(t.desc),
    starred: isFav(t.plan, t.task)
  }));
  return {inPlan: deco([...inPlan].sort(cmp)), other: deco([...other].sort(cmp))};
});
const showGroupHeaders = computed(() => (ui.query || '').trim().length > 0);

const favTasksView = computed(() => {
  const map = new Map(allTasks.value.map(t => [t.__key, t]));
  const list = [...favSet.value.values()].map(k => map.get(k)).filter(Boolean);
  return list
      .sort((a, b) => a.title.localeCompare(b.title) || a.plan.localeCompare(b.plan) || a.task.localeCompare(b.task))
      .map(t => ({...t, titleHtml: highlight(t.title), descHtml: highlight(t.desc), starred: true}));
});

onMounted(async () => {
  await loadPlans();
  if (!ui.planSelected && plans.value.length) ui.planSelected = plans.value[0].name;
  await loadAllTasks();
  window.addEventListener('keydown', onGlobalKey);
});

function onGlobalKey(e) {
  if (e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey) {
    e.preventDefault();
    focusSearch();
  }
}

// 参数配置
const cfg = reactive({
  open: false,
  plan: '',
  task: '',
  title: 'Configure Task',
  meta: null,
  inputsRaw: '{}',
  jsonError: '',
  priority: null,
  note: '',
  repeat: 1, // ✅ 新增
});

function openConfig(plan, task, meta) {
  cfg.open = true;
  cfg.plan = plan;
  cfg.task = task;
  cfg.meta = meta || {};
  cfg.title = `Configure • ${task}`;
  if (hasSchema.value) {
    formModelReset();
    const def = cfg.meta?.defaults || {};
    for (const f of schemaFields.value) formModel[f.key] = def[f.key] ?? (f.type === 'boolean' ? false : (f.type === 'number' ? 0 : ''));
  } else {
    const def = cfg.meta?.defaults || {};
    cfg.inputsRaw = JSON.stringify(def || {}, null, 2);
    cfg.jsonError = '';
  }
  cfg.priority = null;
  cfg.note = '';
  cfg.repeat = 1; // ✅ 重置为 1
}

const hasSchema = computed(() => !!cfg.meta?.inputs_schema);
const formModel = reactive({});

function formModelReset() {
  Object.keys(formModel).forEach(k => delete formModel[k]);
}

const schemaFields = computed(() => {
  const sch = cfg.meta?.inputs_schema;
  if (!sch || typeof sch !== 'object') return [];
  const props = sch.properties || {};
  const order = sch.uiOrder || Object.keys(props);
  return order.map(k => {
    const p = props[k] || {};
    if (Array.isArray(p.enum)) return {
      key: k,
      label: p.title || k,
      type: 'enum',
      enum: p.enum,
      help: p.description || ''
    };
    if (p.type === 'boolean') return {
      key: k,
      label: p.title || k,
      type: 'boolean',
      onLabel: p.onLabel || 'Enabled',
      help: p.description || ''
    };
    if (p.type === 'number' || p.type === 'integer') return {
      key: k,
      label: p.title || k,
      type: 'number',
      help: p.description || ''
    };
    return {key: k, label: p.title || k, type: 'string', placeholder: p.examples?.[0] || '', help: p.description || ''};
  });
});
watch(() => cfg.inputsRaw, v => {
  if (hasSchema.value) return;
  try {
    JSON.parse(v || '{}');
    cfg.jsonError = '';
  } catch (e) {
    cfg.jsonError = 'Invalid JSON: ' + e.message;
  }
});
const canAdd = computed(() => hasSchema.value ? true : !cfg.jsonError);

function buildInputs() {
  if (hasSchema.value) {
    const out = {};
    for (const f of schemaFields.value) out[f.key] = formModel[f.key];
    return out;
  }
  try {
    return JSON.parse(cfg.inputsRaw || '{}');
  } catch {
    return {};
  }
}

// 本地队列
const staging = useStagingQueue();
const stagingList = computed(() => Array.isArray(staging.items?.value) ? staging.items.value : []);
const {updateTask} = staging;

function confirmAdd() {
  const inputs = buildInputs();
  staging.addTask({
    plan_name: cfg.plan,
    task_name: cfg.task,
    inputs,
    priority: cfg.priority ?? null,
    note: cfg.note || '',
    repeat: Math.max(1, Math.min(500, cfg.repeat || 1)), // ✅ 添加重复次数
  });
  toast({
    type: 'success',
    title: 'Added to queue',
    message: `${cfg.plan} / ${cfg.task} ${cfg.repeat > 1 ? `(×${cfg.repeat})` : ''}`
  });
  cfg.open = false;
}

// 队列：展开/折叠 & 操作
const expanded = ref(new Set());

function toggleRow(id) {
  const s = new Set(expanded.value);
  s.has(id) ? s.delete(id) : s.add(id);
  expanded.value = s;
}

function expandAll(v) {
  expanded.value = v ? new Set(stagingList.value.map(x => x.id)) : new Set();
}

function remove(it) {
  staging.removeTask(it.id);
}

function clearAll() {
  staging.clear();
}

// 拖拽排序
const dragId = ref(null);
const dragOverId = ref(null);

function onDragStart(id, ev) {
  dragId.value = id;
  ev.dataTransfer?.setData('text/plain', String(id));
  ev.dataTransfer?.setDragImage?.(new Image(), 0, 0);
}

function onDragOver(id) {
  dragOverId.value = id;
}

function onDragLeave(id) {
  if (dragOverId.value === id) dragOverId.value = null;
}

function onDrop(targetId) {
  const fromId = dragId.value;
  const toId = targetId;
  dragOverId.value = null;
  dragId.value = null;
  if (!fromId || !toId || fromId === toId) return;
  const list = stagingList.value;
  const from = list.findIndex(x => x.id === fromId);
  const to = list.findIndex(x => x.id === toId);
  if (from < 0 || to < 0) return;
  const dir = to > from ? +1 : -1;
  let cur = from;
  while (cur !== to) {
    staging.move(list[cur].id, dir);
    cur += dir;
  }
}

// 通用
function previewInputs(obj) {
  try {
    const s = JSON.stringify(obj || {});
    return s.length > 80 ? s.slice(0, 80) + '…' : s;
  } catch {
    return '{}';
  }
}

function pretty(o) {
  try {
    return JSON.stringify(o, null, 2);
  } catch {
    return String(o);
  }
}

function safeUpper(s) {
  const t = (s == null ? '' : String(s));
  return t ? t.toUpperCase() : '—';
}

function statusPill(s) {
  const v = (s || 'pending').toLowerCase();
  if (v === 'running') return 'pill-blue';
  if (v === 'dispatched' || v === 'dispatching') return 'pill-blue';
  if (v === 'success') return 'pill-green';
  if (v === 'error') return 'pill-red';
  return 'pill-gray';
}
</script>

<style scoped>
.execute-view {
  width: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.header-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-frosted);
}

.view-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}

.view-subtitle {
  color: var(--text-secondary);
}

.toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
}

.content-grid {
  width: 100%;
  min-width: 0;
  display: grid;
  gap: 24px;
  grid-template-columns: repeat(auto-fit, minmax(450px, 1fr));
}

.controls {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 16px;
}

.controls .input {
  flex: 1 1 auto;
  min-width: 0;
}

.task-grid {
  width: 100%;
  min-width: 0;
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
}

.grid-header {
  grid-column: 1 / -1;
  font-size: 12px;
  color: var(--text-secondary);
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  border: 1px dashed var(--border-frosted);
  background: color-mix(in oklab, var(--primary-accent) 5%, transparent);
}

.empty-state {
  color: var(--text-secondary);
  padding: 16px;
  text-align: center;
  grid-column: 1 / -1;
}

.queue-panel {
  margin-top: 8px;
}

.drag-handle {
  cursor: grab;
  color: var(--text-tertiary);
}

.row-drop-target {
  background: color-mix(in oklab, var(--primary-accent) 10%, transparent);
}

/* ✅ 新增：重复次数输入框样式 */
.repeat-input {
  width: 60px;
  padding: 4px 8px;
  border: 1px solid var(--border-frosted);
  border-radius: 4px;
  background: var(--bg-input);
  color: var(--text-primary);
  text-align: center;
  font-size: 13px;
  transition: all 0.2s;
}

.repeat-input:hover {
  border-color: var(--primary-accent);
}

.repeat-input:focus {
  outline: none;
  border-color: var(--primary-accent);
  box-shadow: 0 0 0 2px rgba(88, 101, 242, 0.1);
}

.repeat-input::-webkit-inner-spin-button,
.repeat-input::-webkit-outer-spin-button {
  opacity: 1;
}

.fade-enter-active, .fade-leave-active {
  transition: all var(--dur) var(--ease);
}

.fade-enter-from, .fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

.expand-enter-active, .expand-leave-active {
  transition: all var(--dur) var(--ease);
}

.expand-enter-from, .expand-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>

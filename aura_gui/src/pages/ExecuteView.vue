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

    <div class="content-grid">
      <SchemePanel v-model:open="open.byPlan" title="按计划" description="按 Plan 浏览可用任务">
        <div class="controls">
          <select class="select" v-model="ui.planSelected">
            <option disabled value="">选择 Plan</option>
            <option v-for="p in plans" :key="p.name" :value="p.name">{{ p.name }}</option>
          </select>
          <input class="input" v-model="ui.query" placeholder="搜索任务" />
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

    <div class="queue-grid">
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
          <tr v-for="it in historyView" :key="it.id">
            <td><strong>{{ it.plan }}</strong> / {{ it.task }}</td>
            <td>{{ it.status }}</td>
            <td>{{ fmtTimeMs(it.at) }}</td>
          </tr>
          <tr v-if="!history.length">
            <td colspan="3" class="empty-state">暂无历史记录</td>
          </tr>
          </tbody>
        </table>
      </div>
    </div>

    <ProContextPanel :open="config.open" :title="config.title" @close="config.open = false">
      <div style="color:var(--text-secondary); font-size:12px;">
        {{ config.plan }} / {{ config.task }}
      </div>
      <div v-if="hasInputs" class="form-grid">
        <InputFieldRenderer
          v-for="input in normalizedInputs"
          :key="input.name"
          :schema="input"
          v-model="inputModel[input.name]"
        />
      </div>
      <div v-else class="empty-state">This task requires no inputs.</div>
      <div class="field">
        <div class="label">Repeat</div>
        <input class="input" type="number" min="1" max="500" v-model.number="config.repeat" />
      </div>
      <div style="display:flex; gap:8px;">
        <button class="btn btn-primary" @click="addToGuiQueue" :disabled="!canAdd">
          加入前端队列
        </button>
        <button class="btn btn-ghost" @click="config.open = false">取消</button>
      </div>
    </ProContextPanel>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import axios from 'axios';
import { useDebounceFn } from '@vueuse/core';
import SchemePanel from '../components/SchemePanel.vue';
import TaskMiniCard from '../components/TaskMiniCard.vue';
import ProContextPanel from '../components/ProContextPanel.vue';
import InputFieldRenderer from '../components/InputFieldRenderer.vue';
import { useToasts } from '../composables/useToasts.js';
import { getGuiConfig } from '../config.js';
import { useBackendQueue } from '../composables/useBackendQueue.js';
import { useGuiQueue } from '../composables/useGuiQueue.js';
import { buildDefaultFromSchema, normalizeInputSchema } from '../utils/inputSchema.js';
import { parseTaskFile } from '../task_editor/convert/yamlCompiler.js';

const { push: toast } = useToasts();
const cfg = getGuiConfig();
const api = axios.create({
  baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: cfg?.api?.timeout_ms || 5000,
});

const engineRunning = ref(false);
const plans = ref([]);
const tasks = ref([]);
const ui = reactive({ planSelected: '', query: '' });
const debouncedQuery = ref(''); // 防抖后的查询字符串
const open = reactive({ byPlan: true, favs: true });
const favKey = 'exec.favs';
const favSet = ref(new Set(JSON.parse(localStorage.getItem(favKey) || '[]')));

// 防抖更新查询（300ms）
const updateDebouncedQuery = useDebounceFn((value) => {
  debouncedQuery.value = value;
}, 300);

// 监听 ui.query 变化并防抖更新
watch(() => ui.query, (newValue) => {
  updateDebouncedQuery(newValue);
}, { immediate: true });

function toggleFav(plan, task) {
  const key = `${plan}::${task}`;
  const next = new Set(favSet.value);
  if (next.has(key)) {
    next.delete(key);
  } else {
    next.add(key);
  }
  favSet.value = next;
  localStorage.setItem(favKey, JSON.stringify([...next]));
}

const favTasksView = computed(() => {
  const map = new Map(tasks.value.map(item => [item.__key, item]));
  return [...favSet.value.values()]
    .map(key => map.get(key))
    .filter(Boolean)
    .sort((a, b) => a.title.localeCompare(b.title) || a.plan.localeCompare(b.plan) || a.task.localeCompare(b.task))
    .map(item => ({ ...item, titleHtml: item.title, descHtml: item.desc, starred: true }));
});

const filteredTasks = computed(() => {
  const plan = ui.planSelected || plans.value[0]?.name || '';
  const query = (debouncedQuery.value || '').trim().toLowerCase(); // 使用防抖后的查询
  const match = (item) => !query || `${item.plan}${item.task}${item.title}${item.desc}`.toLowerCase().includes(query);
  const inPlan = tasks.value.filter(item => item.plan === plan && match(item));
  const outPlan = tasks.value.filter(item => item.plan !== plan && match(item));
  const sorter = (a, b) => {
    const aFav = favSet.value.has(`${a.plan}::${a.task}`);
    const bFav = favSet.value.has(`${b.plan}::${b.task}`);
    if (aFav !== bFav) return aFav ? -1 : 1;
    const titleCmp = a.title.localeCompare(b.title);
    if (titleCmp) return titleCmp;
    const planCmp = a.plan.localeCompare(b.plan);
    return planCmp || a.task.localeCompare(b.task);
  };
  return [...inPlan, ...outPlan]
    .sort(sorter)
    .map(item => ({
      ...item,
      starred: favSet.value.has(`${item.plan}::${item.task}`),
      titleHtml: item.title,
      descHtml: item.desc,
    }));
});

async function loadPlans() {
  try {
    const { data } = await api.get('/plans');
    plans.value = data || [];
  } catch (err) {
    toast({ type: 'error', title: 'Load plans failed', message: err.message });
  }
}

async function loadTasks() {
  const list = [];
  for (const plan of plans.value) {
    try {
      const { data } = await api.get(`/plans/${plan.name}/tasks`);
      (data || []).forEach((task) => {
        list.push({
          __key: `${plan.name}::${task.task_name_in_plan || task.task_name}`,
          plan: plan.name,
          task: task.task_name_in_plan || task.task_name,
          title: task.meta?.title || task.task_name_in_plan || task.task_name,
          desc: task.meta?.description || '',
          meta: task.meta || {},
        });
      });
    } catch {
      /* ignore per-plan failures */
    }
  }
  tasks.value = list;
}

const config = reactive({
  open: false,
  plan: '',
  task: '',
  title: 'Configure Task',
  meta: null,
  repeat: 1,
});
const inputModel = reactive({});
const normalizedInputs = computed(() => {
  if (!Array.isArray(config.meta?.inputs)) return [];
  return (config.meta.inputs || [])
    .filter((input) => input && typeof input === 'object' && input.name)
    .map((input) => normalizeInputSchema({
      ...input,
      label: input.label || input.name,
      name: input.name,
    }));
});
const hasInputs = computed(() => normalizedInputs.value.length > 0);

function deriveFilePath(taskName) {
  const parts = taskName.split('/');
  if (parts.length === 1) {
    return `tasks/${parts[0]}.yaml`;
  }
  const filePath = parts.slice(0, -1).join('/');
  return `tasks/${filePath}.yaml`;
}

async function reloadTaskFile(plan, taskName) {
  const filePath = deriveFilePath(taskName);
  try {
    await api.post(`/plans/${plan}/files/reload`, null, { params: { path: filePath } });
  } catch (err) {
    console.warn('[ExecuteView] reload task file failed:', err);
  }
  return filePath;
}

async function resolveTaskMeta(plan, taskName, meta = {}) {
  if (Array.isArray(meta?.inputs)) return meta;
  const filePath = await reloadTaskFile(plan, taskName);
  try {
    const { data } = await api.get(`/plans/${plan}/files/content`, { params: { path: filePath } });
    const taskFile = parseTaskFile(data, filePath);
    const taskKey = taskName.split('/').slice(-1)[0];
    const fileMeta = taskFile?.tasks?.[taskKey]?.meta;
    if (fileMeta && typeof fileMeta === 'object') {
      return { ...meta, ...fileMeta, inputs: fileMeta.inputs ?? meta.inputs };
    }
  } catch (err) {
    console.warn('[ExecuteView] load task meta failed:', err);
  }
  return meta;
}

function resetInputModel() {
  Object.keys(inputModel).forEach(key => delete inputModel[key]);
}

function applyInputDefaults() {
  resetInputModel();
  const defaults = (config.meta?.defaults && typeof config.meta.defaults === 'object')
    ? config.meta.defaults
    : {};
  normalizedInputs.value.forEach((schema) => {
    const fallback = buildDefaultFromSchema(schema);
    inputModel[schema.name] = defaults[schema.name] ?? fallback;
  });
}

async function openConfig(plan, task, meta) {
  config.open = true;
  config.plan = plan;
  config.task = task;
  config.meta = await resolveTaskMeta(plan, task, meta || {});
  config.title = `Configure · ${task}`;
  config.repeat = 1;
  applyInputDefaults();
}

const canAdd = computed(() => !!config.plan && !!config.task);

function parseInputs() {
  return { ...inputModel };
}

const {
  readyQueue,
  fetchReady,
  remove: removeReady,
  moveFront: moveFrontBackend,
  clear: clearReady,
  activeRuns,
  fetchActiveRuns,
} = useBackendQueue();
const {
  items: guiItems,
  add: addGui,
  update: updateGui,
  remove: removeGuiItem,
  clear: clearGuiItems,
  move: moveGuiItem,
} = useGuiQueue();

const history = ref([]);
let pollTimer = null;
let activeMap = new Map();
const historyView = computed(() =>
  history.value.filter(item => item.plan && item.task && item.status && !String(item.status).toLowerCase().includes('starting'))
);

async function refreshQueue() {
  await fetchReady();
}

async function refreshActiveRuns() {
  const prev = new Map(activeMap);
  await fetchActiveRuns();
  activeMap = new Map();
  for (const run of activeRuns.value) {
    const key = run.trace_id || run.cid || `${run.plan_name}/${run.task_name}`;
    activeMap.set(key, run);
    prev.delete(key);
  }
  prev.forEach((run, key) => {
    history.value = [{
      id: `hist_${key}_${Date.now()}`,
      plan: run.plan_name,
      task: run.task_name,
      status: run.status || '完成',
      at: Date.now(),
    }, ...history.value].slice(0, 100);
  });
}

async function removeQueue(cid) {
  await removeReady(cid);
  await fetchReady();
}

async function moveFrontQueue(cid) {
  await moveFrontBackend(cid);
  await fetchReady();
}

async function clearQueue() {
  await clearReady();
  await fetchReady();
}

function addToGuiQueue() {
  const inputs = parseInputs();
  const repeat = Math.max(1, Math.min(500, config.repeat || 1));
  for (let i = 0; i < repeat; i += 1) {
    addGui({ plan: config.plan, task: config.task, inputs, repeat: 1 });
  }
  config.open = false;
  toast({
    type: 'success',
    title: '已加入前端队列',
    message: `${config.plan} / ${config.task} ×${repeat}`,
  });
}

async function pushToBackend(item) {
  const inputs = item.inputs || {};
  updateGui(item.id, { status: 'pushing' });
  try {
    await reloadTaskFile(item.plan, item.task);
    const repeat = Math.max(1, item.repeat || 1);
    let cid = null;
    if (repeat > 1) {
      const tasksPayload = Array.from({ length: repeat }, () => ({
        plan_name: item.plan,
        task_name: item.task,
        inputs,
      }));
      const { data } = await api.post('/tasks/batch', { tasks: tasksPayload });
      if (Array.isArray(data?.results) && data.results.length) {
        cid = data.results[0]?.cid || null;
      }
    } else {
      const { data } = await api.post('/tasks/run', {
        plan_name: item.plan,
        task_name: item.task,
        inputs,
      });
      cid = data?.cid || null;
    }
    updateGui(item.id, { status: 'queued', lastCid: cid, pushedAt: Date.now() });
    history.value = [{
      id: item.id,
      plan: item.plan,
      task: item.task,
      status: '已推送',
      at: Date.now(),
    }, ...history.value].slice(0, 50);
    removeGuiItem(item.id);
    toast({ type: 'success', title: '已推送', message: `${item.plan} / ${item.task}` });
    await fetchReady();
    await refreshActiveRuns();
  } catch (err) {
    updateGui(item.id, { status: 'pending' });
    toast({
      type: 'error',
      title: 'Push failed',
      message: err?.response?.data?.detail || err.message,
    });
  }
}

function removeGui(id) {
  removeGuiItem(id);
}

function moveGui(id, direction) {
  moveGuiItem(id, direction);
}

function clearGuiQueue() {
  clearGuiItems();
}

async function pushAllGui() {
  const list = [...guiItems.value];
  for (const item of list) {
    await pushToBackend(item);
  }
}

function fmtTime(ts) {
  return ts ? new Date(ts * 1000).toLocaleTimeString() : '-';
}

function fmtTimeMs(ts) {
  if (!ts) return '-';
  const ms = typeof ts === 'number' && ts > 1e12 ? ts : ts * 1000;
  return new Date(ms).toLocaleString();
}

function guiStatusLabel(status) {
  if (status === 'pending') return '待推送';
  if (status === 'pushing') return '推送中';
  if (status === 'queued') return '已推送';
  return status;
}

function guiStatusClass(status) {
  if (status === 'queued') return 'pill-green';
  if (status === 'pushing') return 'pill-blue';
  return '';
}

function moveFront(cid) {
  moveFrontQueue(cid);
}

onMounted(async () => {
  await loadPlans();
  if (!ui.planSelected && plans.value.length) {
    ui.planSelected = plans.value[0].name;
  }
  await loadTasks();
  await fetchReady();
  await refreshActiveRuns();
  try {
    const { data } = await api.get('/system/status');
    engineRunning.value = !!data?.is_running;
  } catch {
    engineRunning.value = false;
  }
  pollTimer = setInterval(async () => {
    await fetchReady();
    await refreshActiveRuns();
  }, 2000);
});

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});
</script>

<style scoped>
.execute-view { display: flex; flex-direction: column; gap: 16px; }
.header-bar { display: flex; justify-content: space-between; align-items: center; }
.view-title { font-size: 22px; }
.view-subtitle { color: var(--text-3); font-size: 12px; }
.toolbar { display: flex; gap: 8px; align-items: center; }
.pill { padding: 4px 10px; border-radius: 999px; background: #eee; color: #555; font-size: 12px; }
.pill-blue { background: #e0f2ff; color: #0369a1; }
.pill-green { background: #e0ffe8; color: #0f9d58; }
.content-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.task-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; margin-top: 10px; }
.empty-state { color: #999; text-align: center; padding: 16px; }
.queue-panel table { width: 100%; border-collapse: collapse; }
.queue-panel th, .queue-panel td { padding: 8px; border-bottom: 1px solid #eee; text-align: left; }
.queue-panel code { font-family: ui-monospace, Menlo, monospace; font-size: 12px; }
.trace-label { font-size: 11px; color: var(--text-3); line-height: 1.2; }
.json-input .textarea { width: 100%; height: 160px; }
.form-grid { display: grid; grid-template-columns: 1fr; gap: 12px; margin: 12px 0; }
.field .label { font-size: 12px; color: var(--text-3); margin-bottom: 4px; }
.error { color: #c00; font-size: 12px; }
</style>

<template>
  <div class="panel">
    <div class="panel-header automation-header">
      <div>
        <strong>自动化</strong>
        <div class="panel-subtitle">按方案管理调度与中断规则。</div>
      </div>
      <div class="header-actions">
        <button class="btn btn-ghost btn-mini" :disabled="loading" @click="refreshPlanData">刷新</button>
        <button class="btn btn-ghost btn-mini" @click="restartScheduler">重启调度器</button>
      </div>
    </div>

    <div class="panel-body automation-grid">
      <div class="panel plan-panel">
        <div class="panel-header plan-header-actions">
          <div class="plan-header-title">
            <strong>方案</strong>
          </div>
          <input class="input" v-model="planQuery" placeholder="搜索方案" style="min-width:140px;" />
        </div>
        <div class="panel-body" style="padding:0;">
          <div class="plan-list">
            <table>
              <thead>
                <tr><th>名称</th></tr>
              </thead>
              <tbody>
                <tr
                  v-for="p in filteredPlans"
                  :key="p.name"
                  @click="selectPlan(p.name)"
                  :style="{background: selectedPlan===p.name ? 'rgba(88, 101, 242, 0.12)' : 'transparent'}"
                >
                  <td>
                    <strong>{{ p.name }}</strong>
                    <div class="plan-count">{{ p.task_count }} 个任务</div>
                  </td>
                </tr>
                <tr v-if="!filteredPlans.length"><td class="empty-cell">暂无方案</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="rules-panel">
        <div class="rules-tabs">
          <button class="tab-button" :class="{ active: activeTab === 'schedules' }" @click="activeTab='schedules'">调度</button>
          <button class="tab-button" :class="{ active: activeTab === 'interrupts' }" @click="activeTab='interrupts'">中断</button>
        </div>

        <ProFilterBar v-model="activeFilters" :status-options="statusOptions" :plan-options="[]">
          <button class="btn btn-primary btn-mini" @click="createRule">新建</button>
          <button class="btn btn-ghost btn-mini" @click="refreshRules">刷新</button>
        </ProFilterBar>

        <ProDataTable
          :columns="activeColumns"
          :rows="activeRows"
          row-key="__key"
          :maxHeight="'64vh'"
          @row-click="openEditor"
        >
          <template #col-triggers="{ row }">
            <div class="trigger-tags">
              <span v-for="tag in row.triggerTags" :key="tag" class="pill">{{ tag }}</span>
              <span v-if="!row.triggerTags.length" class="empty-tag">无</span>
            </div>
          </template>
          <template #col-enabled="{ row }">
            <span class="pill" :class="row.enabled ? 'pill-green' : 'pill-red'">
              {{ row.enabled ? '启用' : '禁用' }}
            </span>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-ghost btn-mini" @click.stop="toggleRule(row)">
              {{ row.enabled ? '禁用' : '启用' }}
            </button>
            <button class="btn btn-ghost btn-mini" @click.stop="openEditor(row)">编辑</button>
            <button class="btn btn-ghost btn-mini" @click.stop="deleteRule(row)">删除</button>
          </template>
        </ProDataTable>
      </div>
    </div>
  </div>

  <ProContextPanel :open="editor.open" :title="editor.title" width="640px" @close="closeEditor">
    <div v-if="editor.rule" class="editor-wrap">
      <div class="editor-sub">方案：{{ selectedPlan || '-' }}</div>

      <div v-if="editor.mode === 'schedules'" class="editor-form">
        <div class="field">
          <label>ID</label>
          <input class="input" v-model="editor.rule.id" />
        </div>
        <div class="field">
          <label>任务</label>
          <input class="input" list="task-options" v-model="editor.rule.task" placeholder="task_name" />
          <datalist id="task-options">
            <option v-for="task in taskOptions" :key="task" :value="task" />
          </datalist>
        </div>
        <div class="field inline">
          <label>启用</label>
          <input type="checkbox" v-model="editor.rule.enabled" />
        </div>

        <div class="section-title">触发器</div>
        <div v-for="(trigger, idx) in editor.rule.triggers" :key="`tr-${idx}`" class="trigger-card">
          <div class="trigger-head">
            <select class="select" v-model="trigger.type">
              <option value="cron">定时</option>
              <option value="variable">变量</option>
              <option value="task">任务</option>
              <option value="file">文件</option>
              <option value="event">事件</option>
            </select>
            <button class="btn btn-ghost btn-mini" @click="removeTrigger(idx)">移除</button>
          </div>

          <div v-if="trigger.type === 'cron'" class="trigger-body">
            <label>表达式</label>
            <input class="input" v-model="trigger.expression" placeholder="* * * * *" />
          </div>

          <div v-else-if="trigger.type === 'variable'" class="trigger-body">
            <label>键</label>
            <input class="input" v-model="trigger.key" placeholder="state.key" />
            <label>运算符</label>
            <select class="select" v-model="trigger.operator">
              <option value="eq">等于</option>
              <option value="neq">不等于</option>
            </select>
            <label>值</label>
            <input class="input" v-model="trigger.value" placeholder="值（可留空）" />
          </div>

          <div v-else-if="trigger.type === 'task'" class="trigger-body">
            <label>任务</label>
            <input class="input" list="task-options" v-model="trigger.task" placeholder="task_name" />
            <label>状态</label>
            <select class="select" v-model="trigger.status">
              <option value="completed">完成</option>
            </select>
          </div>

          <div v-else-if="trigger.type === 'file'" class="trigger-body">
            <label>路径</label>
            <input class="input" v-model="trigger.path" placeholder="./path" />
            <label>匹配</label>
            <input class="input" v-model="trigger.pattern" placeholder="*.txt" />
            <label>事件</label>
            <input class="input" v-model="trigger.eventsText" placeholder="created, modified" />
            <label class="inline">
              <input type="checkbox" v-model="trigger.recursive" />
              递归
            </label>
          </div>

          <div v-else-if="trigger.type === 'event'" class="trigger-body">
            <label>事件模式</label>
            <input class="input" v-model="trigger.event" placeholder="event.name" />
          </div>
        </div>
        <button class="btn btn-ghost btn-mini" @click="addTrigger">添加触发器</button>

        <div class="section-title">输入</div>
        <textarea class="textarea" v-model="editor.inputsText" placeholder="{}"></textarea>

        <div class="section-title">运行选项</div>
        <div class="field">
          <label>冷却（秒）</label>
          <input class="input" type="number" min="0" v-model.number="editor.rule.run_options.cooldown" />
        </div>
      </div>

      <div v-else class="editor-form">
        <div class="field">
          <label>名称</label>
          <input class="input" v-model="editor.rule.name" />
        </div>
        <div class="field">
          <label>处理任务</label>
          <input class="input" list="task-options" v-model="editor.rule.handler_task" placeholder="task_name" />
        </div>
        <div class="field">
          <label>范围</label>
          <select class="select" v-model="editor.rule.scope">
            <option value="plan">方案</option>
            <option value="global">全局</option>
          </select>
        </div>
        <div class="field inline">
          <label>默认启用</label>
          <input type="checkbox" v-model="editor.rule.enabled_by_default" />
        </div>

        <div class="section-title">条件</div>
        <div class="field">
          <label>动作</label>
          <input class="input" v-model="editor.rule.condition.action" placeholder="action.name" />
        </div>
        <div class="field">
          <label>参数</label>
          <textarea class="textarea" v-model="editor.paramsText" placeholder="{}"></textarea>
        </div>

        <div class="section-title">时序</div>
        <div class="field">
          <label>检查间隔（秒）</label>
          <input class="input" type="number" min="0" v-model.number="editor.rule.check_interval" />
        </div>
        <div class="field">
          <label>冷却（秒）</label>
          <input class="input" type="number" min="0" v-model.number="editor.rule.cooldown" />
        </div>
      </div>

      <div v-if="editor.error" class="error-text">{{ editor.error }}</div>
      <div class="editor-actions">
        <button class="btn btn-ghost" @click="closeEditor">取消</button>
        <button class="btn btn-primary" @click="saveEditor">保存</button>
      </div>
    </div>
    <div v-else class="empty-panel">请选择一条规则进行编辑。</div>
  </ProContextPanel>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import axios from 'axios';
import YAML from 'yaml';
import { nanoid } from 'nanoid';
import ProFilterBar from '../components/ProFilterBar.vue';
import ProDataTable from '../components/ProDataTable.vue';
import ProContextPanel from '../components/ProContextPanel.vue';
import { useTaskEditorApi } from '../composables/useTaskEditorApi.js';
import { useToasts } from '../composables/useToasts.js';
import { getGuiConfig } from '../config.js';

const api = useTaskEditorApi();
const { push: toast } = useToasts();
const cfg = getGuiConfig();
const systemApi = axios.create({
  baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: cfg?.api?.timeout_ms || 5000,
});

const plans = ref([]);
const planQuery = ref('');
const selectedPlan = ref('');
const tasks = ref([]);
const activeTab = ref('schedules');
const scheduleRules = ref([]);
const interruptRules = ref([]);
const loading = ref(false);

const filters = reactive({
  schedules: { query: '', status: '', plan: '' },
  interrupts: { query: '', status: '', plan: '' },
});

const editor = reactive({
  open: false,
  mode: 'schedules',
  title: '',
  rule: null,
  inputsText: '',
  paramsText: '',
  error: '',
  originalKey: ''
});

const scheduleColumns = [
  { key: 'id', label: 'ID', sortable: true, width: '24%' },
  { key: 'task', label: '任务', sortable: true, width: '22%' },
  { key: 'triggers', label: '触发器', width: '28%' },
  { key: 'cooldown', label: '冷却', sortable: true, width: '12%' },
  { key: 'enabled', label: '启用', sortable: true, width: '10%' },
];

const interruptColumns = [
  { key: 'name', label: '名称', sortable: true, width: '24%' },
  { key: 'handler_task', label: '处理任务', width: '24%' },
  { key: 'scope', label: '范围', sortable: true, width: '12%' },
  { key: 'check_interval', label: '检查', sortable: true, width: '12%' },
  { key: 'cooldown', label: '冷却', sortable: true, width: '12%' },
  { key: 'enabled', label: '启用', sortable: true, width: '10%' },
];

const activeFilters = computed({
  get: () => filters[activeTab.value],
  set: (val) => {
    filters[activeTab.value] = { ...filters[activeTab.value], ...val };
  }
});

const statusOptions = computed(() => ['启用', '禁用']);

const filteredPlans = computed(() => {
  const q = planQuery.value.trim().toLowerCase();
  if (!q) return plans.value;
  return plans.value.filter((p) => p.name.toLowerCase().includes(q));
});

const taskOptions = computed(() => {
  return tasks.value
    .map((t) => t.task_name_in_plan || t.task_name)
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b));
});

const activeColumns = computed(() => activeTab.value === 'schedules' ? scheduleColumns : interruptColumns);

const activeRows = computed(() => {
  const q = (activeFilters.value.query || '').trim().toLowerCase();
  const status = activeFilters.value.status;
  if (activeTab.value === 'schedules') {
    return scheduleRules.value
      .map((rule) => {
        const enabled = rule.enabled !== false;
        return {
          __key: rule.id,
          id: rule.id,
          task: rule.task,
          cooldown: rule.run_options?.cooldown ?? 0,
          enabled,
          triggerTags: summarizeTriggers(rule.triggers),
          __ref: rule,
        };
      })
      .filter((row) => {
        const matchQuery = !q || `${row.id}${row.task}`.toLowerCase().includes(q);
        const matchStatus = !status || (status === '启用' ? row.enabled : !row.enabled);
        return matchQuery && matchStatus;
      });
  }

  return interruptRules.value
    .map((rule) => {
      const enabled = getInterruptEnabled(rule);
      return {
        __key: rule.name,
        name: rule.name,
        handler_task: rule.handler_task,
        scope: rule.scope || 'plan',
        check_interval: rule.check_interval ?? 5,
        cooldown: rule.cooldown ?? 60,
        enabled,
        triggerTags: [],
        __ref: rule,
      };
    })
    .filter((row) => {
      const matchQuery = !q || `${row.name}${row.handler_task}`.toLowerCase().includes(q);
      const matchStatus = !status || (status === '启用' ? row.enabled : !row.enabled);
      return matchQuery && matchStatus;
    });
});

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function summarizeTriggers(triggers) {
  if (!Array.isArray(triggers)) return [];
  return triggers.map((t) => {
    if (!t || typeof t !== 'object') return '未知';
    const type = t.type || '未知';
    if (type === 'cron') return `定时:${t.expression || '*'}`;
    if (type === 'variable') return `变量:${t.key || '-'}`;
    if (type === 'task') return `任务:${t.task || '-'}`;
    if (type === 'file') return `文件:${t.path || '-'}`;
    if (type === 'event') return `事件:${t.event || '-'}`;
    return type;
  });
}

function getInterruptEnabled(rule) {
  if (!rule || typeof rule !== 'object') return false;
  if (rule.scope === 'global') return !!rule.enabled_by_default;
  if (typeof rule.enabled === 'boolean') return rule.enabled;
  return true;
}

function setInterruptEnabled(rule, value) {
  if (rule.scope === 'global') {
    rule.enabled_by_default = value;
    return;
  }
  rule.enabled = value;
}

function normalizeSchedule(raw, index) {
  const base = raw && typeof raw === 'object' ? clone(raw) : {};
  const id = base.id || `schedule_${index + 1}`;
  const triggers = Array.isArray(base.triggers) ? base.triggers.map((t) => {
    const trigger = t && typeof t === 'object' ? clone(t) : {};
    if (trigger.type === 'file') {
      const text = Array.isArray(trigger.events) ? trigger.events.join(', ') : (trigger.events || '');
      trigger.eventsText = text;
    }
    return trigger;
  }) : [];
  return {
    id,
    task: base.task || '',
    enabled: base.enabled !== false,
    inputs: base.inputs && typeof base.inputs === 'object' ? base.inputs : {},
    run_options: {
      cooldown: 0,
      ...(base.run_options && typeof base.run_options === 'object' ? base.run_options : {})
    },
    triggers,
  };
}

function normalizeInterrupt(raw, index) {
  const base = raw && typeof raw === 'object' ? clone(raw) : {};
  return {
    name: base.name || `interrupt_${index + 1}`,
    handler_task: base.handler_task || '',
    scope: base.scope || 'plan',
    enabled_by_default: !!base.enabled_by_default,
    enabled: typeof base.enabled === 'boolean' ? base.enabled : undefined,
    condition: base.condition && typeof base.condition === 'object' ? base.condition : { action: '', params: {} },
    check_interval: base.check_interval ?? 5,
    cooldown: base.cooldown ?? 60,
  };
}

async function loadPlans() {
  plans.value = await api.listPlans();
  if (!selectedPlan.value && plans.value.length) {
    selectedPlan.value = plans.value[0].name;
  }
}

async function loadTasks(planName) {
  if (!planName) return [];
  try {
    return await api.listTasksForPlan(planName);
  } catch {
    return [];
  }
}

async function readYamlFile(planName, path) {
  try {
    const content = await api.getFileContent(planName, path);
    return content || '';
  } catch (err) {
    if (err?.response?.status === 404) return '';
    throw err;
  }
}

async function loadSchedules(planName) {
  const content = await readYamlFile(planName, 'schedule.yaml');
  const data = content ? YAML.parse(content) : {};
  const list = Array.isArray(data?.schedules) ? data.schedules : [];
  scheduleRules.value = list.map(normalizeSchedule);
}

async function loadInterrupts(planName) {
  const content = await readYamlFile(planName, 'interrupts.yaml');
  const data = content ? YAML.parse(content) : {};
  const list = Array.isArray(data?.interrupts) ? data.interrupts : [];
  interruptRules.value = list.map(normalizeInterrupt);
}

async function refreshPlanData() {
  if (!selectedPlan.value) return;
  loading.value = true;
  try {
    tasks.value = await loadTasks(selectedPlan.value);
    await loadSchedules(selectedPlan.value);
    await loadInterrupts(selectedPlan.value);
  } catch (err) {
    toast({ type: 'error', title: '加载失败', message: err.message });
  } finally {
    loading.value = false;
  }
}

function selectPlan(name) {
  selectedPlan.value = name;
}

async function refreshRules() {
  if (!selectedPlan.value) return;
  if (activeTab.value === 'schedules') {
    await loadSchedules(selectedPlan.value);
  } else {
    await loadInterrupts(selectedPlan.value);
  }
}

function createRule() {
  if (activeTab.value === 'schedules') {
    editor.mode = 'schedules';
    editor.originalKey = '';
    editor.rule = normalizeSchedule({
      id: `schedule_${nanoid(6)}`,
      task: '',
      enabled: true,
      triggers: [{ type: 'cron', expression: '* * * * *' }],
      inputs: {},
      run_options: { cooldown: 0 }
    }, 0);
    editor.inputsText = JSON.stringify(editor.rule.inputs || {}, null, 2);
    editor.title = '新建调度';
  } else {
    editor.mode = 'interrupts';
    editor.originalKey = '';
    editor.rule = normalizeInterrupt({
      name: `interrupt_${nanoid(6)}`,
      handler_task: '',
      scope: 'plan',
      enabled_by_default: false,
      condition: { action: '', params: {} },
      check_interval: 5,
      cooldown: 60
    }, 0);
    editor.paramsText = JSON.stringify(editor.rule.condition?.params || {}, null, 2);
    editor.title = '新建中断';
  }
  editor.error = '';
  editor.open = true;
}

function openEditor(row) {
  if (!row || !row.__ref) return;
  const rule = clone(row.__ref);
  editor.mode = activeTab.value;
  editor.originalKey = activeTab.value === 'schedules' ? rule.id : rule.name;
  editor.rule = activeTab.value === 'schedules'
    ? normalizeSchedule(rule, 0)
    : normalizeInterrupt(rule, 0);
  editor.inputsText = JSON.stringify(editor.rule.inputs || {}, null, 2);
  editor.paramsText = JSON.stringify(editor.rule.condition?.params || {}, null, 2);
  editor.title = activeTab.value === 'schedules'
    ? `编辑调度：${editor.rule.id}`
    : `编辑中断：${editor.rule.name}`;
  editor.error = '';
  editor.open = true;
}

function closeEditor() {
  editor.open = false;
  editor.rule = null;
  editor.inputsText = '';
  editor.paramsText = '';
  editor.error = '';
  editor.originalKey = '';
}

function addTrigger() {
  if (!editor.rule?.triggers) editor.rule.triggers = [];
  editor.rule.triggers.push({ type: 'cron', expression: '* * * * *' });
}

function removeTrigger(idx) {
  editor.rule.triggers.splice(idx, 1);
}

function parseJson(text) {
  const trimmed = String(text || '').trim();
  if (!trimmed) return {};
  try {
    return JSON.parse(trimmed);
  } catch (err) {
    throw new Error('JSON 无效。');
  }
}

function normalizeScheduleTrigger(trigger) {
  if (!trigger || typeof trigger !== 'object') return trigger;
  if (trigger.type === 'file') {
    const eventsRaw = trigger.eventsText || trigger.events;
    const events = typeof eventsRaw === 'string'
      ? eventsRaw.split(',').map((v) => v.trim()).filter(Boolean)
      : Array.isArray(eventsRaw) ? eventsRaw : [];
    const out = { ...trigger };
    delete out.eventsText;
    if (events.length) {
      out.events = events;
    } else {
      delete out.events;
    }
    return out;
  }
  if (trigger.type === 'variable') {
    const out = { ...trigger };
    if (out.value === '' || out.value === undefined) {
      delete out.value;
    }
    return out;
  }
  return { ...trigger };
}

function buildSchedulePayload(rule) {
  const payload = {
    id: rule.id,
    task: rule.task,
    enabled: rule.enabled !== false,
    triggers: Array.isArray(rule.triggers)
      ? rule.triggers.map(normalizeScheduleTrigger).filter((t) => t && t.type)
      : []
  };
  if (rule.inputs && Object.keys(rule.inputs).length) {
    payload.inputs = rule.inputs;
  }
  if (rule.run_options && Object.keys(rule.run_options).length) {
    payload.run_options = rule.run_options;
  }
  return payload;
}

function buildInterruptPayload(rule) {
  const payload = {
    name: rule.name,
    handler_task: rule.handler_task,
    scope: rule.scope || 'plan',
    enabled_by_default: !!rule.enabled_by_default,
    check_interval: rule.check_interval ?? 5,
    cooldown: rule.cooldown ?? 60,
    condition: rule.condition || { action: '', params: {} },
  };
  if (rule.scope !== 'global' && typeof rule.enabled === 'boolean') {
    payload.enabled = rule.enabled;
  }
  return payload;
}

async function saveSchedules() {
  if (!selectedPlan.value) return;
  const payload = { schedules: scheduleRules.value.map(buildSchedulePayload) };
  const content = YAML.stringify(payload, { indent: 2 });
  await api.saveFileContent(selectedPlan.value, 'schedule.yaml', content);
  toast({ type: 'success', title: '调度已保存', message: '请重启调度器以生效。' });
}

async function saveInterrupts() {
  if (!selectedPlan.value) return;
  const payload = { interrupts: interruptRules.value.map(buildInterruptPayload) };
  const content = YAML.stringify(payload, { indent: 2 });
  await api.saveFileContent(selectedPlan.value, 'interrupts.yaml', content);
  toast({ type: 'success', title: '中断已保存', message: '请重启调度器以生效。' });
}

async function saveEditor() {
  if (!editor.rule) return;
  editor.error = '';
  try {
    if (editor.mode === 'schedules') {
      if (!editor.rule.id || !editor.rule.task) {
        editor.error = '必须填写调度 ID 和任务。';
        return;
      }
      editor.rule.inputs = parseJson(editor.inputsText);
      const key = editor.originalKey || editor.rule.id;
      let idx = scheduleRules.value.findIndex((r) => r.id === key);
      if (editor.originalKey && editor.originalKey !== editor.rule.id) {
        scheduleRules.value = scheduleRules.value.filter((r) => r.id !== editor.originalKey);
        idx = -1;
      }
      if (idx >= 0) {
        scheduleRules.value[idx] = clone(editor.rule);
      } else {
        scheduleRules.value.unshift(clone(editor.rule));
      }
      await saveSchedules();
    } else {
      if (!editor.rule.name || !editor.rule.handler_task) {
        editor.error = '必须填写中断名称和处理任务。';
        return;
      }
      editor.rule.condition = editor.rule.condition || { action: '', params: {} };
      editor.rule.condition.params = parseJson(editor.paramsText);
      const key = editor.originalKey || editor.rule.name;
      let idx = interruptRules.value.findIndex((r) => r.name === key);
      if (editor.originalKey && editor.originalKey !== editor.rule.name) {
        interruptRules.value = interruptRules.value.filter((r) => r.name !== editor.originalKey);
        idx = -1;
      }
      if (idx >= 0) {
        interruptRules.value[idx] = clone(editor.rule);
      } else {
        interruptRules.value.unshift(clone(editor.rule));
      }
      await saveInterrupts();
    }
    closeEditor();
  } catch (err) {
    editor.error = err.message || '保存失败。';
  }
}

async function toggleRule(row) {
  if (!row || !row.__ref) return;
  if (activeTab.value === 'schedules') {
    row.__ref.enabled = !row.__ref.enabled;
    await saveSchedules();
  } else {
    setInterruptEnabled(row.__ref, !getInterruptEnabled(row.__ref));
    await saveInterrupts();
  }
}

async function deleteRule(row) {
  if (!row || !row.__ref) return;
  const label = activeTab.value === 'schedules' ? row.id : row.name;
  const ok = window.confirm(`确认删除 ${label}？`);
  if (!ok) return;
  if (activeTab.value === 'schedules') {
    scheduleRules.value = scheduleRules.value.filter((r) => r.id !== row.id);
    await saveSchedules();
  } else {
    interruptRules.value = interruptRules.value.filter((r) => r.name !== row.name);
    await saveInterrupts();
  }
}

async function restartScheduler() {
  const ok = window.confirm('是否重启调度器以应用更改？');
  if (!ok) return;
  try {
    await systemApi.post('/system/stop');
  } catch {
  }
  try {
    await systemApi.post('/system/start');
    toast({ type: 'success', title: '调度器已重启', message: '更改已生效。' });
  } catch (err) {
    toast({ type: 'error', title: '重启失败', message: err.message });
  }
}

watch(selectedPlan, async (plan) => {
  if (!plan) return;
  await refreshPlanData();
});

onMounted(loadPlans);
</script>

<style scoped>
.panel-subtitle {
  color: var(--text-secondary);
  font-size: 13px;
}
.automation-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.automation-grid {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
  min-height: 60vh;
}
.plan-panel {
  display: flex;
  flex-direction: column;
}
.plan-header-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.plan-header-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.plan-list {
  max-height: 64vh;
  overflow: auto;
}
.plan-count {
  color: var(--text-secondary);
  font-size: 12px;
}
.plan-list th {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-frosted);
  background: rgba(249, 250, 251, 0.8);
}
.plan-list td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-frosted);
  cursor: pointer;
}
.empty-cell {
  padding: 12px;
  color: var(--text-secondary);
}
.rules-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.rules-tabs {
  display: flex;
  gap: 8px;
}
.tab-button {
  border: 1px solid transparent;
  border-radius: 999px;
  padding: 6px 14px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--dur) var(--ease);
}
.tab-button:hover {
  background: rgba(88, 101, 242, 0.08);
  color: var(--text-primary);
}
.tab-button.active {
  background: var(--primary-accent);
  color: #fff;
}
.trigger-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.empty-tag {
  font-size: 12px;
  color: var(--text-tertiary);
}
.editor-wrap {
  display: grid;
  gap: 12px;
}
.editor-sub {
  font-size: 12px;
  color: var(--text-secondary);
}
.editor-form {
  display: grid;
  gap: 12px;
}
.field {
  display: grid;
  gap: 6px;
}
.field.inline {
  display: flex;
  align-items: center;
  gap: 8px;
}
.field label {
  font-size: 12px;
  color: var(--text-secondary);
}
.section-title {
  font-size: 12px;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.trigger-card {
  border: 1px solid var(--border-frosted);
  border-radius: 12px;
  padding: 10px;
  display: grid;
  gap: 8px;
}
.trigger-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.trigger-body {
  display: grid;
  gap: 6px;
}
.textarea {
  min-height: 120px;
  border: 1px solid var(--border-frosted);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  font-family: ui-monospace, Menlo, monospace;
  color: var(--text-primary);
  background: transparent;
}
.error-text {
  color: #c00;
  font-size: 12px;
}
.editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.btn-mini {
  padding: 4px 10px;
  font-size: 12px;
}
@media (max-width: 980px) {
  .automation-grid {
    grid-template-columns: 1fr;
  }
  .plan-panel {
    min-height: 220px;
  }
  .plan-list {
    max-height: 220px;
  }
}
</style>

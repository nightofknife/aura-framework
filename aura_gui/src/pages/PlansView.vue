<template>
  <div class="panel">
    <div class="panel-header">
      <div><strong>Plans & Tasks</strong></div>
      <div style="color:var(--text-3); font-size:13px;">Select a plan to stage tasks, then dispatch from Execute</div>
    </div>

    <div class="panel-body" style="display:grid; grid-template-columns: 320px 1fr; gap:16px; min-height:60vh;">
      <!-- Plans list -->
      <div class="panel" style="display:flex; flex-direction:column;">
        <div class="panel-header">
          <strong>Plans</strong>
          <input class="input" v-model="planQuery" placeholder="Search plans…" style="min-width:140px;">
        </div>
        <div class="panel-body" style="padding:0;">
          <div style="max-height:60vh; overflow:auto;">
            <table>
              <thead><tr><th style="padding:10px 12px; border-bottom:1px solid var(--border); background:#F9FAFB;">Name</th></tr></thead>
              <tbody>
              <tr v-for="p in filteredPlans" :key="p.name" @click="selectPlan(p.name)" :style="{background: selectedPlan===p.name ? '#EEF2FF' : 'transparent'}">
                <td style="padding:10px 12px; border-bottom:1px solid var(--border); cursor:pointer;">
                  <strong>{{ p.name }}</strong>
                  <div style="color:var(--text-3); font-size:12px;">{{ p.task_count }} tasks</div>
                </td>
              </tr>
              <tr v-if="!filteredPlans.length"><td style="padding:12px; color:var(--text-3);">No plans.</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Tasks of selected plan -->
      <div style="display:flex; flex-direction:column; gap:12px;">
        <ProFilterBar v-model="filters" :status-options="[]" :plan-options="[]" @reset="onResetFilters">
          <select class="select" v-model="density" title="Row density">
            <option value="comfy">Comfy</option>
            <option value="compact">Compact</option>
          </select>
        </ProFilterBar>

        <ProDataTable
            :columns="taskColumns"
            :rows="taskRows"
            row-key="__key"
            :maxHeight="density==='compact' ? '68vh' : '60vh'"
            :sort-default="{key:'title',dir:'asc'}"
            @row-click="onTaskClick"
        >
          <template #col-title="{ row }">
            <div style="font-weight:700;">{{ row.title }}</div>
            <div style="color:var(--text-3); font-size:12px; max-width:900px; overflow:hidden; text-overflow:ellipsis;">
              {{ row.description || '—' }}
            </div>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-primary" @click.stop="openDrawer(row)">Configure</button>
          </template>
        </ProDataTable>
      </div>
    </div>
  </div>

  <!-- 右侧抽屉：百科 + 配置 + 高级 -->
  <ProContextPanel :open="drawerOpen" :title="drawerTitle" @close="drawerOpen=false">
    <div v-if="selectedTask">
      <!-- Details -->
      <div style="margin-bottom:12px;">
        <div style="font-size:12px; color:var(--text-3);">Plan</div>
        <div style="font-weight:600">{{ selectedPlan }}</div>
      </div>
      <div v-if="selectedTask.description" style="color:var(--text-2); margin-bottom:12px;">
        {{ selectedTask.description }}
      </div>
      <div v-if="examples.length" style="margin-bottom:12px;">
        <div style="font-size:12px; color:var(--text-3); margin-bottom:4px;">Examples</div>
        <div style="display:flex; gap:6px; flex-wrap:wrap;">
          <button class="btn btn-sm" v-for="(ex,i) in examples" :key="i" @click="applyExample(ex)">Use Example {{ i+1 }}</button>
        </div>
      </div>

      <hr style="border:none; border-top:1px solid var(--border); margin:12px 0;"/>

      <!-- Configure -->
      <div style="margin-bottom:10px; display:flex; align-items:center; justify-content:space-between;">
        <strong>Configure Inputs</strong>
        <div v-if="hasSchema" style="display:flex; gap:6px; align-items:center;">
          <label class="chk"><input type="checkbox" v-model="useJsonEditor"> JSON mode</label>
        </div>
      </div>

      <!-- Schema Form -->
      <div v-if="hasSchema && !useJsonEditor" style="display:grid; gap:10px;">
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

      <!-- JSON Editor -->
      <div v-else>
        <div style="font-size:12px; color:var(--text-3);">Inputs (JSON)</div>
        <textarea class="input" v-model="inputsRaw" rows="10" style="width:100%; font-family: ui-monospace, Menlo, monospace;"></textarea>
        <div v-if="jsonError" style="color:var(--danger); font-size:12px; margin-top:4px;">{{ jsonError }}</div>
      </div>

      <!-- Advanced -->
      <details style="margin-top:12px;">
        <summary style="cursor:pointer; color:var(--text-2);"><b>Advanced</b> (priority & note)</summary>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:10px;">
          <div>
            <div style="font-size:12px; color:var(--text-3);">Priority (optional)</div>
            <input class="input" v-model.number="priority" type="number" placeholder="e.g. 5">
          </div>
          <div>
            <div style="font-size:12px; color:var(--text-3);">Note</div>
            <input class="input" v-model="note" placeholder="Optional note">
          </div>
        </div>
      </details>

      <!-- Actions -->
      <div style="margin-top:12px; display:flex; gap:8px;">
        <button class="btn btn-primary" @click="addToQueue" :disabled="hasSchema?false:!!jsonError">Add to Queue</button>
        <button class="btn btn-ghost" @click="drawerOpen=false">Close</button>
      </div>
    </div>

    <div v-else style="color:var(--text-3);">No selection.</div>
  </ProContextPanel>
</template>

<script setup>
import {ref, computed, onMounted, reactive, watch} from 'vue';
import axios from 'axios';
import ProFilterBar from '../components/ProFilterBar.vue';
import ProDataTable from '../components/ProDataTable.vue';
import ProContextPanel from '../components/ProContextPanel.vue';
import {useToasts} from '../composables/useToasts.js';
import {useStagingQueue} from '../composables/useStagingQueue.js';

const {push: toast} = useToasts();
const {addTask} = useStagingQueue();

const api = axios.create({baseURL:'http://127.0.0.1:18098/api', timeout:5000});

const plans = ref([]);
const planQuery = ref('');
const selectedPlan = ref('');
const tasks = ref([]);
const filters = ref({ query:'', status:'', plan:'' });
const density = ref('comfy');

const taskColumns = [
  { key:'title', label:'Task', sortable:true, width:'45%' },
  { key:'last',  label:'Last Result', sortable:true, width:'20%' },
  { key:'avg',   label:'Avg Duration', sortable:true, width:'18%' },
];

const taskRows = computed(()=>{
  const list = tasks.value.map(t=>({
    __key: t.full_task_id || t.task_name_in_plan || t.task_name,
    title: t.meta?.title || t.task_name_in_plan || t.task_name,
    description: t.meta?.description || '',
    last: '—',
    avg:  '—',
    task_name: t.task_name_in_plan || t.task_name,
    meta: t.meta || {},
  }));
  const q = (filters.value.query||'').toLowerCase();
  return q ? list.filter(r => r.title.toLowerCase().includes(q) || (r.description||'').toLowerCase().includes(q)) : list;
});

const filteredPlans = computed(()=>{
  const q = planQuery.value.toLowerCase();
  return q ? plans.value.filter(p=> p.name.toLowerCase().includes(q)) : plans.value;
});

async function loadPlans(){
  const { data } = await api.get('/plans');
  plans.value = data || [];
  if (!selectedPlan.value && plans.value.length) selectPlan(plans.value[0].name);
}
async function loadTasks(plan){
  tasks.value = [];
  const { data } = await api.get(`/plans/${plan}/tasks`);
  tasks.value = data || [];
}
function selectPlan(name){ selectedPlan.value = name; loadTasks(name); }
function onResetFilters(){}

// Drawer state
const drawerOpen = ref(false);
const selectedTask = ref(null);
const drawerTitle = computed(()=> selectedTask.value ? `Configure • ${selectedTask.value.title}` : 'Configure');

// —— Configure model —— //
const hasSchema = computed(()=> !!selectedTask.value?.meta?.inputs_schema);
const useJsonEditor = ref(false);
const schemaFields = computed(()=> {
  const sch = selectedTask.value?.meta?.inputs_schema;
  if (!sch || typeof sch !== 'object') return [];
  // 仅处理常见 JSON Schema 形态：properties + type + enum
  const props = sch.properties || {};
  const order = sch.uiOrder || Object.keys(props);
  return order.map(k => {
    const p = props[k] || {};
    if (Array.isArray(p.enum)) return { key:k, label:p.title || k, type:'enum', enum:p.enum, help:p.description || '' };
    if (p.type === 'boolean') return { key:k, label:p.title || k, type:'boolean', onLabel: p.onLabel || 'Enabled', help:p.description || '' };
    if (p.type === 'number' || p.type === 'integer') return { key:k, label:p.title || k, type:'number', help:p.description || '' };
    // default to string
    return { key:k, label:p.title || k, type:'string', placeholder: p.examples?.[0] || '', help:p.description || '' };
  });
});
const formModel = reactive({});
const inputsRaw = ref('{}');
const jsonError = ref('');
const priority = ref(null);
const note = ref('');

// Examples
const examples = computed(()=>{
  const ex = selectedTask.value?.meta?.examples;
  if (Array.isArray(ex)) return ex;
  return [];
});

function onTaskClick(row){ openDrawer(row); }
function openDrawer(row){
  selectedTask.value = {
    task_name: row.task_name,
    title: row.title,
    description: row.description,
    meta: row.meta || {},
  };
  // reset
  priority.value = null; note.value = '';
  // init from schema defaults if any
  if (hasSchema.value) {
    const def = selectedTask.value.meta?.defaults || {};
    Object.keys(formModel).forEach(k=> delete formModel[k]);
    for (const f of schemaFields.value) {
      formModel[f.key] = def[f.key] ?? (f.type==='boolean' ? false : (f.type==='number'? 0 : ''));
    }
    useJsonEditor.value = false;
  } else {
    const def = selectedTask.value.meta?.defaults || {};
    inputsRaw.value = JSON.stringify(def || {}, null, 2);
    useJsonEditor.value = true; // 无 schema 时默认 JSON
  }
  jsonError.value = '';
  drawerOpen.value = true;
}

function applyExample(obj){
  if (hasSchema.value && !useJsonEditor.value) {
    for (const f of schemaFields.value) {
      formModel[f.key] = (obj && Object.prototype.hasOwnProperty.call(obj, f.key)) ? obj[f.key] : formModel[f.key];
    }
  } else {
    inputsRaw.value = JSON.stringify(obj || {}, null, 2);
  }
}

// JSON 校验
watch(inputsRaw, v=>{
  if (!useJsonEditor.value) return;
  try { JSON.parse(v || '{}'); jsonError.value = ''; }
  catch(e){ jsonError.value = 'Invalid JSON: ' + e.message; }
});

function buildInputs(){
  if (hasSchema.value && !useJsonEditor.value) {
    // 从 formModel 收集
    const out = {};
    for (const f of schemaFields.value) out[f.key] = formModel[f.key];
    return out;
  }
  try { return JSON.parse(inputsRaw.value || '{}'); }
  catch { return {}; }
}

function addToQueue(){
  const inputs = buildInputs();
  addTask({
    plan_name: selectedPlan.value,
    task_name: selectedTask.value.task_name,
    inputs,
    priority: priority.value ?? null,
    note: note.value || ''
  });
  toast({ type:'success', title:'Added to queue', message:`${selectedPlan.value} / ${selectedTask.value.task_name}` });
  drawerOpen.value = false;
}

onMounted(loadPlans);
</script>

<style scoped>
.chk{ font-size:12px; color: var(--text-3); display:flex; gap:6px; align-items:center; }
</style>

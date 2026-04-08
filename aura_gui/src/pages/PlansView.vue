<template>
  <div class="page-shell plans-page">
    <section class="plans-header">
      <div class="plans-header__copy">
        <span class="eyebrow">Read Only Task Folio</span>
        <h1 class="page-title">Plans</h1>
        <p class="page-subtitle">Browse plans as indexed folders and tasks as dossier slips. This page should feel archival, not operational.</p>
      </div>
    </section>

    <section class="folio-board">
      <aside class="folio-board__index">
        <div>
          <span class="label">Plan Index</span>
          <input v-model="planQuery" class="input" placeholder="Search plans" />
        </div>

        <div class="folio-board__index-list">
          <button
            v-for="plan in filteredPlans"
            :key="plan.name"
            class="plan-folder"
            :class="{ 'is-active': selectedPlan === plan.name }"
            @click="selectPlan(plan.name)"
          >
            <strong>{{ plan.name }}</strong>
            <span>{{ plan.task_count }} tasks</span>
            <span>{{ plan.task_error_count }} errors</span>
          </button>
        </div>
      </aside>

      <div class="folio-board__content">
        <section class="task-strip">
          <div class="task-strip__head">
            <div>
              <span class="label">Task Strip</span>
              <strong class="task-strip__title">{{ selectedPlan || 'Tasks' }}</strong>
            </div>
            <button class="btn btn-ghost" @click="refreshAll">Refresh</button>
          </div>

          <input v-model="taskQuery" class="input" placeholder="Search tasks" />

          <div class="task-strip__list">
            <button
              v-for="task in filteredTasks"
              :key="task.task_ref"
              class="task-slip"
              :class="{ 'is-active': selectedTaskRef === task.task_ref }"
              @click="selectedTaskRef = task.task_ref"
            >
              <span class="task-slip__title">{{ task.meta?.title || task.task_ref }}</span>
              <code>{{ task.task_ref }}</code>
            </button>
          </div>
        </section>

        <section class="dossier-sheet">
          <div v-if="selectedTask" class="dossier-sheet__body">
            <header class="dossier-sheet__head">
              <div>
                <span class="label">Task Dossier</span>
                <strong class="dossier-sheet__title">{{ selectedTask.meta?.title || selectedTask.task_ref }}</strong>
              </div>
              <div class="dossier-sheet__pills">
                <span class="pill">{{ selectedTask.plan_name }}</span>
                <span v-if="selectedTask.meta?.entry_point" class="pill">{{ selectedTask.meta.entry_point }}</span>
                <span v-if="selectedTask.meta?.concurrency" class="pill">{{ selectedTask.meta.concurrency }}</span>
              </div>
            </header>

            <code>{{ selectedTask.task_ref }}</code>
            <p class="dossier-sheet__desc">{{ selectedTask.meta?.description || 'No description provided.' }}</p>

            <div class="dossier-sheet__grid">
              <section class="dossier-block">
                <span class="label">Inputs</span>
                <table class="simple-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Type</th>
                      <th>Required</th>
                      <th>Default</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="input in taskInputs" :key="input.name">
                      <td>{{ input.name }}</td>
                      <td>{{ input.type || '-' }}</td>
                      <td>{{ input.required ? 'Yes' : 'No' }}</td>
                      <td>{{ stringify(input.default) }}</td>
                    </tr>
                    <tr v-if="!taskInputs.length">
                      <td colspan="4" class="empty-cell">This task has no declared input slots.</td>
                    </tr>
                  </tbody>
                </table>
              </section>

              <section v-if="selectedTask.definition?.steps" class="dossier-block">
                <span class="label">Step Preview</span>
                <div class="step-slips">
                  <div v-for="(step, id) in selectedTask.definition.steps" :key="id" class="step-slip">
                    <code>{{ id }}</code>
                    <strong>{{ step.action || '-' }}</strong>
                  </div>
                </div>
              </section>
            </div>

            <div v-if="taskErrors.length" class="error-notes">
              <span class="label">Load Errors</span>
              <div v-for="(error, index) in taskErrors" :key="index" class="error-notes__item">{{ stringify(error) }}</div>
            </div>
          </div>

          <div v-else class="empty-state">Select a task slip to inspect its dossier.</div>
        </section>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import axios from 'axios'
import { getGuiConfig } from '../config.js'

const cfg = getGuiConfig()
const api = axios.create({
  baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: cfg?.api?.timeout_ms || 5000,
})

const plans = ref([])
const tasks = ref([])
const taskErrors = ref([])
const selectedPlan = ref('')
const selectedTaskRef = ref('')
const planQuery = ref('')
const taskQuery = ref('')

const filteredPlans = computed(() => {
  const q = planQuery.value.trim().toLowerCase()
  return plans.value.filter((plan) => !q || plan.name.toLowerCase().includes(q))
})

const filteredTasks = computed(() => {
  const q = taskQuery.value.trim().toLowerCase()
  return tasks.value.filter((task) => {
    if (!q) return true
    return `${task.task_ref} ${task.meta?.title || ''} ${task.meta?.description || ''}`.toLowerCase().includes(q)
  })
})

const selectedTask = computed(() =>
  filteredTasks.value.find((task) => task.task_ref === selectedTaskRef.value) ||
  filteredTasks.value[0] ||
  null
)

const taskInputs = computed(() => Array.isArray(selectedTask.value?.meta?.inputs) ? selectedTask.value.meta.inputs : [])

async function loadPlans() {
  const { data } = await api.get('/plans')
  plans.value = Array.isArray(data) ? data : []
  if (!selectedPlan.value && plans.value.length) {
    selectedPlan.value = plans.value[0].name
  }
}

async function loadTasks(planName) {
  if (!planName) {
    tasks.value = []
    taskErrors.value = []
    selectedTaskRef.value = ''
    return
  }

  const [taskResponse, errorResponse] = await Promise.all([
    api.get(`/plans/${planName}/tasks`).catch(() => ({ data: [] })),
    api.get(`/plans/${planName}/task-load-errors`).catch(() => ({ data: [] })),
  ])

  tasks.value = Array.isArray(taskResponse.data) ? taskResponse.data : []
  taskErrors.value = Array.isArray(errorResponse.data) ? errorResponse.data : []
  selectedTaskRef.value = tasks.value[0]?.task_ref || ''
}

async function selectPlan(planName) {
  selectedPlan.value = planName
  await loadTasks(planName)
}

async function refreshAll() {
  await loadPlans()
  await loadTasks(selectedPlan.value)
}

function stringify(value) {
  if (value === undefined || value === null || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

onMounted(refreshAll)
</script>

<style scoped>
.plans-page {
  gap: 20px;
}

.plans-header {
  padding: 18px;
  border: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(59, 68, 72, 0.92), rgba(39, 46, 49, 0.92));
  box-shadow: var(--shadow-plate), var(--shadow-inset);
}

.folio-board {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 18px;
  min-height: calc(100vh - 250px);
}

.folio-board__index,
.task-strip,
.dossier-sheet {
  border: 1px solid rgba(224, 214, 186, 0.1);
  background: linear-gradient(180deg, rgba(56, 64, 68, 0.94), rgba(37, 45, 48, 0.94));
  box-shadow: var(--shadow-plate), var(--shadow-inset);
}

.folio-board__index {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
}

.folio-board__index-list,
.task-strip__list {
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: 10px;
  overflow: auto;
  padding-right: 6px;
}

.folio-board__content {
  display: grid;
  grid-template-rows: 260px minmax(0, 1fr);
  gap: 18px;
  min-height: 0;
}

.task-strip {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 12px;
  padding: 16px;
}

.task-strip__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: end;
}

.task-strip__title,
.dossier-sheet__title,
.plan-folder strong,
.task-slip__title {
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 30px;
  letter-spacing: 0.08em;
  line-height: 0.9;
  text-transform: uppercase;
}

.plan-folder,
.task-slip {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  border: 1px solid rgba(224, 214, 186, 0.1);
  background: rgba(25, 31, 33, 0.32);
  color: var(--text-main);
  text-align: left;
  cursor: pointer;
}

.plan-folder.is-active,
.task-slip.is-active {
  border-color: rgba(199, 104, 63, 0.22);
  background: linear-gradient(90deg, rgba(199, 104, 63, 0.14), rgba(25, 31, 33, 0.4));
}

.plan-folder span,
.task-slip code {
  color: var(--text-soft);
  font-size: 12px;
}

.dossier-sheet {
  min-height: 0;
  padding: 16px;
}

.dossier-sheet__body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
}

.dossier-sheet__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: start;
  flex-wrap: wrap;
}

.dossier-sheet__pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.dossier-sheet__desc {
  margin: 0;
  color: var(--text-soft);
  line-height: 1.7;
}

.dossier-sheet__grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(280px, 0.85fr);
  gap: 14px;
}

.dossier-block,
.error-notes {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid rgba(224, 214, 186, 0.1);
  background: rgba(25, 31, 33, 0.32);
}

.step-slips {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.step-slip {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid rgba(224, 214, 186, 0.08);
  background: rgba(18, 22, 24, 0.28);
}

.error-notes__item {
  color: #e8c1bb;
  font-size: 12px;
  line-height: 1.6;
}
</style>

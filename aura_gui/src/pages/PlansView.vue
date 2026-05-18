<template>
  <div class="page-shell tasks-page">
    <div class="page-heading">
      <div class="heading-block">
        <h1 class="page-title">任务库</h1>
      </div>
      <div class="heading-actions">
        <button class="btn btn-ghost" @click="refreshAll">
          <RefreshCw class="icon" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="pageError" class="notice notice-danger">{{ pageError }}</div>

    <section class="library-grid">
      <aside class="panel library-index">
        <header class="panel-header">
          <div>
            <span class="panel-kicker">索引</span>
            <strong>Plans / Tasks</strong>
          </div>
        </header>

        <div class="panel-body stack">
          <input v-model="planQuery" class="input" placeholder="搜索计划" />
          <div class="plan-list">
            <button
              v-for="plan in filteredPlans"
              :key="plan.name"
              class="plan-row"
              :class="{ 'is-active': selectedPlan === plan.name }"
              @click="selectPlan(plan.name)"
            >
              <span>
                <strong>{{ plan.name }}</strong>
                <small>{{ plan.taskCount }} 个任务</small>
              </span>
              <span v-if="plan.taskErrorCount" class="pill pill-red">{{ plan.taskErrorCount }}</span>
            </button>
            <div v-if="!filteredPlans.length" class="empty-state">没有匹配的计划。</div>
          </div>

          <input v-model="taskQuery" class="input" placeholder="搜索任务" />
          <div class="task-list">
            <button
              v-for="task in filteredTasks"
              :key="task.key"
              class="task-row"
              :class="{ 'is-active': selectedTaskKey === task.key }"
              @click="selectedTaskKey = task.key"
            >
              <strong>{{ task.title }}</strong>
              <code>{{ task.taskRef }}</code>
            </button>
            <div v-if="loadingTasks" class="empty-state">正在加载任务...</div>
            <div v-else-if="!filteredTasks.length" class="empty-state">没有匹配的任务。</div>
          </div>
        </div>
      </aside>

      <section class="panel task-detail">
        <header class="panel-header">
          <div>
            <span class="panel-kicker">任务详情</span>
            <strong>{{ selectedTask?.title || '未选择任务' }}</strong>
          </div>
          <div v-if="selectedTask" class="toolbar">
            <span class="pill pill-gray">{{ selectedTask.planName }}</span>
            <span v-if="selectedTask.entryPoint" class="pill pill-gray">{{ selectedTask.entryPoint }}</span>
            <span v-if="selectedTask.concurrency" class="pill pill-gray">{{ selectedTask.concurrency }}</span>
          </div>
        </header>

        <div class="panel-body">
          <template v-if="selectedTask">
            <div class="tabs detail-tabs">
              <button v-for="tab in tabs" :key="tab.key" class="tab" :class="{ 'is-active': activeTab === tab.key }" @click="activeTab = tab.key">
                {{ tab.label }}
              </button>
            </div>

            <section v-if="activeTab === 'overview'" class="detail-section">
              <div class="meta-grid">
                <div class="meta-card"><span>计划</span><code>{{ selectedTask.planName }}</code></div>
                <div class="meta-card"><span>任务引用</span><code>{{ selectedTask.taskRef }}</code></div>
                <div class="meta-card"><span>输入字段</span><code>{{ taskInputs.length }}</code></div>
                <div class="meta-card"><span>步骤</span><code>{{ stepRows.length }}</code></div>
              </div>
              <p v-if="selectedTask.description" class="description">{{ selectedTask.description }}</p>

              <details class="raw-block">
                <summary>完整 definition</summary>
                <pre class="json">{{ pretty(selectedTask.definition || {}) }}</pre>
              </details>
            </section>

            <section v-else-if="activeTab === 'inputs'" class="detail-section">
              <table>
                <thead>
                  <tr>
                    <th>字段</th>
                    <th>类型</th>
                    <th>必填</th>
                    <th>默认值</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="input in taskInputs" :key="input.name">
                    <td><code>{{ input.name }}</code></td>
                    <td>{{ input.type || '-' }}</td>
                    <td>{{ input.required ? '是' : '否' }}</td>
                    <td>{{ compact(input.default) }}</td>
                  </tr>
                  <tr v-if="!taskInputs.length">
                    <td colspan="4" class="empty-cell">该任务没有声明输入字段。</td>
                  </tr>
                </tbody>
              </table>

              <details class="raw-block">
                <summary>输入 schema 原始 JSON</summary>
                <pre class="json">{{ pretty(selectedTask.inputs || []) }}</pre>
              </details>
            </section>

            <section v-else-if="activeTab === 'steps'" class="detail-section">
              <table>
                <thead>
                  <tr>
                    <th>步骤</th>
                    <th>Action</th>
                    <th>依赖</th>
                    <th>参数数</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in actionSchemaRows" :key="row.id">
                    <td><code>{{ row.id }}</code></td>
                    <td>{{ row.action || '-' }}</td>
                    <td>{{ row.dependsOn.length ? row.dependsOn.join(', ') : '入口' }}</td>
                    <td>{{ row.parameters.length }}</td>
                  </tr>
                  <tr v-if="!actionSchemaRows.length">
                    <td colspan="4" class="empty-cell">该任务没有步骤定义。</td>
                  </tr>
                </tbody>
              </table>

              <details class="raw-block">
                <summary>Action schema 详情</summary>
                <pre class="json">{{ pretty(actionSchemaRows) }}</pre>
              </details>
            </section>

            <section v-else class="detail-section">
              <div class="toolbar">
                <button class="btn btn-ghost" :disabled="checking || !apiTokenConfigured" @click="validateSelectedTask">Validate</button>
                <button class="btn btn-primary" :disabled="checking || !apiTokenConfigured" @click="dryRunSelectedTask">Dry-run</button>
              </div>
              <div v-if="!apiTokenConfigured" class="notice">Local API token required. Configure it in Settings.</div>

              <div v-if="validationResult" class="result-block">
                <span class="label">Validate Result</span>
                <details open>
                  <summary>原始 JSON</summary>
                  <pre class="json">{{ pretty(validationResult) }}</pre>
                </details>
              </div>

              <div v-if="dryRunResult" class="result-block">
                <span class="label">Dry-run Result</span>
                <details open>
                  <summary>原始 JSON</summary>
                  <pre class="json">{{ pretty(dryRunResult) }}</pre>
                </details>
              </div>

              <div v-if="taskErrors.length" class="result-block">
                <span class="label">加载错误</span>
                <div v-for="(item, index) in taskErrors" :key="index" class="notice notice-danger">
                  {{ item.message || compact(item.raw || item) }}
                </div>
              </div>
            </section>
          </template>

          <div v-else class="empty-state">请选择一个任务。</div>
        </div>
      </section>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { RefreshCw } from 'lucide-vue-next'

import { listActions, listPlans, listTaskLoadErrors, listTasks } from '../api/plans.js'
import { dryRunTask, validateTask } from '../api/tasks.js'
import { errorMessage } from '../api/errors.js'
import { useApiTokenStatus } from '../composables/useApiToken.js'
import { normalizeInputSchema } from '../utils/inputSchema.js'

const tabs = [
  { key: 'overview', label: '概览' },
  { key: 'inputs', label: '输入' },
  { key: 'steps', label: '步骤' },
  { key: 'verify', label: '验证' },
]

const plans = ref([])
const tasks = ref([])
const taskErrors = ref([])
const actions = ref([])
const selectedPlan = ref('')
const selectedTaskKey = ref('')
const planQuery = ref('')
const taskQuery = ref('')
const activeTab = ref('overview')
const loadingTasks = ref(false)
const checking = ref(false)
const pageError = ref('')
const validationResult = ref(null)
const dryRunResult = ref(null)
const { hasToken: apiTokenConfigured } = useApiTokenStatus()

const filteredPlans = computed(() => {
  const q = planQuery.value.trim().toLowerCase()
  return plans.value.filter((plan) => !q || plan.name.toLowerCase().includes(q))
})

const filteredTasks = computed(() => {
  const q = taskQuery.value.trim().toLowerCase()
  return tasks.value.filter((task) => {
    if (!q) return true
    return `${task.title} ${task.taskRef} ${task.description}`.toLowerCase().includes(q)
  })
})

const selectedTask = computed(() =>
  tasks.value.find((task) => task.key === selectedTaskKey.value) ||
  filteredTasks.value[0] ||
  null
)

const taskInputs = computed(() =>
  (selectedTask.value?.inputs || []).map((input) => normalizeInputSchema(input))
)

const stepRows = computed(() => selectedTask.value?.steps || [])

const actionSchemaRows = computed(() =>
  stepRows.value.map((step) => {
    const action = actions.value.find((item) =>
      item.fqid === step.action ||
      item.name === step.action ||
      item.fqid?.endsWith(`/${step.action}`) ||
      item.fqid?.endsWith(`.${step.action}`)
    )
    return {
      ...step,
      parameters: Array.isArray(action?.parameters) ? action.parameters : [],
      actionMeta: action || null,
    }
  })
)

async function refreshAll() {
  try {
    const [loadedPlans, loadedActions] = await Promise.all([
      listPlans(),
      listActions().catch(() => []),
    ])
    plans.value = loadedPlans
    actions.value = loadedActions
    if (!loadedPlans.some((plan) => plan.name === selectedPlan.value)) {
      selectedPlan.value = loadedPlans.find((plan) => plan.taskCount > 0)?.name || loadedPlans[0]?.name || ''
    }
    await loadSelectedPlan()
    pageError.value = ''
  } catch (error) {
    pageError.value = errorMessage(error, '任务库加载失败。')
  }
}

async function selectPlan(planName) {
  if (selectedPlan.value === planName) return
  selectedPlan.value = planName
  await loadSelectedPlan()
}

async function loadSelectedPlan() {
  if (!selectedPlan.value) {
    tasks.value = []
    taskErrors.value = []
    selectedTaskKey.value = ''
    return
  }
  loadingTasks.value = true
  validationResult.value = null
  dryRunResult.value = null
  try {
    const [loadedTasks, loadedErrors] = await Promise.all([
      listTasks(selectedPlan.value),
      listTaskLoadErrors(selectedPlan.value).catch(() => []),
    ])
    tasks.value = loadedTasks
    taskErrors.value = loadedErrors
    if (!loadedTasks.some((task) => task.key === selectedTaskKey.value)) {
      selectedTaskKey.value = loadedTasks[0]?.key || ''
    }
  } catch (error) {
    tasks.value = []
    taskErrors.value = []
    selectedTaskKey.value = ''
    pageError.value = errorMessage(error, '任务加载失败。')
  } finally {
    loadingTasks.value = false
  }
}

async function validateSelectedTask() {
  if (!selectedTask.value) return
  if (!apiTokenConfigured.value) {
    validationResult.value = {
      status: 'error',
      errorSummary: 'Local API token required. Configure it in Settings.',
    }
    return
  }
  checking.value = true
  try {
    validationResult.value = await validateTask({
      planName: selectedTask.value.planName,
      taskRef: selectedTask.value.taskRef,
      strict: false,
    })
  } catch (error) {
    validationResult.value = { status: 'error', errorSummary: errorMessage(error) }
  } finally {
    checking.value = false
  }
}

async function dryRunSelectedTask() {
  if (!selectedTask.value) return
  if (!apiTokenConfigured.value) {
    dryRunResult.value = {
      status: 'error',
      errorSummary: 'Local API token required. Configure it in Settings.',
    }
    return
  }
  checking.value = true
  try {
    dryRunResult.value = await dryRunTask({
      planName: selectedTask.value.planName,
      taskRef: selectedTask.value.taskRef,
      strict: false,
    })
  } catch (error) {
    dryRunResult.value = { status: 'error', errorSummary: errorMessage(error) }
  } finally {
    checking.value = false
  }
}

function pretty(value) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function compact(value) {
  if (value === undefined) return '--'
  if (value === null) return 'null'
  if (typeof value === 'string') return value || '--'
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

onMounted(refreshAll)
</script>

<style scoped>
.library-grid {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}

.library-index,
.task-detail {
  min-width: 0;
}

.plan-list,
.task-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.plan-row,
.task-row {
  display: flex;
  width: 100%;
  min-width: 0;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  padding: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-surface-2);
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
}

.plan-row:hover,
.task-row:hover,
.plan-row.is-active,
.task-row.is-active {
  border-color: var(--border-strong);
  background: var(--bg-elevated);
}

.plan-row.is-active,
.task-row.is-active {
  box-shadow: inset 3px 0 0 var(--accent);
}

.plan-row span,
.task-row {
  min-width: 0;
}

.plan-row span:first-child,
.task-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.plan-row small {
  color: var(--text-muted);
}

.detail-tabs {
  margin-bottom: 14px;
}

.detail-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.meta-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-surface-2);
}

.meta-card span {
  color: var(--text-muted);
  font-size: 12px;
}

.description {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.55;
}

.raw-block,
.result-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

summary {
  color: var(--text-secondary);
  cursor: pointer;
}

.notice {
  padding: 10px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
}

.notice-danger {
  border-color: rgba(239, 91, 91, 0.34);
  background: var(--danger-soft);
  color: #ffb4b4;
}

@media (max-width: 1120px) {
  .library-grid {
    grid-template-columns: 260px minmax(0, 1fr);
  }

  .meta-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>

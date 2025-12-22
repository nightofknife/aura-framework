<template>
  <div class="panel property-panel">
    <div class="panel-header"><strong>属性</strong></div>
    <div class="panel-body" v-if="selection.type === 'task'">
      <div class="field">
        <label>标题</label>
        <input class="input" v-model="taskMeta.title" @input="updateMeta" />
      </div>
      <div class="field">
        <label>描述</label>
        <textarea class="input" rows="3" v-model="taskMeta.description" @input="updateMeta"></textarea>
      </div>
      <div class="field">
        <label>入口任务</label>
        <input type="checkbox" v-model="taskMeta.entry_point" @change="updateMeta" />
      </div>
      <div class="field">
        <label>输入定义 (JSON)</label>
        <textarea class="input" rows="4" v-model="inputsRaw" @change="updateInputs"></textarea>
        <div v-if="inputsError" class="error">{{ inputsError }}</div>
      </div>
      <div class="field">
        <label>执行模式</label>
        <select class="select" v-model="taskExecutionMode" @change="updateTask">
          <option value="sync">同步</option>
          <option value="async">异步</option>
        </select>
      </div>
      <div class="field">
        <label>返回值 (JSON)</label>
        <textarea class="input" rows="6" v-model="returnsRaw" @change="updateReturns"></textarea>
        <div v-if="returnsError" class="error">{{ returnsError }}</div>
      </div>
    </div>

    <div class="panel-body" v-else-if="selection.type === 'node'">
      <div class="field">
        <label>动作</label>
        <input
          class="input"
          v-model="nodeAction"
          @input="updateNodeAction"
          list="action-list"
          placeholder="输入动作名称"
        />
        <datalist id="action-list">
          <option v-for="action in actions" :key="action.fqid" :value="action.name || action.fqid">
            {{ action.name || action.fqid }}
          </option>
        </datalist>
        <div v-if="!actions.length" class="hint">暂无动作列表，可直接输入动作名称。</div>
      </div>
      <div class="field">
        <label>参数</label>
        <KeyValueEditor
          :model-value="paramsValue"
          @update:modelValue="updateParams"
          :kinds="paramKinds"
          empty-text="暂无参数"
        />
      </div>
      <div class="field">
        <label>循环方式</label>
        <select class="select" v-model="loopMode" @change="updateLoop">
          <option value="none">无</option>
          <option value="for_each">遍历</option>
          <option value="times">次数</option>
          <option value="while">条件</option>
        </select>
      </div>
      <div v-if="loopMode === 'for_each'" class="field">
        <label>遍历表达式</label>
        <input class="input" v-model="loopForEach" @input="updateLoop" placeholder="{{ inputs.items }}" />
      </div>
      <div v-if="loopMode === 'times'" class="field">
        <label>循环次数</label>
        <input class="input" type="number" min="1" v-model.number="loopTimes" @input="updateLoop" />
      </div>
      <div v-if="loopMode === 'while'" class="field">
        <label>条件表达式</label>
        <input class="input" v-model="loopWhile" @input="updateLoop" placeholder="{{ state.flag }}" />
      </div>
      <div v-if="loopMode === 'while'" class="field">
        <label>最大迭代次数</label>
        <input class="input" type="number" min="1" v-model.number="loopMaxIterations" @input="updateLoop" />
      </div>
      <div v-if="loopMode !== 'none'" class="field">
        <label>并发数</label>
        <input class="input" type="number" min="1" v-model.number="loopParallelism" @input="updateLoop" />
      </div>
      <div class="field">
        <label>输出</label>
        <KeyValueEditor
          :model-value="outputsValue"
          @update:modelValue="updateOutputs"
          :kinds="outputKinds"
          empty-text="暂无输出"
        />
      </div>
      <div class="field">
        <label>重试次数</label>
        <input class="input" type="number" min="0" v-model.number="retryCount" @input="updateRetry" />
      </div>
      <div class="field">
        <label>重试间隔（秒）</label>
        <input class="input" type="number" min="0" step="0.1" v-model.number="retryDelay" @input="updateRetry" />
      </div>
      <div class="field">
        <label>异常类型（逗号分隔）</label>
        <input class="input" v-model="retryOn" @input="updateRetry" placeholder="TimeoutError, ValueError" />
      </div>
      <div class="field">
        <label>重试条件表达式</label>
        <input class="input" v-model="retryCondition" @input="updateRetry" placeholder="{{ result.status_code >= 500 }}" />
      </div>
      <div class="field actions">
        <button class="btn btn-ghost danger" @click="emit('remove-node')">删除节点</button>
      </div>
    </div>

    <div class="panel-body" v-else-if="selection.type === 'gate'">
      <div class="field">
        <label>逻辑门类型</label>
        <select class="select" v-model="gateType" @change="updateGateType">
          <option value="and">并且</option>
          <option value="or">或者</option>
          <option value="not">非</option>
          <option value="when">条件</option>
          <option value="status">状态</option>
        </select>
      </div>
      <div v-if="gateType === 'when'" class="field">
        <label>条件表达式</label>
        <input class="input" v-model="gateExpr" @input="updateGateExpr" />
      </div>
      <div v-if="gateType === 'status'" class="field">
        <label>节点 ID</label>
        <input class="input" v-model="gateNodeId" @input="updateGateStatus" />
      </div>
      <div v-if="gateType === 'status'" class="field">
        <label>状态列表（逗号分隔）</label>
        <input class="input" v-model="gateStatuses" @input="updateGateStatus" />
      </div>
      <div class="field actions">
        <button class="btn btn-ghost danger" @click="emit('remove-gate')">删除逻辑门</button>
      </div>
    </div>

    <div class="panel-body" v-else>
      <div class="empty">请选择节点或逻辑门。</div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import KeyValueEditor from './KeyValueEditor.vue'

const props = defineProps({
  selection: { type: Object, required: true },
  task: { type: Object, default: null },
  node: { type: Object, default: null },
  gate: { type: Object, default: null },
  actions: { type: Array, default: () => [] }
})

const emit = defineEmits(['update-task', 'update-node', 'update-gate', 'remove-node', 'remove-gate'])

const taskMeta = ref({})
const taskExecutionMode = ref('sync')
const returnsRaw = ref('')
const returnsError = ref('')
const inputsRaw = ref('')
const inputsError = ref('')

const nodeAction = ref('')
const paramsValue = ref({})
const outputsValue = ref({})
const loopMode = ref('none')
const loopForEach = ref('')
const loopTimes = ref(1)
const loopWhile = ref('')
const loopMaxIterations = ref(1000)
const loopParallelism = ref(null)
const retryCount = ref(0)
const retryDelay = ref(0)
const retryOn = ref('')
const retryCondition = ref('')

const paramKinds = ['string', 'number', 'boolean', 'null', 'expression', 'object', 'array']
const outputKinds = ['expression', 'string', 'number', 'boolean', 'null', 'object', 'array']

const gateType = ref('and')
const gateExpr = ref('')
const gateNodeId = ref('')
const gateStatuses = ref('')

watch(() => props.task, (value) => {
  if (!value) return
  taskMeta.value = { ...(value.meta || {}) }
  taskExecutionMode.value = value.execution_mode || 'sync'
  returnsRaw.value = value.returns ? JSON.stringify(value.returns, null, 2) : ''
  returnsError.value = ''
  inputsRaw.value = value.meta?.inputs ? JSON.stringify(value.meta.inputs, null, 2) : ''
  inputsError.value = ''
}, { immediate: true })

watch(() => props.node, (value) => {
  if (!value) return
  nodeAction.value = value.action || ''
  paramsValue.value = value.params ? JSON.parse(JSON.stringify(value.params)) : {}
  outputsValue.value = value.outputs ? JSON.parse(JSON.stringify(value.outputs)) : {}

  const loopConfig = value.loop || {}
  if (loopConfig.for_each !== undefined) {
    loopMode.value = 'for_each'
    loopForEach.value = loopConfig.for_each || ''
  } else if (loopConfig.times !== undefined) {
    loopMode.value = 'times'
    loopTimes.value = Number(loopConfig.times) || 1
  } else if (loopConfig.while !== undefined) {
    loopMode.value = 'while'
    loopWhile.value = loopConfig.while || ''
    loopMaxIterations.value = Number(loopConfig.max_iterations) || 1000
  } else {
    loopMode.value = 'none'
    loopForEach.value = ''
    loopTimes.value = 1
    loopWhile.value = ''
    loopMaxIterations.value = 1000
  }
  loopParallelism.value = loopConfig.parallelism ?? null

  const retryConfig = value.retry
  if (typeof retryConfig === 'number') {
    retryCount.value = retryConfig
    retryDelay.value = 0
    retryOn.value = ''
    retryCondition.value = ''
  } else if (retryConfig && typeof retryConfig === 'object') {
    retryCount.value = Number(retryConfig.count) || 0
    retryDelay.value = Number(retryConfig.delay ?? retryConfig.interval ?? 0) || 0
    retryOn.value = Array.isArray(retryConfig.on_exception) ? retryConfig.on_exception.join(',') : ''
    retryCondition.value = retryConfig.condition || retryConfig.retry_condition || ''
  } else {
    retryCount.value = 0
    retryDelay.value = 0
    retryOn.value = ''
    retryCondition.value = ''
  }
}, { immediate: true })

watch(() => props.gate, (value) => {
  if (!value) return
  gateType.value = value.type
  gateExpr.value = value.expr || ''
  gateNodeId.value = value.node_id || ''
  gateStatuses.value = (value.statuses || []).join(',')
}, { immediate: true })

const updateMeta = () => {
  emit('update-task', { meta: { ...taskMeta.value } })
}

const updateTask = () => {
  emit('update-task', { execution_mode: taskExecutionMode.value })
}

const updateInputs = () => {
  if (!inputsRaw.value) {
    inputsError.value = ''
    taskMeta.value = { ...taskMeta.value }
    delete taskMeta.value.inputs
    emit('update-task', { meta: { ...taskMeta.value } })
    return
  }
  try {
    const parsed = JSON.parse(inputsRaw.value)
    inputsError.value = ''
    taskMeta.value = { ...taskMeta.value, inputs: parsed }
    emit('update-task', { meta: { ...taskMeta.value } })
  } catch (err) {
    inputsError.value = 'JSON 无效'
  }
}

const updateReturns = () => {
  if (!returnsRaw.value) {
    returnsError.value = ''
    emit('update-task', { returns: undefined })
    return
  }
  try {
    const parsed = JSON.parse(returnsRaw.value)
    returnsError.value = ''
    emit('update-task', { returns: parsed })
  } catch (err) {
    returnsError.value = 'JSON 无效'
  }
}

const updateNodeAction = () => {
  emit('update-node', { action: nodeAction.value })
}

const updateParams = (value) => {
  const payload = value && Object.keys(value).length ? value : undefined
  paramsValue.value = value || {}
  emit('update-node', { params: payload })
}

const updateOutputs = (value) => {
  const payload = value && Object.keys(value).length ? value : undefined
  outputsValue.value = value || {}
  emit('update-node', { outputs: payload })
}

const updateLoop = () => {
  if (loopMode.value === 'none') {
    emit('update-node', { loop: undefined })
    return
  }
  const config = {}
  if (loopMode.value === 'for_each') {
    config.for_each = loopForEach.value || ''
  }
  if (loopMode.value === 'times') {
    config.times = Number(loopTimes.value) || 1
  }
  if (loopMode.value === 'while') {
    config.while = loopWhile.value || ''
    if (loopMaxIterations.value) {
      config.max_iterations = Number(loopMaxIterations.value) || 1000
    }
  }
  if (loopParallelism.value) {
    config.parallelism = Number(loopParallelism.value) || 1
  }
  emit('update-node', { loop: config })
}

const updateRetry = () => {
  const count = Number(retryCount.value) || 0
  const delay = Number(retryDelay.value) || 0
  const onException = retryOn.value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  const condition = retryCondition.value.trim()

  if (!count && !delay && onException.length === 0 && !condition) {
    emit('update-node', { retry: undefined })
    return
  }

  const config = { count, delay }
  if (onException.length) config.on_exception = onException
  if (condition) config.condition = condition
  emit('update-node', { retry: config })
}

const updateGateType = () => emit('update-gate', { type: gateType.value })
const updateGateExpr = () => emit('update-gate', { expr: gateExpr.value })
const updateGateStatus = () => {
  const statuses = gateStatuses.value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  emit('update-gate', { node_id: gateNodeId.value, statuses })
}
</script>

<style scoped>
.property-panel { min-width: 280px; }
.field { display: grid; gap: 6px; margin-bottom: 12px; }
.field.actions { margin-top: 16px; }
.danger {
  color: var(--error);
  border-color: rgba(220, 38, 38, 0.4);
}
.danger:hover {
  background: rgba(220, 38, 38, 0.08);
  color: var(--error);
}
.field label { font-size: 12px; color: var(--text-secondary); }
.error { font-size: 12px; color: var(--error); }
.hint { font-size: 12px; color: var(--text-secondary); }
.empty { color: var(--text-secondary); font-size: 13px; }
</style>

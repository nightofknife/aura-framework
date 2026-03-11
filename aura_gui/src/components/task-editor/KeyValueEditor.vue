<template>
  <div class="kv-editor">
    <div v-if="!entries.length" class="empty">{{ emptyText }}</div>

    <div v-for="(entry, index) in entries" :key="entry.id" class="kv-row">
      <div v-if="isObjectMode" class="cell key">
        <input class="input" v-model="entry.key" :placeholder="keyPlaceholder" @input="emitChange" />
      </div>
      <div v-else class="cell index">#{{ index + 1 }}</div>

      <div class="cell type">
        <select class="select" v-model="entry.kind" @change="onKindChange(entry)">
          <option v-for="option in kindOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>

      <div class="cell value">
        <template v-if="entry.kind === 'string'">
          <input class="input" v-model="entry.value" :placeholder="valuePlaceholder" @input="emitChange" />
        </template>
        <template v-else-if="entry.kind === 'number'">
          <input class="input" type="number" v-model.number="entry.value" @input="emitChange" />
        </template>
        <template v-else-if="entry.kind === 'boolean'">
          <select class="select" v-model="entry.value" @change="emitChange">
            <option :value="true">是</option>
            <option :value="false">否</option>
          </select>
        </template>
        <template v-else-if="entry.kind === 'null'">
          <div class="null-value">空</div>
        </template>
        <template v-else-if="entry.kind === 'expression'">
          <input class="input" v-model="entry.value" placeholder="表达式，如 {{ inputs.value }}" @input="emitChange" />
        </template>
        <template v-else-if="entry.kind === 'object'">
          <KeyValueEditor
            v-model="entry.value"
            mode="object"
            :kinds="kinds"
            empty-text="暂无子项"
            key-placeholder="字段名"
            value-placeholder="值"
          />
        </template>
        <template v-else-if="entry.kind === 'array'">
          <KeyValueEditor
            v-model="entry.value"
            mode="array"
            :kinds="kinds"
            empty-text="暂无项"
            key-placeholder="字段名"
            value-placeholder="值"
          />
        </template>
      </div>

      <div class="cell action">
        <button class="btn btn-ghost btn-mini" @click="removeEntry(entry.id)">删除</button>
      </div>
    </div>

    <div class="kv-footer">
      <button class="btn btn-ghost btn-mini" @click="addEntry">{{ addLabel }}</button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { nanoid } from 'nanoid'

defineOptions({ name: 'KeyValueEditor' })

const props = defineProps({
  modelValue: { type: [Object, Array], default: () => ({}) },
  mode: { type: String, default: 'object' },
  kinds: {
    type: Array,
    default: () => ['string', 'number', 'boolean', 'null', 'expression', 'object', 'array']
  },
  emptyText: { type: String, default: '暂无参数' },
  keyPlaceholder: { type: String, default: '参数名' },
  valuePlaceholder: { type: String, default: '值' }
})

const emit = defineEmits(['update:modelValue'])

const isObjectMode = computed(() => props.mode !== 'array')

const kindLabels = {
  string: '文本',
  number: '数字',
  boolean: '布尔',
  null: '空值',
  expression: '表达式',
  object: '对象',
  array: '数组'
}

const kindOptions = computed(() => props.kinds.map((kind) => ({
  value: kind,
  label: kindLabels[kind] || kind
})))

const entries = ref([])
let syncing = false

const inferKind = (value) => {
  if (value === null) return 'null'
  if (Array.isArray(value)) return 'array'
  if (typeof value === 'object') return 'object'
  if (typeof value === 'number') return 'number'
  if (typeof value === 'boolean') return 'boolean'
  if (typeof value === 'string') {
    if (value.includes('{{') && value.includes('}}')) return 'expression'
    return 'string'
  }
  return 'string'
}

const normalizeValue = (kind) => {
  if (kind === 'null') return null
  if (kind === 'number') return 0
  if (kind === 'boolean') return false
  if (kind === 'expression' || kind === 'string') return ''
  if (kind === 'array') return []
  if (kind === 'object') return {}
  return ''
}

const toEntry = (key, value) => ({
  id: nanoid(6),
  key: key || '',
  kind: inferKind(value),
  value: value
})

const toEntries = (value) => {
  if (props.mode === 'array') {
    const list = Array.isArray(value) ? value : []
    return list.map((item) => toEntry('', item))
  }
  const obj = value && typeof value === 'object' ? value : {}
  return Object.entries(obj).map(([key, val]) => toEntry(key, val))
}

const toValue = (entry) => {
  if (entry.kind === 'null') return null
  if (entry.kind === 'number') {
    const num = Number(entry.value)
    if (Number.isNaN(num)) return undefined
    return num
  }
  if (entry.kind === 'boolean') return Boolean(entry.value)
  if (entry.kind === 'expression' || entry.kind === 'string') return entry.value || ''
  if (entry.kind === 'array') return Array.isArray(entry.value) ? entry.value : []
  if (entry.kind === 'object') return entry.value && typeof entry.value === 'object' ? entry.value : {}
  return undefined
}

const emitChange = () => {
  if (syncing) return
  if (props.mode === 'array') {
    emit('update:modelValue', entries.value.map((entry) => toValue(entry)).filter((v) => v !== undefined))
    return
  }

  const result = {}
  for (const entry of entries.value) {
    if (!entry.key) continue
    const value = toValue(entry)
    if (value === undefined) continue
    result[entry.key] = value
  }
  emit('update:modelValue', result)
}

const onKindChange = (entry) => {
  entry.value = normalizeValue(entry.kind)
  emitChange()
}

const addEntry = () => {
  const entry = toEntry('', '')
  if (!props.kinds.includes(entry.kind)) {
    entry.kind = props.kinds[0] || 'string'
    entry.value = normalizeValue(entry.kind)
  }
  entries.value.push(entry)
  emitChange()
}

const removeEntry = (id) => {
  entries.value = entries.value.filter((entry) => entry.id !== id)
  emitChange()
}

const addLabel = computed(() => (props.mode === 'array' ? '添加项' : '添加字段'))

watch(() => props.modelValue, (value) => {
  syncing = true
  entries.value = toEntries(value)
  Promise.resolve().then(() => {
    syncing = false
  })
}, { immediate: true, deep: true })

watch(entries, () => {
  emitChange()
}, { deep: true })
</script>

<style scoped>
.kv-editor {
  display: grid;
  gap: 8px;
}
.kv-row {
  display: grid;
  grid-template-columns: 1.2fr 120px 2fr 70px;
  gap: 8px;
  align-items: start;
}
.kv-row .cell.key { grid-column: span 1; }
.kv-row .cell.index {
  font-size: 12px;
  color: var(--text-secondary);
  padding-top: 8px;
}
.kv-row .cell.value {
  display: grid;
  gap: 8px;
}
.kv-row .cell.action { text-align: right; }
.null-value {
  font-size: 12px;
  color: var(--text-secondary);
  padding: 8px 0;
}
.kv-footer {
  display: flex;
  justify-content: flex-end;
}
.btn-mini {
  padding: 4px 10px;
  font-size: 12px;
}
.empty { color: var(--text-secondary); font-size: 13px; }
</style>

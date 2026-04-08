<template>
  <div class="input-field">
    <label v-if="normalized.label || normalized.name" class="label">
      {{ normalized.label || normalized.name }}
      <span v-if="normalized.required" class="req">*</span>
    </label>

    <template v-if="!isList">
      <RadioGroup
        v-if="widgetConfig.widget === 'radio'"
        v-model="innerValue"
        :options="normalized.enum || []"
        :layout="widgetConfig.layout || 'vertical'"
        :required="normalized.required"
        :name="normalized.name"
        :disabled="normalized.readonly"
      />

      <select
        v-else-if="isEnumSelect"
        v-model="innerValue"
        class="select"
        :disabled="normalized.readonly"
      >
        <option v-if="!normalized.required" :value="null">Not selected</option>
        <option v-for="option in normalized.enum || []" :key="option" :value="option">{{ option }}</option>
      </select>

      <label v-else-if="normalized.type === 'boolean'" class="bool-field">
        <input v-model="innerValue" type="checkbox" :disabled="normalized.readonly" />
        <span>{{ normalized.label || normalized.name }}</span>
      </label>

      <input
        v-else-if="normalized.type === 'number'"
        v-model.number="innerValue"
        class="input"
        type="number"
        :placeholder="normalized.placeholder || ''"
        :min="normalized.min"
        :max="normalized.max"
        :step="normalized.step || 'any'"
        :disabled="normalized.readonly"
      />

      <input
        v-else
        v-model="innerValue"
        class="input"
        type="text"
        :placeholder="normalized.placeholder || ''"
        :disabled="normalized.readonly"
      />
    </template>

    <template v-else>
      <CheckboxGroup
        v-if="widgetConfig.widget === 'checkbox'"
        v-model="innerValue"
        :options="normalized.enum || []"
        :min="normalized.min"
        :max="normalized.max"
        :columns="widgetConfig.columns || 1"
        :show-select-all="normalized.ui?.show_select_all"
      />

      <TagInput
        v-else-if="widgetConfig.widget === 'tag-input'"
        v-model="innerValue"
        :placeholder="normalized.placeholder || 'Press Enter to add a tag'"
      />

      <div v-else-if="isSimpleDictList" class="table-block">
        <table class="simple-table">
          <thead>
            <tr>
              <th v-for="column in tableColumns" :key="column.key">{{ column.label || column.name || column.key }}</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in listValue" :key="index">
              <td v-for="column in tableColumns" :key="column.key">
                <select
                  v-if="column.enum && column.enum.length"
                  :value="item[column.key]"
                  class="select table-input"
                  :disabled="normalized.readonly"
                  @change="updateTableItem(index, column.key, $event.target.value)"
                >
                  <option v-for="option in column.enum" :key="option" :value="option">{{ option }}</option>
                </select>

                <input
                  v-else-if="column.type === 'boolean'"
                  :checked="item[column.key]"
                  type="checkbox"
                  :disabled="normalized.readonly"
                  @change="updateTableItem(index, column.key, $event.target.checked)"
                />

                <input
                  v-else-if="column.type === 'number'"
                  :value="item[column.key]"
                  class="input table-input"
                  type="number"
                  :min="column.min"
                  :max="column.max"
                  :step="column.step || 'any'"
                  :disabled="normalized.readonly"
                  @input="updateTableItem(index, column.key, parseFloat($event.target.value))"
                />

                <input
                  v-else
                  :value="item[column.key]"
                  class="input table-input"
                  type="text"
                  :placeholder="column.placeholder || ''"
                  :disabled="normalized.readonly"
                  @input="updateTableItem(index, column.key, $event.target.value)"
                />
              </td>
              <td>
                <button type="button" class="btn btn-ghost btn-sm" @click="removeList(index)">Remove</button>
              </td>
            </tr>
            <tr v-if="listValue.length === 0">
              <td :colspan="tableColumns.length + 1" class="empty-state">No items yet.</td>
            </tr>
          </tbody>
        </table>
        <button type="button" class="btn btn-ghost btn-sm" @click="addList">Add Row</button>
      </div>

      <div v-else class="list-block">
        <div v-for="(item, index) in listValue" :key="index" class="list-row">
          <InputFieldRenderer
            :schema="normalized.item || {}"
            :model-value="item"
            @update:modelValue="updateList(index, $event)"
          />
          <button type="button" class="btn btn-ghost btn-sm" @click="removeList(index)">Remove</button>
        </div>
        <button type="button" class="btn btn-ghost btn-sm" @click="addList">Add Item</button>
      </div>
    </template>

    <div v-if="normalized.type === 'dict'" class="dict-block">
      <InputFieldRenderer
        v-for="(child, key) in normalized.properties || {}"
        :key="key"
        :schema="{ ...child, name: child.name || key, label: child.label || child.title || key }"
        :model-value="(innerValue || {})[key]"
        @update:modelValue="(value) => updateDict(key, value)"
      />
    </div>

    <div v-if="normalized.description" class="hint">{{ normalized.description }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { buildDefaultFromSchema, cloneDeep, cloneInputs, normalizeInputSchema } from '../utils/inputSchema.js'
import { inferWidget } from '../utils/widgetInference.js'
import RadioGroup from './widgets/RadioGroup.vue'
import CheckboxGroup from './widgets/CheckboxGroup.vue'
import TagInput from './widgets/TagInput.vue'

const props = defineProps({
  schema: { type: Object, required: true },
  modelValue: { type: [String, Number, Boolean, Object, Array, null], default: null },
})

const emit = defineEmits(['update:modelValue'])
const normalized = computed(() => normalizeInputSchema(props.schema || {}))
const widgetConfig = computed(() => inferWidget(normalized.value))
const isList = computed(() => {
  const type = normalized.value.type || 'string'
  return type === 'list' || type.startsWith('list<')
})

const isEnumSelect = computed(() => {
  const schema = normalized.value || {}
  if (!Array.isArray(schema.enum) || schema.enum.length === 0 || isList.value) {
    return false
  }
  return widgetConfig.value.widget !== 'radio'
})

const isSimpleDictList = computed(() => {
  if (normalized.value.type !== 'list') return false
  const itemSchema = normalized.value.item
  if (!itemSchema || itemSchema.type !== 'dict') return false
  const properties = itemSchema.properties || {}
  const keys = Object.keys(properties)
  if (!keys.length) return false
  return keys.every((key) => {
    const prop = properties[key]
    return ['string', 'number', 'boolean'].includes(prop.type || 'string') || !!prop.enum
  })
})

const tableColumns = computed(() => {
  if (!isSimpleDictList.value) return []
  return Object.keys(normalized.value.item?.properties || {}).map((key) => ({
    key,
    ...normalizeInputSchema(normalized.value.item.properties[key]),
  }))
})

const innerValue = computed({
  get() {
    if (props.modelValue === undefined) {
      return buildDefaultFromSchema(normalized.value)
    }
    return props.modelValue
  },
  set(value) {
    emit('update:modelValue', value)
  },
})

const listValue = computed(() => (Array.isArray(innerValue.value) ? innerValue.value : []))

function addList() {
  emit('update:modelValue', [...listValue.value, buildDefaultFromSchema(normalized.value.item || {})])
}

function removeList(index) {
  const next = listValue.value.slice()
  next.splice(index, 1)
  emit('update:modelValue', next)
}

function updateList(index, value) {
  const next = listValue.value.slice()
  next[index] = value
  emit('update:modelValue', next)
}

function updateDict(key, value) {
  const next = props.modelValue && typeof props.modelValue === 'object' ? cloneInputs(props.modelValue) : {}
  next[key] = value
  emit('update:modelValue', next)
}

function updateTableItem(index, key, value) {
  const next = cloneDeep(listValue.value)
  if (!next[index]) next[index] = {}
  next[index][key] = value
  emit('update:modelValue', next)
}
</script>

<style scoped>
.input-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.req {
  color: var(--ember-bright);
}

.bool-field {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-main);
}

.bool-field input {
  width: 16px;
  height: 16px;
}

.dict-block,
.list-block {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.dict-block {
  margin-top: 8px;
  padding-left: 14px;
  border-left: 1px solid var(--line);
}

.list-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
}

.table-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.table-input {
  min-height: 38px;
}
</style>

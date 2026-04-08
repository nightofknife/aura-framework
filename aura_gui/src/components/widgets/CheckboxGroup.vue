<template>
  <div class="checkbox-wrapper">
    <div v-if="showSelectAll" class="checkbox-controls">
      <button type="button" class="btn btn-ghost btn-sm" @click="selectAll">Select All</button>
      <button type="button" class="btn btn-ghost btn-sm" @click="clearAll">Clear</button>
    </div>

    <div :class="['checkbox-group', `columns-${columns}`]">
      <label v-for="option in options" :key="option" class="checkbox-item">
        <input
          type="checkbox"
          :value="option"
          :checked="selectedValues.includes(option)"
          :disabled="isDisabled(option)"
          @change="toggleCheckbox(option)"
        />
        <span>{{ option }}</span>
      </label>
    </div>

    <div v-if="min != null || max != null" class="hint">{{ countHintText }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { getCountHintText } from '../../utils/widgetInference.js'

const props = defineProps({
  options: { type: Array, required: true },
  modelValue: { type: Array, default: () => [] },
  min: { type: Number, default: undefined },
  max: { type: Number, default: undefined },
  columns: { type: Number, default: 1 },
  showSelectAll: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])
const selectedValues = computed(() => props.modelValue || [])
const countHintText = computed(() => getCountHintText(selectedValues.value.length, props.min, props.max))

function isDisabled(option) {
  if (selectedValues.value.includes(option)) return false
  return props.max !== undefined && selectedValues.value.length >= props.max
}

function toggleCheckbox(option) {
  const next = [...selectedValues.value]
  const index = next.indexOf(option)

  if (index > -1) {
    if (props.min !== undefined && next.length <= props.min) return
    next.splice(index, 1)
  } else {
    if (props.max !== undefined && next.length >= props.max) return
    next.push(option)
  }

  emit('update:modelValue', next)
}

function selectAll() {
  emit('update:modelValue', props.max !== undefined ? props.options.slice(0, props.max) : [...props.options])
}

function clearAll() {
  emit('update:modelValue', [])
}
</script>

<style scoped>
.checkbox-wrapper {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.checkbox-controls {
  display: flex;
  gap: 8px;
}

.checkbox-group {
  display: grid;
  gap: 10px;
}

.checkbox-group.columns-1 {
  grid-template-columns: 1fr;
}

.checkbox-group.columns-2 {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.checkbox-group.columns-3 {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.checkbox-item {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  padding: 0 12px;
  border: 1px solid var(--line);
  background: rgba(8, 20, 32, 0.72);
  color: var(--smoke);
  clip-path: polygon(8px 0, 100% 0, calc(100% - 8px) 100%, 0 100%);
}

.checkbox-item input {
  margin: 0;
}
</style>

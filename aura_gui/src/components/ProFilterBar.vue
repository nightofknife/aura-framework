<template>
  <div class="filterbar">
    <input
      v-model="local.query"
      class="input filterbar__search"
      placeholder="Search plan, task, or cid"
      @input="debouncedEmitChange"
    />

    <select v-if="statusOptions?.length" v-model="local.status" class="select" @change="emitChange">
      <option value="">All statuses</option>
      <option v-for="status in statusOptions" :key="status" :value="status">{{ status }}</option>
    </select>

    <select v-if="planOptions?.length" v-model="local.plan" class="select" @change="emitChange">
      <option value="">All plans</option>
      <option v-for="plan in planOptions" :key="plan" :value="plan">{{ plan }}</option>
    </select>

    <slot />

    <button class="btn btn-ghost filterbar__reset" @click="onReset">Reset</button>
  </div>
</template>

<script setup>
import { reactive, watch } from 'vue'
import { useDebounceFn } from '@vueuse/core'

const props = defineProps({
  modelValue: { type: Object, default: () => ({ query: '', status: '', plan: '' }) },
  statusOptions: { type: Array, default: () => [] },
  planOptions: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue', 'reset'])
const local = reactive({ ...props.modelValue })

watch(() => props.modelValue, (value) => Object.assign(local, value))

function emitChange() {
  emit('update:modelValue', { ...local })
}

const debouncedEmitChange = useDebounceFn(emitChange, 240)

function onReset() {
  Object.assign(local, { query: '', status: '', plan: '' })
  emitChange()
  emit('reset')
}
</script>

<style scoped>
.filterbar {
  display: grid;
  grid-template-columns: minmax(260px, 1.5fr) repeat(2, minmax(170px, 0.8fr)) auto auto;
  gap: 10px;
  align-items: center;
  padding: 12px;
  border: 1px solid var(--line);
  background:
    linear-gradient(180deg, rgba(64, 73, 77, 0.9), rgba(43, 51, 54, 0.9));
  box-shadow: var(--shadow-inset);
}

.filterbar__reset {
  justify-self: end;
}
</style>

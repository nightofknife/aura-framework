<template>
  <div class="filterbar">
    <input
      v-model="local.query"
      class="input filterbar__search"
      placeholder="搜索 plan、task 或 CID"
      @input="debouncedEmitChange"
    />

    <select v-if="statusOptions?.length" v-model="local.status" class="select" @change="emitChange">
      <option value="">全部状态</option>
      <option v-for="status in statusOptions" :key="status" :value="status">{{ statusLabel(status) }}</option>
    </select>

    <select v-if="planOptions?.length" v-model="local.plan" class="select" @change="emitChange">
      <option value="">全部计划</option>
      <option v-for="plan in planOptions" :key="plan" :value="plan">{{ plan }}</option>
    </select>

    <slot />

    <button class="btn btn-ghost filterbar__reset" @click="onReset">重置</button>
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

function statusLabel(status) {
  const labels = {
    queued: '排队',
    running: '运行中',
    success: '成功',
    failed: '失败',
    cancelled: '已取消',
    unknown: '未知',
  }
  return labels[status] || status
}
</script>

<style scoped>
.filterbar {
  display: grid;
  grid-template-columns: minmax(260px, 1.5fr) repeat(2, minmax(170px, 0.8fr)) auto auto;
  gap: 10px;
  align-items: center;
  padding: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
}

.filterbar__reset {
  justify-self: end;
}

@media (max-width: 1120px) {
  .filterbar {
    grid-template-columns: minmax(0, 1fr) minmax(150px, 0.5fr) minmax(150px, 0.5fr);
  }

  .filterbar__reset {
    justify-self: start;
  }
}
</style>

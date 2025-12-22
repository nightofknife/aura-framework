<template>
  <div class="toolbar">
    <div class="left">
      <button class="btn btn-primary" @click="$emit('add-node')">添加节点</button>
      <select class="select" v-model="gateType" @change="handleAddGate">
        <option value="">添加逻辑门</option>
        <option value="and">并且</option>
        <option value="or">或者</option>
        <option value="not">非</option>
        <option value="when">条件</option>
        <option value="status">状态</option>
      </select>
      <button class="btn btn-ghost" @click="$emit('auto-layout')">自动布局</button>
      <button class="btn btn-ghost" @click="$emit('validate')">校验</button>
    </div>
    <div class="right">
      <button class="btn btn-ghost" @click="$emit('preview')">预览 YAML</button>
      <button class="btn btn-primary" @click="$emit('save')">保存</button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const gateType = ref('')

defineProps({})

const emit = defineEmits(['add-node', 'add-gate', 'auto-layout', 'validate', 'preview', 'save'])

const handleAddGate = () => {
  if (!gateType.value) return
  emit('add-gate', gateType.value)
  gateType.value = ''
}
</script>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.toolbar .left, .toolbar .right { display: flex; gap: 8px; align-items: center; }
.btn.active { border-color: var(--primary-accent); color: var(--primary-accent); }
</style>

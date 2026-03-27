<template>
  <div class="panel action-library">
    <div class="panel-header action-header">
      <strong>动作库</strong>
      <input class="input action-search" v-model="query" placeholder="搜索动作名称或标识" />
    </div>
    <div class="panel-body action-body">
      <div v-if="!filteredActions.length" class="empty">暂无动作</div>
      <button
        v-for="action in filteredActions"
        :key="action.fqid"
        class="action-item"
        :title="action.docstring || action.fqid"
        @click="$emit('add-action', action)"
      >
        <div class="title">{{ action.name || action.fqid }}</div>
        <div class="sub">{{ action.fqid }}</div>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  actions: { type: Array, default: () => [] }
})

defineEmits(['add-action'])

const query = ref('')

const filteredActions = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return props.actions
  return props.actions.filter((action) => {
    const haystack = `${action.name || ''} ${action.fqid || ''} ${action.docstring || ''}`.toLowerCase()
    return haystack.includes(keyword)
  })
})
</script>

<style scoped>
.action-library {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.action-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.action-search {
  max-width: 260px;
}
.action-body {
  flex: 1 1 auto;
  overflow: auto;
  display: grid;
  gap: 8px;
}
.action-item {
  text-align: left;
  background: transparent;
  border: 1px solid var(--border-frosted);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  cursor: pointer;
  transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.action-item:hover {
  border-color: var(--primary-accent);
  background: rgba(88, 101, 242, 0.08);
}
.action-item .title { font-weight: 600; }
.action-item .sub { font-size: 12px; color: var(--text-secondary); }
.empty { color: var(--text-secondary); font-size: 13px; }
</style>

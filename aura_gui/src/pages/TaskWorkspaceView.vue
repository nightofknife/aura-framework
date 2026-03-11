<template>
  <div class="task-workspace">
    <div class="task-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab-button"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="task-tab-body">
      <KeepAlive>
        <component :is="activeComponent" />
      </KeepAlive>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import TaskEditorView from './TaskEditorView.vue'
import FileEditorView from './FileEditorView.vue'

const tabs = [
  { key: 'task', label: '任务编排' },
  { key: 'file', label: '文件编辑' }
]

const activeTab = ref('task')
const activeComponent = computed(() => (activeTab.value === 'file' ? FileEditorView : TaskEditorView))
</script>

<style scoped>
.task-workspace {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 70vh;
}
.task-tabs {
  display: inline-flex;
  gap: 8px;
  padding: 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid var(--border-frosted);
  align-self: flex-start;
}
.tab-button {
  border: 1px solid transparent;
  background: transparent;
  border-radius: 999px;
  padding: 6px 14px;
  font-weight: 600;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--dur) var(--ease);
}
.tab-button:hover {
  color: var(--text-primary);
  background: rgba(88, 101, 242, 0.08);
}
.tab-button.active {
  color: #fff;
  background: var(--primary-accent);
  box-shadow: 0 6px 14px rgba(88, 101, 242, 0.25);
}
.task-tab-body {
  flex: 1 1 auto;
  min-height: 0;
}
</style>

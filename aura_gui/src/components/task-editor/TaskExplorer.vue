<template>
  <div class="task-editor-explorer">
    <div class="panel explorer-panel">
      <div class="panel-header">
        <span class="panel-icon plan"></span>
        <strong class="panel-title">方案</strong>
      </div>
      <div class="panel-body list">
        <button
          v-for="plan in plans"
          :key="plan.name"
          class="list-item"
          :class="{ active: plan.name === selectedPlan }"
          :title="plan.name"
          @click="$emit('select-plan', plan.name)"
        >
          <span class="item-icon plan"></span>
          <div class="text">
            <div class="title">{{ plan.name }}</div>
            <div class="sub">{{ plan.task_count }} 个任务</div>
          </div>
        </button>
      </div>
    </div>

    <div class="panel explorer-panel">
      <div class="panel-header">
        <span class="panel-icon file"></span>
        <strong class="panel-title">任务文件</strong>
        <button class="btn btn-ghost btn-mini" @click="toggleCreate">新建</button>
      </div>
      <div class="panel-body list">
        <div v-if="creating" class="create-task">
          <input
            class="input"
            v-model="newTaskName"
            placeholder="任务路径，如 test/my_task"
            @keydown.enter="emitCreate"
          />
          <div class="create-actions">
            <button class="btn btn-primary btn-mini" @click="emitCreate">创建</button>
            <button class="btn btn-ghost btn-mini" @click="cancelCreate">取消</button>
          </div>
        </div>
        <div v-if="!groupedFiles.length" class="empty">暂无任务</div>
        <div v-for="file in groupedFiles" :key="file.path" class="file-group">
          <div
            class="file-title"
            :class="{ active: file.path === selectedFile }"
            :title="file.path"
            @click="$emit('select-file', file.path)"
          >
            <span class="item-icon file"></span>
            <span class="file-label">{{ file.path }}</span>
          </div>
          <div class="file-tasks">
            <button
              v-for="task in file.tasks"
              :key="task.task_key"
              class="list-item sub"
              :class="{ active: task.task_key === selectedTaskKey }"
              :title="task.title"
              @click="$emit('select-task', { taskKey: task.task_key, filePath: file.path })"
            >
              <span class="item-icon task"></span>
              <div class="text">
                <div class="title">{{ task.title }}</div>
                <div class="sub">{{ task.task_key }}</div>
              </div>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  plans: { type: Array, default: () => [] },
  tasks: { type: Array, default: () => [] },
  selectedPlan: { type: String, default: '' },
  selectedFile: { type: String, default: '' },
  selectedTaskKey: { type: String, default: '' }
})

const emit = defineEmits(['select-plan', 'select-file', 'select-task', 'create-task'])

const creating = ref(false)
const newTaskName = ref('')

const toggleCreate = () => {
  creating.value = !creating.value
  if (!creating.value) newTaskName.value = ''
}

const cancelCreate = () => {
  creating.value = false
  newTaskName.value = ''
}

const emitCreate = () => {
  const name = newTaskName.value.trim()
  if (!name) return
  emit('create-task', name)
  cancelCreate()
}

const deriveFilePath = (taskNameOrRef) => {
  // 处理新格式: tasks:test:draw_one_star -> tasks/test/draw_one_star.yaml
  // 处理旧格式: test/draw_one_star/draw_one_star -> tasks/test/draw_one_star.yaml
  if (taskNameOrRef.startsWith('tasks:')) {
    // 新格式
    const path = taskNameOrRef.slice(6).replace(/:/g, '/')  // 去掉 'tasks:' 并替换 ':' 为 '/'
    return `tasks/${path}.yaml`
  } else {
    // 旧格式
    const parts = taskNameOrRef.split('/')
    if (parts.length === 1) {
      return `tasks/${parts[0]}.yaml`
    }
    // 如果最后一部分与倒数第二部分相同，去掉重复
    if (parts.length >= 2 && parts[parts.length - 1] === parts[parts.length - 2]) {
      const filePath = parts.slice(0, -1).join('/')
      return `tasks/${filePath}.yaml`
    }
    const filePath = parts.join('/')
    return `tasks/${filePath}.yaml`
  }
}

const groupedFiles = computed(() => {
  const map = new Map()
  for (const task of props.tasks) {
    const taskNameOrRef = task.task_ref || task.task_name_in_plan || task.task_name
    const filePath = deriveFilePath(taskNameOrRef)
    // 从任务引用中提取任务键
    let taskKey
    if (taskNameOrRef.startsWith('tasks:')) {
      // 新格式: tasks:test:draw_one_star -> draw_one_star
      const parts = taskNameOrRef.slice(6).split(':')
      taskKey = parts[parts.length - 1]
    } else {
      // 旧格式: test/draw_one_star/draw_one_star -> draw_one_star
      const parts = taskNameOrRef.split('/')
      taskKey = parts[parts.length - 1]
    }
    const title = task.meta?.title || taskKey

    if (!map.has(filePath)) {
      map.set(filePath, { path: filePath, tasks: [] })
    }
    map.get(filePath).tasks.push({ task_key: taskKey, title })
  }
  return Array.from(map.values()).sort((a, b) => a.path.localeCompare(b.path))
})
</script>

<style scoped>
.task-editor-explorer {
  display: grid;
  gap: 12px;
  grid-template-columns: minmax(260px, 1fr) minmax(320px, 1.4fr);
  height: 100%;
  min-height: 0;
}
.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.panel-header .btn {
  margin-left: auto;
}
.explorer-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.explorer-panel .panel-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}
.list { display: grid; gap: 8px; }
.list-item {
  display: flex;
  align-items: center;
  gap: 8px;
  text-align: left;
  background: transparent;
  border: 1px solid var(--border-frosted);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  cursor: pointer;
  transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.list-item.active {
  border-color: var(--primary-accent);
  background: rgba(88, 101, 242, 0.08);
}
.list-item .title { font-weight: 600; }
.list-item .sub { font-size: 12px; color: var(--text-secondary); }
.file-group { display: grid; gap: 6px; }
.file-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 4px 0;
}
.file-title.active { color: var(--text-primary); font-weight: 600; }
.file-tasks { display: grid; gap: 6px; padding-left: 12px; }
.empty { color: var(--text-secondary); font-size: 13px; }
.create-task {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px dashed var(--border-frosted);
  border-radius: var(--radius-sm);
}
.create-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
.btn-mini {
  padding: 4px 10px;
  font-size: 12px;
}

.panel-icon,
.item-icon {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  background: rgba(88, 101, 242, 0.2);
  flex: 0 0 auto;
}
.panel-icon.file,
.item-icon.file { background: rgba(14, 165, 233, 0.2); }
.item-icon.task { background: rgba(16, 185, 129, 0.2); }

</style>

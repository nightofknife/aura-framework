<!-- src/components/TaskList.vue -->
<template>
  <div class="task-list-container">
    <h2>Tasks in "{{ planName }}"</h2>
    <div v-if="loading" class="loading">Loading tasks...</div>
    <div v-if="error" class="error">{{ error }}</div>
    <ul v-if="tasks.length > 0">
      <li v-for="task in tasks" :key="task.full_task_id" class="task-item">
        <div class="task-info">
          <strong class="task-title">{{ task.meta.title || task.task_name_in_plan }}</strong>
          <p class="task-description">{{ task.meta.description }}</p>
        </div>
        <!-- 修改：按钮现在会调用 openRunModal 方法 -->
        <button class="run-button" @click="openRunModal(task)">Run</button>
      </li>
    </ul>
    <div v-else-if="!loading && !error" class="no-tasks">
      This plan has no tasks.
    </div>
  </div>
</template>

<script setup>
// 修改：添加 defineEmits
const props = defineProps({
  planName: String,
  tasks: Array,
  loading: Boolean,
  error: String,
});

const emit = defineEmits(['open-run-modal']);

// 新增：定义一个方法，当按钮被点击时，
// 它会发出 'open-run-modal' 事件，并把整个 task 对象作为参数传递出去。
const openRunModal = (task) => {
  emit('open-run-modal', task);
};
</script>

<style scoped>
.task-list-container {
  padding: 20px;
  background-color: #fff;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}
.task-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px;
  border-bottom: 1px solid #eee;
}
.task-item:last-child {
  border-bottom: none;
}
.task-info {
  flex-grow: 1;
}
.task-title {
  font-size: 1.1em;
  color: #333;
}
.task-description {
  font-size: 0.9em;
  color: #777;
  margin: 5px 0 0 0;
}
.run-button {
  padding: 8px 15px;
  border: 1px solid #007bff;
  background-color: #007bff;
  color: white;
  border-radius: 5px;
  cursor: pointer;
  transition: background-color 0.2s ease;
  margin-left: 20px;
  font-weight: bold;
}
.run-button:hover {
  background-color: #0056b3;
}
.loading, .error, .no-tasks {
  padding: 15px;
  text-align: center;
  color: #888;
}
.error {
  color: #D8000C;
}
</style>

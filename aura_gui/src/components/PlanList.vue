<!-- src/components/PlanList.vue -->
<template>
  <div class="plan-list-container">
    <h2>Available Plans</h2>
    <div v-if="loading" class="loading">Loading plans...</div>
    <div v-if="error" class="error">{{ error }}</div>
    <!-- 修改：ul元素现在监听点击事件，但具体处理在li上 -->
    <ul v-if="plans.length > 0">
      <!-- 修改：li现在是一个可点击的按钮，并根据是否被选中来动态添加'selected'类 -->
      <li
        v-for="plan in plans"
        :key="plan.name"
        class="plan-item"
        :class="{ selected: plan.name === selectedPlan }"
        @click="selectPlan(plan.name)"
      >
        <span class="plan-name">{{ plan.name }}</span>
        <span class="task-count">{{ plan.task_count }} tasks</span>
      </li>
    </ul>
    <div v-else-if="!loading && !error" class="no-plans">
      No plans found. Is the API server running and have you created any plans?
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import axios from 'axios';

// 新增：定义这个组件可以接收的属性 (props) 和可以发出的事件 (emits)
defineProps({
  selectedPlan: String, // 接收一个名为 selectedPlan 的字符串属性
});
const emit = defineEmits(['plan-selected']); // 定义一个名为 'plan-selected' 的自定义事件

const plans = ref([]);
const loading = ref(true);
const error = ref(null);
const apiClient = axios.create({
  baseURL: 'http://127.0.0.1:8000/api',
  timeout: 5000,
});

const fetchPlans = async () => {
  // ... fetchPlans 的内部逻辑保持不变 ...
  loading.value = true;
  error.value = null;
  try {
    const response = await apiClient.get('/plans');
    plans.value = response.data;
  } catch (err) {
    console.error("Failed to fetch plans:", err);
    error.value = 'Failed to load plans. Please ensure the Aura API server is running.';
  } finally {
    loading.value = false;
  }
};

onMounted(fetchPlans);

// 新增：定义点击事件的处理函数
const selectPlan = (planName) => {
  // 当一个plan被点击时，通过emit向父组件发送'plan-selected'事件，并附带plan的名称
  emit('plan-selected', planName);
};
</script>

<style scoped>
/* ... 保留大部分之前的样式 ... */
.plan-list-container {
  padding: 20px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background-color: #fff;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}
.plan-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 15px;
  margin-bottom: 8px;
  background-color: #f9f9f9;
  border: 1px solid #eee;
  border-radius: 6px;
  list-style-type: none;
  /* 新增：让列表项看起来像可以点击的 */
  cursor: pointer;
  transition: background-color 0.2s ease, border-color 0.2s ease;
}
/* 新增：鼠标悬停时的样式 */
.plan-item:hover {
  background-color: #f0f5ff;
  border-color: #a0bfff;
}
/* 新增：被选中项的样式 */
.plan-item.selected {
  background-color: #e6f0ff;
  border-color: #79a7ff;
  font-weight: bold;
}
.plan-name { font-weight: 600; color: #333; }
.task-count { font-size: 0.9em; color: #777; background-color: #e9e9e9; padding: 3px 8px; border-radius: 10px; }
.loading, .error, .no-plans { margin-top: 20px; padding: 15px; text-align: center; color: #888; background-color: #f5f5f5; border-radius: 6px; }
.error { color: #D8000C; background-color: #FFD2D2; }
</style>

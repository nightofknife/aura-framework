<template>
  <div>
    <div v-if="loading" class="list">
      <div class="list-item"><span class="item-sub">Loading plans…</span></div>
    </div>
    <div v-else-if="error" class="list">
      <div class="list-item"><span class="item-sub" style="color:var(--danger)">{{ error }}</span></div>
    </div>
    <div v-else class="list">
      <div
          v-for="plan in plans"
          :key="plan.name"
          class="list-item"
          :class="{ selected: plan.name === selectedPlan }"
          @click="selectPlan(plan.name)"
      >
        <div>
          <div class="item-title">{{ plan.name }}</div>
          <div class="item-sub">Automation plan</div>
        </div>
        <div class="item-meta">
          <span class="meta-chip"><span class="meta-strong">{{ plan.task_count }}</span> tasks</span>
        </div>
      </div>
      <div v-if="plans.length===0" class="list-item"><span class="item-sub">No plans found.</span></div>
    </div>
  </div>
</template>

<script setup>
import {ref, onMounted} from 'vue';
import axios from 'axios';

defineProps({selectedPlan: String});
const emit = defineEmits(['plan-selected']);

const plans = ref([]);
const loading = ref(true);
const error = ref(null);
const apiClient = axios.create({baseURL: 'http://127.0.0.1:8000/api', timeout: 5000});

const fetchPlans = async () => {
  loading.value = true;
  error.value = null;
  try {
    const r = await apiClient.get('/plans');
    plans.value = r.data;
  } catch (e) {
    error.value = 'Failed to load plans.';
  } finally {
    loading.value = false;
  }
};
onMounted(fetchPlans);

const selectPlan = (name) => emit('plan-selected', name);
</script>

<style scoped>
/* 使用全局 theme.css 里的 .list / .list-item 样式，无需额外样式 */
</style>

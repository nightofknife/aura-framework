<!-- src/components/RunTaskModal.vue -->
<template>
  <div v-if="show" class="modal-overlay" @click.self="close">
    <div class="modal-content">
      <h3>Run Task: {{ task.meta.title || task.task_name_in_plan }}</h3>

      <form @submit.prevent="submit">
        <div v-if="!normalizedInputs.length" class="no-inputs">
          This task requires no inputs.
        </div>

        <InputFieldRenderer
            v-else
            v-for="input in normalizedInputs"
            :key="input.name"
            :schema="input"
            v-model="inputsData[input.name]"
        />

        <div class="modal-actions">
          <button type="button" class="btn-secondary" @click="close">Cancel</button>
          <button type="submit" class="btn-primary">Run Task</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import {computed, ref, watchEffect} from 'vue';
import InputFieldRenderer from './InputFieldRenderer.vue';
import {buildDefaultFromSchema, normalizeInputSchema} from '../utils/inputSchema.js';

const props = defineProps({
  show: Boolean,
  task: Object,
});

const emit = defineEmits(['close', 'run']);

const normalizedInputs = computed(() => {
  if (!props.task?.meta?.inputs) return [];
  return (props.task.meta.inputs || [])
      .filter(it => it && it.name)
      .map(it => normalizeInputSchema({...it, label: it.label || it.name, name: it.name}));
});

const inputsData = ref({});

watchEffect(() => {
  if (!normalizedInputs.value.length) {
    inputsData.value = {};
    return;
  }
  const next = {};
  normalizedInputs.value.forEach((schema) => {
    next[schema.name] = buildDefaultFromSchema(schema);
  });
  inputsData.value = next;
});

const close = () => {
  emit('close');
};

const submit = () => {
  emit('run', inputsData.value);
};
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.6);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  padding: 25px;
  border-radius: 8px;
  width: 500px;
  max-width: 90%;
  box-shadow: 0 5px 15px rgba(0, 0, 0, 0.3);
}

.no-inputs {
  margin: 20px 0;
  text-align: center;
  color: #888;
}

.modal-actions {
  margin-top: 20px;
  text-align: right;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.modal-actions button {
  padding: 10px 20px;
  border: none;
  border-radius: 5px;
  cursor: pointer;
}

.btn-primary {
  background-color: #007bff;
  color: white;
}

.btn-secondary {
  background-color: #6c757d;
  color: white;
}
</style>

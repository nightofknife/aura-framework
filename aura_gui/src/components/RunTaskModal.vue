<!-- src/components/RunTaskModal.vue -->
<template>
  <!-- v-if="show" 控制整个模态框的显示和隐藏 -->
  <div v-if="show" class="modal-overlay" @click.self="close">
    <div class="modal-content">
      <h3>Run Task: {{ task.meta.title || task.task_name_in_plan }}</h3>

      <form @submit.prevent="submit">
        <div v-if="!task.meta.inputs || task.meta.inputs.length === 0" class="no-inputs">
          This task requires no inputs.
        </div>

        <!-- v-for 循环遍历任务定义中的 inputs，动态生成表单字段 -->
        <div v-for="input in task.meta.inputs" :key="input.name" class="form-group">
          <label :for="input.name">{{ input.label || input.name }}</label>
          <!-- v-model 将表单输入的值与我们的 anputsData ref 双向绑定 -->
          <input
            :type="input.type || 'text'"
            :id="input.name"
            v-model="inputsData[input.name]"
            :placeholder="input.placeholder || ''"
            :required="input.required || false"
          />
          <small v-if="input.description">{{ input.description }}</small>
        </div>

        <div class="modal-actions">
          <button type="button" class="btn-secondary" @click="close">Cancel</button>
          <button type="submit" class="btn-primary">Run Task</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, watchEffect } from 'vue';

// 定义组件可以接收的属性
const props = defineProps({
  show: Boolean, // 是否显示
  task: Object,  // 任务定义对象
});

// 定义组件可以发出的事件
const emit = defineEmits(['close', 'run']);

// 创建一个响应式对象来存储表单数据
const inputsData = ref({});

// watchEffect 是一个非常有用的钩子。
// 它会立即运行一次，然后在其依赖项发生变化时重新运行。
// 我们用它来根据传入的 task prop 初始化/重置表单数据。
watchEffect(() => {
  if (props.task && props.task.meta && props.task.meta.inputs) {
    const newInputs = {};
    for (const input of props.task.meta.inputs) {
      // 为每个输入设置一个默认值
      newInputs[input.name] = input.default || '';
    }
    inputsData.value = newInputs;
  } else {
    inputsData.value = {};
  }
});

const close = () => {
  emit('close');
};

const submit = () => {
  // 当表单提交时，发出 'run' 事件，并附带收集到的表单数据
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
  box-shadow: 0 5px 15px rgba(0,0,0,0.3);
}
.form-group {
  margin-bottom: 15px;
}
.form-group label {
  display: block;
  margin-bottom: 5px;
  font-weight: bold;
}
.form-group input {
  width: 100%;
  padding: 8px;
  border: 1px solid #ccc;
  border-radius: 4px;
  box-sizing: border-box;
}
.form-group small {
  display: block;
  margin-top: 4px;
  color: #777;
}
.no-inputs {
  margin: 20px 0;
  text-align: center;
  color: #888;
}
.modal-actions {
  margin-top: 20px;
  text-align: right;
}
.modal-actions button {
  padding: 10px 20px;
  border: none;
  border-radius: 5px;
  cursor: pointer;
  margin-left: 10px;
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

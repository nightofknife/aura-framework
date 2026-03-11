<template>
  <div class="checkbox-wrapper">
    <!-- 全选/清空按钮 -->
    <div v-if="showSelectAll" class="checkbox-controls">
      <button type="button" @click="selectAll" class="btn-control">全选</button>
      <button type="button" @click="clearAll" class="btn-control">清空</button>
    </div>

    <!-- Checkbox 组 -->
    <div :class="['checkbox-group', `columns-${columns}`]">
      <label v-for="option in options" :key="option" class="checkbox-item">
        <input
          type="checkbox"
          :value="option"
          :checked="selectedValues.includes(option)"
          :disabled="isDisabled(option)"
          @change="toggleCheckbox(option)" />
        <span class="checkbox-label">{{ option }}</span>
      </label>
    </div>

    <!-- 数量提示 -->
    <div v-if="min != null || max != null" class="count-hint" :class="`hint-${hintStatus}`">
      {{ countHintText }}
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { getCountHintText, getCountHintStatus } from '../../utils/widgetInference.js';

const props = defineProps({
  options: { type: Array, required: true },
  modelValue: { type: Array, default: () => [] },
  min: { type: Number, default: undefined },
  max: { type: Number, default: undefined },
  columns: { type: Number, default: 1 },
  showSelectAll: { type: Boolean, default: false }
});

const emit = defineEmits(['update:modelValue']);

const selectedValues = computed(() => props.modelValue || []);

function isDisabled(option) {
  // 如果已选中，不禁用（可以取消）
  if (selectedValues.value.includes(option)) {
    return false;
  }

  // 如果有最大限制且已达上限，禁用未选中的
  if (props.max !== undefined && selectedValues.value.length >= props.max) {
    return true;
  }

  return false;
}

function toggleCheckbox(option) {
  const current = [...selectedValues.value];
  const idx = current.indexOf(option);

  if (idx > -1) {
    // 取消选择 - 检查最小限制
    if (props.min !== undefined && current.length <= props.min) {
      return; // 不允许取消，已达下限
    }
    current.splice(idx, 1);
  } else {
    // 添加选择 - 检查最大限制
    if (props.max !== undefined && current.length >= props.max) {
      return; // 不允许添加，已达上限
    }
    current.push(option);
  }

  emit('update:modelValue', current);
}

function selectAll() {
  if (props.max !== undefined) {
    // 如果有最大限制，只选择前max个
    emit('update:modelValue', props.options.slice(0, props.max));
  } else {
    emit('update:modelValue', [...props.options]);
  }
}

function clearAll() {
  emit('update:modelValue', []);
}

const countHintText = computed(() =>
  getCountHintText(selectedValues.value.length, props.min, props.max)
);

const hintStatus = computed(() =>
  getCountHintStatus(selectedValues.value.length, props.min, props.max)
);
</script>

<style scoped>
/* 保持与现有样式一致 */
.checkbox-wrapper {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.checkbox-controls {
  display: flex;
  gap: 8px;
  margin-bottom: 4px;
}

.btn-control {
  padding: 4px 8px;
  font-size: 12px;
  border: 1px solid #d0d7de;
  background: white;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-control:hover {
  background: #f6f8fa;
}

.checkbox-group {
  display: grid;
  gap: 8px;
}

.checkbox-group.columns-1 {
  grid-template-columns: 1fr;
}

.checkbox-group.columns-2 {
  grid-template-columns: repeat(2, 1fr);
}

.checkbox-group.columns-3 {
  grid-template-columns: repeat(3, 1fr);
}

.checkbox-item {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary, #555);
}

.checkbox-item input[type="checkbox"] {
  cursor: pointer;
  margin: 0;
  width: 16px;
  height: 16px;
}

.checkbox-item input[type="checkbox"]:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.checkbox-label {
  user-select: none;
}

.checkbox-item:hover .checkbox-label {
  color: var(--text-primary, #222);
}

.count-hint {
  font-size: 12px;
  margin-top: 4px;
}

.hint-normal {
  color: var(--text-secondary, #666);
}

.hint-error {
  color: #c00;
  font-weight: 600;
}

.hint-full {
  color: #27ae60;
}
</style>

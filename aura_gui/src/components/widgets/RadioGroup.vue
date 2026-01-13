<template>
  <div :class="['radio-group', layout]">
    <label v-for="option in options" :key="option" class="radio-item">
      <input
        type="radio"
        :name="name"
        :value="option"
        :checked="modelValue === option"
        :disabled="disabled"
        @change="$emit('update:modelValue', option)" />
      <span class="radio-label">{{ option }}</span>
    </label>
    <label v-if="!required" class="radio-item">
      <input
        type="radio"
        :name="name"
        :checked="modelValue === null"
        :disabled="disabled"
        @change="$emit('update:modelValue', null)" />
      <span class="radio-label">不选择</span>
    </label>
  </div>
</template>

<script setup>
defineProps({
  options: { type: Array, required: true },
  modelValue: { type: [String, Number, Boolean, null], default: null },
  name: { type: String, default: () => `radio_${Math.random().toString(36).substr(2, 9)}` },
  layout: { type: String, default: 'vertical' }, // 'vertical' | 'horizontal'
  required: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false }
});
defineEmits(['update:modelValue']);
</script>

<style scoped>
/* 保持与现有样式一致 */
.radio-group {
  display: flex;
  gap: 8px;
}

.radio-group.vertical {
  flex-direction: column;
}

.radio-group.horizontal {
  flex-direction: row;
  flex-wrap: wrap;
}

.radio-item {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary, #555);
}

.radio-item input[type="radio"] {
  cursor: pointer;
  margin: 0;
  width: 16px;
  height: 16px;
}

.radio-item input[type="radio"]:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.radio-label {
  user-select: none;
}

.radio-item:hover .radio-label {
  color: var(--text-primary, #222);
}
</style>

<template>
  <div :class="['radio-group', layout]">
    <label v-for="option in options" :key="option" class="radio-item">
      <input
        type="radio"
        :name="name"
        :value="option"
        :checked="modelValue === option"
        :disabled="disabled"
        @change="$emit('update:modelValue', option)"
      />
      <span>{{ option }}</span>
    </label>

    <label v-if="!required" class="radio-item">
      <input
        type="radio"
        :name="name"
        :checked="modelValue === null"
        :disabled="disabled"
        @change="$emit('update:modelValue', null)"
      />
      <span>None</span>
    </label>
  </div>
</template>

<script setup>
defineProps({
  options: { type: Array, required: true },
  modelValue: { type: [String, Number, Boolean, null], default: null },
  name: { type: String, default: () => `radio_${Math.random().toString(36).slice(2, 9)}` },
  layout: { type: String, default: 'vertical' },
  required: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})

defineEmits(['update:modelValue'])
</script>

<style scoped>
.radio-group {
  display: flex;
  gap: 10px;
}

.radio-group.vertical {
  flex-direction: column;
}

.radio-group.horizontal {
  flex-wrap: wrap;
}

.radio-item {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  padding: 0 12px;
  border: 1px solid var(--line);
  background: rgba(8, 20, 32, 0.72);
  color: var(--smoke);
  clip-path: polygon(8px 0, 100% 0, calc(100% - 8px) 100%, 0 100%);
}

.radio-item input {
  margin: 0;
}
</style>

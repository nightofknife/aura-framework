<template>
  <div class="tag-input-wrapper">
    <div class="tags-container">
      <span v-for="(tag, idx) in tags" :key="idx" class="tag">
        {{ tag }}
        <button type="button" @click="removeTag(idx)" class="tag-remove" title="移除">×</button>
      </span>
      <input
        ref="inputRef"
        v-model="currentInput"
        @keydown.enter.prevent="addTag"
        @keydown.backspace="handleBackspace"
        :placeholder="tags.length === 0 ? placeholder : ''"
        class="tag-input" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue';

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  placeholder: { type: String, default: '输入后按Enter添加' }
});

const emit = defineEmits(['update:modelValue']);

const currentInput = ref('');
const inputRef = ref(null);

const tags = computed(() => props.modelValue || []);

function addTag() {
  const value = currentInput.value.trim();
  if (value && !tags.value.includes(value)) {
    emit('update:modelValue', [...tags.value, value]);
    currentInput.value = '';
  }
}

function removeTag(idx) {
  const newTags = [...tags.value];
  newTags.splice(idx, 1);
  emit('update:modelValue', newTags);
}

function handleBackspace() {
  if (currentInput.value === '' && tags.value.length > 0) {
    removeTag(tags.value.length - 1);
  }
}
</script>

<style scoped>
/* 保持与现有输入框样式一致 */
.tag-input-wrapper {
  border: 1px solid #d0d7de;
  border-radius: 6px;
  padding: 4px;
  background: white;
  min-height: 38px;
}

.tags-container {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: #0969da;
  color: white;
  border-radius: 12px;
  font-size: 12px;
  line-height: 1.5;
}

.tag-remove {
  background: none;
  border: none;
  color: white;
  cursor: pointer;
  font-size: 16px;
  padding: 0;
  line-height: 1;
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  transition: background 0.2s;
}

.tag-remove:hover {
  background: rgba(255, 255, 255, 0.2);
}

.tag-input {
  border: none;
  outline: none;
  flex: 1;
  min-width: 120px;
  padding: 4px;
  font-size: 13px;
  color: var(--text-primary, #222);
}

.tag-input::placeholder {
  color: var(--text-secondary, #999);
}
</style>

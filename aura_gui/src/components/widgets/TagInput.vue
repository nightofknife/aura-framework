<template>
  <div class="tag-input-wrapper">
    <span v-for="(tag, index) in tags" :key="index" class="tag">
      {{ tag }}
      <button type="button" class="tag-remove" title="Remove" @click="removeTag(index)">×</button>
    </span>

    <input
      ref="inputRef"
      v-model="currentInput"
      class="tag-input"
      :placeholder="tags.length === 0 ? placeholder : ''"
      @keydown.enter.prevent="addTag"
      @keydown.backspace="handleBackspace"
    />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  placeholder: { type: String, default: 'Press Enter to add a tag' },
})

const emit = defineEmits(['update:modelValue'])
const inputRef = ref(null)
const currentInput = ref('')
const tags = computed(() => props.modelValue || [])

function addTag() {
  const value = currentInput.value.trim()
  if (!value || tags.value.includes(value)) return
  emit('update:modelValue', [...tags.value, value])
  currentInput.value = ''
}

function removeTag(index) {
  const next = [...tags.value]
  next.splice(index, 1)
  emit('update:modelValue', next)
}

function handleBackspace() {
  if (!currentInput.value && tags.value.length) {
    removeTag(tags.value.length - 1)
  }
}
</script>

<style scoped>
.tag-input-wrapper {
  display: flex;
  min-height: 44px;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding: 8px 10px;
  border: 1px solid var(--line);
  background: var(--bg-input);
  clip-path: polygon(10px 0, 100% 0, calc(100% - 10px) 100%, 0 100%);
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 26px;
  padding: 0 10px;
  background: rgba(239, 106, 62, 0.18);
  color: var(--sand-bright);
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  clip-path: polygon(8px 0, 100% 0, calc(100% - 8px) 100%, 0 100%);
}

.tag-remove {
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  padding: 0;
}

.tag-input {
  min-width: 140px;
  flex: 1;
  border: 0;
  background: transparent;
  color: var(--smoke);
  outline: none;
}
</style>

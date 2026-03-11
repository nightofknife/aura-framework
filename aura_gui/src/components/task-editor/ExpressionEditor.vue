<template>
  <div class="expression-editor">
    <div class="vars">
      <div class="label">可用变量</div>
      <div class="list">
        <button class="pill" v-for="item in variables" :key="item" @click.prevent="insertVar(item)">
          {{ item }}
        </button>
      </div>
    </div>
    <textarea class="input" rows="4" v-model="localValue" @input="emitChange" />
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' }
})

const emit = defineEmits(['update:modelValue'])

const variables = ['inputs', 'initial', 'nodes', 'loop', 'state']
const localValue = ref(props.modelValue)

watch(() => props.modelValue, (value) => {
  localValue.value = value
})

const emitChange = () => emit('update:modelValue', localValue.value)

const insertVar = (name) => {
  localValue.value = `${localValue.value}{{ ${name} }}`
  emitChange()
}
</script>

<style scoped>
.expression-editor { display: grid; gap: 8px; }
.vars { display: grid; gap: 6px; }
.vars .label { font-size: 12px; color: var(--text-secondary); }
.vars .list { display: flex; gap: 6px; flex-wrap: wrap; }
</style>


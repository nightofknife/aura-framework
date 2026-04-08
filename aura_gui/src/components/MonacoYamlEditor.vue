<template>
  <div class="monaco-editor-wrapper">
    <vue-monaco-editor
      v-model:value="code"
      language="yaml"
      :options="editorOptions"
      :theme="theme"
      @mount="handleMount"
      @change="handleChange"
      class="monaco-editor"
    />
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { VueMonacoEditor } from '@guolao/vue-monaco-editor'

const props = defineProps({
  modelValue: {
    type: String,
    default: ''
  },
  readOnly: {
    type: Boolean,
    default: false
  },
  theme: {
    type: String,
    default: 'vs-dark'
  },
  height: {
    type: String,
    default: '500px'
  }
})

const emit = defineEmits(['update:modelValue', 'change'])

const code = ref(props.modelValue)

// 编辑器选项
const editorOptions = {
  readOnly: props.readOnly,
  minimap: { enabled: false },
  fontSize: 13,
  lineNumbers: 'on',
  scrollBeyondLastLine: false,
  automaticLayout: true,
  wordWrap: 'on',
  tabSize: 2,
  folding: true,
  lineDecorationsWidth: 10,
  lineNumbersMinChars: 3,
  renderLineHighlight: 'all',
  scrollbar: {
    verticalScrollbarSize: 10,
    horizontalScrollbarSize: 10
  }
}

// 监听外部值变化
watch(() => props.modelValue, (newValue) => {
  if (newValue !== code.value) {
    code.value = newValue
  }
})

function handleMount(editor) {
  // 编辑器挂载完成后的回调
  console.log('Monaco Editor mounted')
}

function handleChange(value) {
  emit('update:modelValue', value)
  emit('change', value)
}
</script>

<style scoped>
.monaco-editor-wrapper {
  border: 1px solid var(--border-frosted, rgba(255, 255, 255, 0.1));
  border-radius: 8px;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.3);
}

.monaco-editor {
  min-height: v-bind(height);
}
</style>

<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useToasts } from '../composables/useToasts.js'

// ✅ 正确解构
const { toasts, dismiss } = useToasts()

function onKeydown(e) {
  if (e.key === 'Escape' && toasts.value.length) {
    const last = toasts.value[toasts.value.length - 1]
    dismiss(last.id)
  }
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div class="toast-host" aria-live="polite" aria-atomic="false">
      <TransitionGroup name="toast" tag="div">
        <!-- ✅ 这里用 toasts -->
        <div v-for="t in toasts" :key="t.id" class="toast" :class="t.type" role="status">
          <button class="close" aria-label="Close" @click="dismiss(t.id)">✕</button>
          <strong class="title">{{ t.title }}</strong>
          <div v-if="t.message" class="msg">{{ t.message }}</div>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

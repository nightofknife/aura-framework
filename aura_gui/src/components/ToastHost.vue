<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useToasts } from '../composables/useToasts.js'

const { toasts, dismiss } = useToasts()

function onKeydown(event) {
  if (event.key === 'Escape' && toasts.value.length) {
    dismiss(toasts.value[toasts.value.length - 1].id)
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div class="toast-host" aria-live="polite" aria-atomic="false">
      <TransitionGroup name="toast">
        <div v-for="toast in toasts" :key="toast.id" class="toast" :class="toast.type" role="status">
          <div class="toast__head">
            <strong>{{ toast.title }}</strong>
            <button class="toast__close" aria-label="Close" @click="dismiss(toast.id)">×</button>
          </div>
          <p v-if="toast.message" class="toast__msg">{{ toast.message }}</p>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-host {
  position: fixed;
  top: calc(var(--titlebar-h) + 18px);
  right: 18px;
  z-index: 40;
  display: flex;
  flex-direction: column;
  gap: 10px;
  pointer-events: none;
}

.toast {
  pointer-events: auto;
  min-width: 280px;
  max-width: 360px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  background: rgba(7, 22, 36, 0.96);
  color: var(--smoke);
  clip-path: polygon(14px 0, 100% 0, calc(100% - 18px) 100%, 0 100%);
  box-shadow: var(--shadow-panel);
}

.toast.success {
  border-color: rgba(88, 188, 125, 0.32);
}

.toast.error {
  border-color: rgba(218, 100, 88, 0.32);
}

.toast.info {
  border-color: rgba(213, 187, 134, 0.24);
}

.toast__head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.toast__head strong {
  color: var(--sand-bright);
  font-family: var(--font-display);
  font-size: 20px;
  letter-spacing: 0.04em;
  line-height: 0.95;
  text-transform: uppercase;
}

.toast__msg {
  margin: 8px 0 0;
  color: var(--smoke-dim);
  font-size: 13px;
  line-height: 1.55;
}

.toast__close {
  width: 28px;
  height: 28px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--smoke-dim);
  cursor: pointer;
  clip-path: polygon(7px 0, 100% 0, calc(100% - 7px) 100%, 0 100%);
}

.toast__close:hover {
  border-color: var(--line);
  background: rgba(18, 42, 62, 0.9);
  color: var(--sand-bright);
}

.toast-enter-active,
.toast-leave-active {
  transition: all var(--dur-med) var(--ease-std);
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(14px);
}
</style>

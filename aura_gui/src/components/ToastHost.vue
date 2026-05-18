<script setup>
import { onMounted, onUnmounted } from 'vue'
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-vue-next'
import { useToasts } from '../composables/useToasts.js'

const { toasts, dismiss } = useToasts()

function iconFor(type) {
  if (type === 'success') return CheckCircle2
  if (type === 'error') return AlertCircle
  return Info
}

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
          <component :is="iconFor(toast.type)" class="toast__icon" />
          <div class="toast__body">
            <strong>{{ toast.title }}</strong>
            <p v-if="toast.message">{{ toast.message }}</p>
          </div>
          <button class="toast__close" aria-label="关闭通知" @click="dismiss(toast.id)">
            <X class="icon" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-host {
  position: fixed;
  top: calc(var(--titlebar-h) + 14px);
  right: 14px;
  z-index: 100;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}

.toast {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  min-width: 300px;
  max-width: 380px;
  padding: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--bg-elevated);
  box-shadow: var(--shadow-elevated);
  color: var(--text-primary);
  pointer-events: auto;
}

.toast.success {
  border-color: rgba(54, 179, 126, 0.36);
}

.toast.error {
  border-color: rgba(239, 91, 91, 0.36);
}

.toast__icon {
  width: 18px;
  height: 18px;
  margin-top: 1px;
  color: var(--info);
}

.toast.success .toast__icon {
  color: var(--success);
}

.toast.error .toast__icon {
  color: var(--danger);
}

.toast__body {
  min-width: 0;
}

.toast__body strong {
  display: block;
  font-size: 13px;
  font-weight: 650;
}

.toast__body p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.toast__close {
  display: inline-flex;
  width: 26px;
  height: 26px;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.toast__close:hover {
  background: var(--bg-surface-2);
  color: var(--text-primary);
}

.toast-enter-active,
.toast-leave-active {
  transition: all var(--dur-med) var(--ease);
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(12px);
}
</style>

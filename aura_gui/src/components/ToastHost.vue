<template>
  <div class="toast-host" aria-live="polite" aria-atomic="false">
    <transition-group name="toast">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="toastClass(t.type)" role="status">
        <div class="toast-icon" aria-hidden="true">
          <span v-if="t.type==='success'">✅</span>
          <span v-else-if="t.type==='error'">⛔</span>
          <span v-else>ℹ️</span>
        </div>
        <div class="toast-body">
          <div class="toast-title" v-if="t.title"><strong>{{ t.title }}</strong></div>
          <div class="toast-msg" v-if="t.message">{{ t.message }}</div>
          <button v-if="t.action" class="btn btn-ghost btn-sm" @click="onAction(t)">{{ t.action.label }}</button>
        </div>
        <button class="toast-close" @click="dismiss(t.id)" aria-label="Close">✕</button>
      </div>
    </transition-group>
  </div>
</template>

<script setup>
import {useToasts} from '../composables/useToasts.js';

const {toasts, dismiss} = useToasts();

function toastClass(type) {
  if (type === 'success') return 'toast-success';
  if (type === 'error') return 'toast-error';
  return 'toast-info';
}

function onAction(t) {
  try {
    t.action?.handler?.();
  } finally {
    dismiss(t.id);
  }
}
</script>

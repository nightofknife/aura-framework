<template>
  <Teleport to="body">
    <div v-if="open" class="modal-mask" @click.self="$emit('cancel')">
      <section class="modal" role="dialog" aria-modal="true" :aria-label="title">
        <header class="modal__head">
          <strong>{{ title }}</strong>
        </header>
        <div class="modal__body">
          <p>{{ message }}</p>
        </div>
        <footer class="modal__actions">
          <button class="btn btn-ghost" @click="$emit('cancel')">{{ cancelText }}</button>
          <button class="btn" :class="danger ? 'btn-danger' : 'btn-primary'" @click="$emit('confirm')">
            {{ confirmText }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
defineProps({
  open: Boolean,
  title: { type: String, default: '确认操作' },
  message: { type: String, default: '' },
  confirmText: { type: String, default: '确认' },
  cancelText: { type: String, default: '取消' },
  danger: Boolean,
})

defineEmits(['confirm', 'cancel'])
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(0, 0, 0, 0.44);
}

.modal {
  width: min(420px, 100%);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--bg-elevated);
  box-shadow: var(--shadow-elevated);
}

.modal__head,
.modal__body,
.modal__actions {
  padding: 14px 16px;
}

.modal__head {
  border-bottom: 1px solid var(--border-subtle);
}

.modal__head strong {
  color: var(--text-primary);
  font-size: 15px;
}

.modal__body p {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.6;
}

.modal__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  border-top: 1px solid var(--border-subtle);
}
</style>

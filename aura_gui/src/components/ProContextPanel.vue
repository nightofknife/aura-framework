<template>
  <Teleport to="body">
    <Transition name="overlay-fade">
      <div v-if="openLocal" class="aether-overlay" @click="requestClose" />
    </Transition>

    <Transition name="drawer-slide" @after-leave="$emit('closed')">
      <aside
          v-if="openLocal"
          class="aether-drawer glass glass-thick glass-refract glass-shimmer"
          :style="{ width }"
          role="dialog"
          aria-modal="true"
          :aria-label="title || 'Panel'"
          @keydown.esc.stop.prevent="requestClose"
      >
        <header class="drawer-head">
          <div class="title">
            <span class="badge">CONFIG</span>
            <strong>{{ title }}</strong>
          </div>
          <button class="btn-icon" aria-label="Close" @click="requestClose">✕</button>
        </header>

        <div class="drawer-body">
          <slot/>
        </div>
      </aside>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue';

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  width: { type: String, default: '560px' },
});
const emit = defineEmits(['close', 'update:open', 'closed']);

const openLocal = ref(!!props.open);
watch(() => props.open, v => openLocal.value = v);

function requestClose() {
  openLocal.value = false;
  emit('update:open', false);
  emit('close');
}

function lockScroll(lock) {
  document.documentElement.style.overflow = lock ? 'hidden' : '';
}
watch(openLocal, v => lockScroll(v));
onMounted(() => lockScroll(openLocal.value));
onUnmounted(() => lockScroll(false));
</script>

<style scoped>
/* Overlay */
.aether-overlay {
  position: fixed; inset: 0;
  background: rgba(11, 18, 32, 0.45);
  backdrop-filter: blur(2px);
  z-index: 1000;
}

/* Drawer 只保留定位与圆角，玻璃质感由 .glass 类提供 */
.aether-drawer {
  position: fixed; top: 0; right: 0; height: 100vh;
  display: flex; flex-direction: column;
  z-index: 1001;
  border-top-left-radius: 16px; border-bottom-left-radius: 16px;
}

/* Header */
.drawer-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-frosted);
}
.title { display: flex; align-items: center; gap: 10px; }
.badge {
  font-size: 11px; font-weight: 700; letter-spacing: .08em;
  padding: 3px 8px; border-radius: 999px;
  color: var(--primary-accent);
  background: rgba(88,101,242,0.12); border: 1px solid rgba(88,101,242,0.28);
}

/* Body */
.drawer-body {
  padding: 16px;
  overflow: auto;
  display: grid; gap: 12px;
}
.btn-icon {
  border: none; background: transparent; cursor: pointer;
  width: 32px; height: 32px; border-radius: 10px; font-size: 16px;
  color: var(--text-secondary);
}
.btn-icon:hover { background: rgba(128,128,128,0.12); }

/* Animations */
.overlay-fade-enter-active, .overlay-fade-leave-active { transition: opacity var(--dur) var(--ease); }
.overlay-fade-enter-from, .overlay-fade-leave-to { opacity: 0; }
.drawer-slide-enter-active, .drawer-slide-leave-active { transition: transform var(--dur) var(--ease); }
.drawer-slide-enter-from, .drawer-slide-leave-to { transform: translateX(100%); }
</style>

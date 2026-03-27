<template>
  <Teleport to="body">
    <Transition name="overlay-fade">
      <div v-if="openLocal" class="brief-overlay" @click="requestClose" />
    </Transition>

    <Transition name="drawer-slide" @after-leave="$emit('closed')">
      <aside
        v-if="openLocal"
        class="brief-drawer"
        :style="{ width }"
        role="dialog"
        aria-modal="true"
        :aria-label="title || 'Task Brief'"
        @keydown.esc.stop.prevent="requestClose"
      >
        <header class="brief-drawer__head">
          <div>
            <span class="brief-drawer__kicker">Task Brief</span>
            <strong class="brief-drawer__title">{{ title }}</strong>
          </div>
          <button class="brief-drawer__close" aria-label="Close" @click="requestClose">X</button>
        </header>

        <div class="brief-drawer__body">
          <slot />
        </div>
      </aside>
    </Transition>
  </Teleport>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  width: { type: String, default: '560px' },
})

const emit = defineEmits(['close', 'update:open', 'closed'])
const openLocal = ref(!!props.open)

watch(() => props.open, (value) => {
  openLocal.value = value
})

watch(openLocal, (value) => {
  document.documentElement.style.overflow = value ? 'hidden' : ''
})

function requestClose() {
  openLocal.value = false
  emit('update:open', false)
  emit('close')
}

onMounted(() => {
  document.documentElement.style.overflow = openLocal.value ? 'hidden' : ''
})

onUnmounted(() => {
  document.documentElement.style.overflow = ''
})
</script>

<style scoped>
.brief-overlay {
  position: fixed;
  inset: 0;
  z-index: 90;
  background: rgba(0, 0, 0, 0.38);
  backdrop-filter: blur(2px);
}

.brief-drawer {
  position: fixed;
  top: 0;
  right: 0;
  z-index: 91;
  display: flex;
  height: 100vh;
  max-width: 92vw;
  flex-direction: column;
  border-left: 1px solid rgba(224, 214, 186, 0.1);
  background: linear-gradient(180deg, rgba(74, 82, 86, 0.98), rgba(46, 55, 58, 0.98));
  box-shadow: var(--shadow-soft), var(--shadow-inset);
}

.brief-drawer__head {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 22px 14px;
  border-bottom: 1px solid rgba(224, 214, 186, 0.08);
}

.brief-drawer__kicker {
  display: block;
  color: var(--paper);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.brief-drawer__title {
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 34px;
  letter-spacing: 0.08em;
  line-height: 0.9;
  text-transform: uppercase;
}

.brief-drawer__close {
  width: 34px;
  height: 34px;
  border: 1px solid rgba(224, 214, 186, 0.1);
  background: rgba(31, 38, 41, 0.56);
  color: var(--text-main);
  cursor: pointer;
  text-transform: uppercase;
}

.brief-drawer__body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 16px;
  overflow: auto;
  padding: 20px 22px 28px;
}

.overlay-fade-enter-active,
.overlay-fade-leave-active,
.drawer-slide-enter-active,
.drawer-slide-leave-active {
  transition: all var(--dur-med) var(--ease);
}

.overlay-fade-enter-from,
.overlay-fade-leave-to {
  opacity: 0;
}

.drawer-slide-enter-from,
.drawer-slide-leave-to {
  transform: translateX(100%);
}
</style>
